from datetime import datetime, timedelta
import requests
import pandas as pd
from cachetools import TTLCache
from dotenv import load_dotenv
import os
from io import StringIO
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import json
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Float,
    JSON,
    inspect,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Set up file handler
file_handler = RotatingFileHandler(
    "logs/app.log", maxBytes=1024 * 1024, backupCount=5  # 1MB
)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

# Get logger
logger = logging.getLogger("solarbudget")
logger.addHandler(file_handler)

load_dotenv()

# Database setup
Base = declarative_base()


class SolcastData(Base):
    __tablename__ = "solcast_data"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PSEData(Base):
    __tablename__ = "pse_data"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# Create database engine
db_path = os.getenv("DATABASE_URL", "sqlite:///data/solarbudget.db")
if db_path.startswith("sqlite:///"):
    # Extract the path part
    path_part = db_path[10:]
    # Get absolute path relative to current directory
    abs_path = os.path.abspath(path_part)
    # Ensure the directory exists
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    # Create the engine with the absolute path
    engine = create_engine(f"sqlite:///{abs_path}")
else:
    engine = create_engine(db_path)


def check_database_health():
    """Check database health on startup."""
    try:
        # Check if database file exists
        db_file = (
            abs_path if "abs_path" in locals() else db_path.replace("sqlite:///", "")
        )
        logger.info(f"Checking database file: {db_file}")
        if os.path.exists(db_file):
            logger.info(f"Database file exists at {db_file}")
            logger.info(
                f"Database file permissions: {oct(os.stat(db_file).st_mode)[-3:]}"
            )
            logger.info(f"Database file size: {os.path.getsize(db_file)} bytes")
        else:
            logger.error(f"Database file does not exist at {db_file}")
            return False

        # Check if we can read from the database
        session = Session()
        try:
            # Check if tables exist
            logger.info("Checking database schema...")
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            logger.info(f"Found tables: {tables}")

            if "solcast_data" not in tables:
                logger.error("solcast_data table does not exist")
                return False

            # Check if we can read from the table
            logger.info("Checking if we can read from solcast_data table...")
            count = session.query(SolcastData).count()
            logger.info(f"Found {count} records in solcast_data table")

            # Check if we can write to the table
            logger.info("Checking if we can write to solcast_data table...")
            test_data = SolcastData(
                timestamp=datetime.utcnow(), data=[{"test": "data"}]
            )
            session.add(test_data)
            session.commit()
            logger.info("Successfully wrote test data to database")
            session.rollback()
            logger.info("Successfully rolled back test data")

            return True
        except Exception as e:
            logger.error(f"Error checking database: {e}")
            return False
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error in database health check: {e}")
        return False


# Create tables if they don't exist
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Check database health on startup
if not check_database_health():
    logger.error("Database health check failed")
else:
    logger.info("Database health check passed")

app = FastAPI(title="Solar Budget")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

pse_cache = TTLCache(maxsize=100, ttl=86400)  # 24 hour cache for PSE data


def get_solcast_data():
    session = Session()
    try:
        # Get all recent records, ordered by timestamp
        logger.info("Querying database for recent records")
        recent_records = (
            session.query(SolcastData)
            .order_by(SolcastData.timestamp.desc())
            .limit(2)
            .all()
        )

        logger.info(f"Found {len(recent_records)} recent records")
        if recent_records:
            logger.info(f"First record timestamp: {recent_records[0].timestamp}")
            logger.info(f"First record data type: {type(recent_records[0].data)}")
            if recent_records[0].data:
                logger.info(f"First record data length: {len(recent_records[0].data)}")
                logger.info(
                    f"First record data sample: {recent_records[0].data[:1] if isinstance(recent_records[0].data, list) else 'Not a list'}"
                )
            if len(recent_records) > 1:
                logger.info(f"Second record timestamp: {recent_records[1].timestamp}")
                logger.info(f"Second record data type: {type(recent_records[1].data)}")
                if recent_records[1].data:
                    logger.info(
                        f"Second record data length: {len(recent_records[1].data)}"
                    )
                    logger.info(
                        f"Second record data sample: {recent_records[1].data[:1] if isinstance(recent_records[1].data, list) else 'Not a list'}"
                    )

        latest_data = recent_records[0] if recent_records else None
        previous_data = recent_records[1] if len(recent_records) > 1 else None

        current_time = datetime.utcnow()
        should_fetch_new = False

        if latest_data is None or (current_time - latest_data.timestamp) > timedelta(
            minutes=30
        ):
            should_fetch_new = True
            logger.info("Will fetch new data from API")

        df = None
        if should_fetch_new:
            # Fetch new data from API
            logger.info("Fetching new Solcast data")
            site_id = os.getenv("SOLCAST_SITE_ID", "6803-0207-f7d6-3a1f")
            url = f"https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts"
            params = {"format": "json"}
            headers = {
                "Authorization": f"Bearer {os.getenv('SOLCAST_API_KEY')}",
                "Accept": "application/json",
            }

            try:
                response = requests.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

                if not isinstance(data, dict) or "forecasts" not in data:
                    logger.error("Invalid Solcast API response format")
                    raise ValueError("Invalid API response format")

                # Process the new data
                df = pd.DataFrame(data["forecasts"])
                df["period_end"] = pd.to_datetime(df["period_end"])
                df = df.set_index("period_end").resample("15min").interpolate()

                # Check if the new data starts too late in the day
                earliest_time = df.index.min()
                current_date = current_time.date()
                expected_start = pd.Timestamp(current_date).replace(
                    hour=5
                )  # Expect data from 5 AM

                logger.info(f"New data earliest time: {earliest_time}")
                logger.info(f"Expected start time: {expected_start}")

                if earliest_time.time() > expected_start.time():
                    logger.info(
                        f"New data starts late at {earliest_time.time()}, checking previous data"
                    )

                    if previous_data:
                        prev_df = pd.DataFrame.from_records(previous_data.data)
                        prev_df["period_end"] = pd.to_datetime(prev_df["period_end"])
                        prev_df = prev_df.set_index("period_end")

                        logger.info(
                            f"Previous data range: {prev_df.index.min()} to {prev_df.index.max()}"
                        )

                        # Filter previous data for early morning hours of current date
                        morning_data = prev_df[
                            (prev_df.index.date == current_date)
                            & (prev_df.index < earliest_time)
                        ]

                        logger.info(f"Found {len(morning_data)} morning data points")
                        if not morning_data.empty:
                            logger.info(
                                f"Morning data range: {morning_data.index.min()} to {morning_data.index.max()}"
                            )
                            logger.info("Merging morning hours from previous data")
                            df = pd.concat([morning_data, df])
                            df = df.sort_index()
                            logger.info(
                                f"Final data range after merge: {df.index.min()} to {df.index.max()}"
                            )

                # Convert DataFrame to records with ISO format timestamps
                records = df.reset_index().to_dict(orient="records")
                for record in records:
                    if isinstance(record["period_end"], pd.Timestamp):
                        record["period_end"] = record["period_end"].isoformat()

                # Save to database
                new_data = SolcastData(timestamp=current_time, data=records)
                session.add(new_data)
                session.commit()

                logger.info("Successfully fetched and cached Solcast data")

            except Exception as e:
                logger.error(f"Error fetching new Solcast data: {e}")
                if latest_data and latest_data.data:
                    logger.info("Using latest cached data due to API error")
                    df = pd.DataFrame.from_records(latest_data.data)
                    df["period_end"] = pd.to_datetime(df["period_end"])
                    df = df.set_index("period_end")
                else:
                    logger.error("No cached data available")
                    return pd.DataFrame()

        else:
            # Use cached data
            logger.info("Using cached Solcast data from database")
            df = pd.DataFrame.from_records(latest_data.data)
            df["period_end"] = pd.to_datetime(df["period_end"])
            df = df.set_index("period_end")

        # Check for missing morning data regardless of data source
        earliest_time = df.index.min()
        current_date = current_time.date()
        expected_start = pd.Timestamp(current_date).replace(
            hour=5
        )  # Expect data from 5 AM

        logger.info(f"Data earliest time: {earliest_time}")
        logger.info(f"Expected start time: {expected_start}")

        if earliest_time.time() > expected_start.time():
            logger.info(
                f"Data starts late at {earliest_time.time()}, checking previous data"
            )

            if previous_data:
                prev_df = pd.DataFrame.from_records(previous_data.data)
                prev_df["period_end"] = pd.to_datetime(prev_df["period_end"])
                prev_df = prev_df.set_index("period_end")

                logger.info(
                    f"Previous data range: {prev_df.index.min()} to {prev_df.index.max()}"
                )

                # Filter previous data for early morning hours of current date
                morning_data = prev_df[
                    (prev_df.index.date == current_date)
                    & (prev_df.index < earliest_time)
                ]

                logger.info(f"Found {len(morning_data)} morning data points")
                if not morning_data.empty:
                    logger.info(
                        f"Morning data range: {morning_data.index.min()} to {morning_data.index.max()}"
                    )
                    logger.info("Merging morning hours from previous data")
                    df = pd.concat([morning_data, df])
                    df = df.sort_index()
                    logger.info(
                        f"Final data range after merge: {df.index.min()} to {df.index.max()}"
                    )

                    if should_fetch_new:
                        # Only save to database if this was new data
                        records = df.reset_index().to_dict(orient="records")
                        for record in records:
                            if isinstance(record["period_end"], pd.Timestamp):
                                record["period_end"] = record["period_end"].isoformat()

                        new_data = SolcastData(timestamp=current_time, data=records)
                        session.add(new_data)
                        session.commit()

        logger.info(f"Final data range: {df.index.min()} to {df.index.max()}")
        return df

    except Exception as e:
        logger.error(f"Unexpected error in get_solcast_data: {e}")
        if latest_data and latest_data.data:
            logger.info("Using latest cached data due to unexpected error")
            df = pd.DataFrame.from_records(latest_data.data)
            df["period_end"] = pd.to_datetime(df["period_end"])
            df = df.set_index("period_end")
            return df
        return pd.DataFrame()
    finally:
        session.close()


def get_pse_prices():
    session = Session()
    try:
        # Check if we have recent data
        latest_data = session.query(PSEData).order_by(PSEData.timestamp.desc()).first()
        current_time = datetime.now()

        def parse_pse_datetime(date_str, time_str):
            """Parse PSE datetime from separate date and time strings."""
            try:
                # Clean time string - take only the start time if it's a range
                if " - " in time_str:
                    time_str = time_str.split(" - ")[0].strip()

                # Create datetime object
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                return dt
            except Exception as e:
                logger.error(f"Error parsing datetime: {date_str} {time_str} - {e}")
                raise

        should_fetch_new = False
        if latest_data is not None:
            # Check if data is from a previous day
            if latest_data.timestamp.date() < current_time.date():
                logger.info("Cached PSE data is from previous day, fetching new data")
                should_fetch_new = True
            # After 16:00, check if we have tomorrow's data
            elif current_time.hour >= 16:
                tomorrow = (current_time + timedelta(days=1)).date()
                cached_dates = {
                    datetime.fromisoformat(item["datetime"]).date()
                    for item in latest_data.data
                }
                if tomorrow not in cached_dates:
                    logger.info(
                        "Missing tomorrow's data after 16:00, fetching new data"
                    )
                    should_fetch_new = True
        else:
            should_fetch_new = True

        if not should_fetch_new:
            logger.info("Using cached PSE data from database")
            try:
                prices = []
                for item in latest_data.data:
                    try:
                        # Parse the datetime string
                        dt_str = item["datetime"]
                        if " - " in dt_str:  # Handle old format
                            # Split into date and time parts
                            parts = dt_str.split("-", 3)
                            date_str = "-".join(parts[:3])
                            time_str = parts[3].split(" - ")[0].strip()
                            dt = datetime.strptime(
                                f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                            )
                        else:  # Handle ISO format
                            dt = datetime.fromisoformat(dt_str)
                        prices.append(
                            {"datetime": dt.isoformat(), "price": item["price"]}
                        )
                    except Exception as e:
                        logger.error(
                            f"Error parsing cached datetime: {e}, item: {item}"
                        )
                        continue

                if prices:
                    return prices
                logger.error("No valid prices after processing cached data")
                should_fetch_new = True
            except Exception as e:
                logger.error(f"Error processing cached data: {e}")
                should_fetch_new = True

        if should_fetch_new:
            # Fetch new data
            logger.info("Fetching new PSE data")
            today = current_time.strftime("%Y-%m-%d")
            tomorrow = (current_time + timedelta(days=1)).strftime("%Y-%m-%d")

            try:
                # Fetch today's data
                url = (
                    f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{today}'"
                )
                logger.info(f"Fetching PSE data for {today}")
                response = requests.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()

                data = response.json()
                logger.debug(f"PSE API response: {data}")

                if not isinstance(data, dict) or "value" not in data:
                    logger.error(f"Unexpected PSE API response format: {type(data)}")
                    return latest_data.data if latest_data else []

                prices = []
                for item in data["value"]:
                    try:
                        if not isinstance(item, dict):
                            continue
                        dt = parse_pse_datetime(item["doba"], item["udtczas_oreb"])
                        prices.append(
                            {
                                "datetime": dt.isoformat(),
                                "price": float(item["rce_pln"]),
                            }
                        )
                    except (KeyError, ValueError) as e:
                        logger.error(f"Error processing PSE item: {e}, item: {item}")
                        continue

                # After 16:00, also fetch tomorrow's data
                if current_time.hour >= 16:
                    tomorrow_url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{tomorrow}'"
                    logger.info(f"Fetching PSE data for {tomorrow}")
                    tomorrow_response = requests.get(
                        tomorrow_url, headers={"Accept": "application/json"}
                    )
                    tomorrow_response.raise_for_status()

                    tomorrow_data = tomorrow_response.json()
                    if isinstance(tomorrow_data, dict) and "value" in tomorrow_data:
                        for item in tomorrow_data["value"]:
                            try:
                                if not isinstance(item, dict):
                                    continue
                                dt = parse_pse_datetime(
                                    item["doba"], item["udtczas_oreb"]
                                )
                                prices.append(
                                    {
                                        "datetime": dt.isoformat(),
                                        "price": float(item["rce_pln"]),
                                    }
                                )
                            except (KeyError, ValueError) as e:
                                logger.error(
                                    f"Error processing PSE tomorrow item: {e}, item: {item}"
                                )
                                continue

                if not prices:
                    logger.error("No valid price data found in PSE API response")
                    return latest_data.data if latest_data else []

                # Save to database
                new_data = PSEData(timestamp=datetime.utcnow(), data=prices)
                session.add(new_data)
                session.commit()

                logger.info(
                    f"Successfully fetched and cached {len(prices)} PSE price records"
                )
                return prices

            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching PSE data: {e}")
                return latest_data.data if latest_data else []

    finally:
        session.close()


def calculate_energy_value(solar_data_df, prices):
    # Convert prices list to DataFrame
    prices_df = pd.DataFrame(prices)

    # Clean datetime strings - handle both formats
    def clean_datetime(dt_str):
        if " - " in dt_str:
            # Handle old format with time range
            dt_str = dt_str.split(" - ")[0]
        return dt_str

    # Clean and parse datetime
    prices_df["datetime"] = prices_df["datetime"].apply(clean_datetime)
    # Parse as naive datetime first, then localize to UTC
    prices_df["datetime"] = pd.to_datetime(prices_df["datetime"]).dt.tz_localize("UTC")
    prices_df = prices_df.set_index("datetime")

    # Ensure solar data is in UTC
    if solar_data_df.index.tz is None:
        solar_data_df.index = solar_data_df.index.tz_localize("UTC")
    elif str(solar_data_df.index.tz) != "UTC":
        solar_data_df.index = solar_data_df.index.tz_convert("UTC")

    # Resample prices to 15-min intervals to match solar data
    prices_df = prices_df.resample("15min").ffill()

    # Calculate value (PLN)
    # Convert MWh price to kWh and multiply by production
    solar_data_df["value"] = (
        solar_data_df["pv_estimate"] * prices_df["price"] / 1000 * 0.25
    )

    return solar_data_df


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    logger.info("Processing index page request")
    solar_data = get_solcast_data()
    prices = get_pse_prices()

    if solar_data.empty:
        logger.error("No solar data available")
        raise HTTPException(
            status_code=500, detail="Unable to fetch solar forecast data"
        )

    if not prices:
        logger.error("No PSE prices available")
        raise HTTPException(status_code=500, detail="Unable to fetch price data")

    # Calculate energy value
    solar_data = calculate_energy_value(solar_data, prices)

    # Convert DataFrame to records with ISO format timestamps
    solar_data_dict = solar_data.reset_index().to_dict("records")
    for record in solar_data_dict:
        if isinstance(record["period_end"], pd.Timestamp):
            record["period_end"] = record["period_end"].isoformat()

    # Separate data into today and tomorrow
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    # Filter solar data
    solar_data_today = [
        record
        for record in solar_data_dict
        if datetime.fromisoformat(record["period_end"]).date() == today
    ]
    solar_data_tomorrow = [
        record
        for record in solar_data_dict
        if datetime.fromisoformat(record["period_end"]).date() == tomorrow
    ]

    # Filter price data
    prices_today = [
        price
        for price in prices
        if datetime.fromisoformat(price["datetime"]).date() == today
    ]
    prices_tomorrow = [
        price
        for price in prices
        if datetime.fromisoformat(price["datetime"]).date() == tomorrow
    ]

    # Sort prices by datetime to ensure correct ordering
    prices_today.sort(key=lambda x: x["datetime"])
    prices_tomorrow.sort(key=lambda x: x["datetime"])

    # Find current price (closest to current time)
    current_time = datetime.now()
    current_hour = current_time.replace(minute=0, second=0, microsecond=0)

    # Find the price entry closest to current time
    current_price = None
    if prices_today:
        time_diffs = [
            abs((datetime.fromisoformat(p["datetime"]) - current_hour).total_seconds())
            for p in prices_today
        ]
        current_price = prices_today[time_diffs.index(min(time_diffs))]

    # Calculate daily totals
    daily_totals = solar_data.resample("D")["pv_estimate"].sum() * 0.25
    daily_value_totals = solar_data.resample("D")["value"].sum()

    # Calculate daily percentiles
    daily_totals_10 = solar_data.resample("D")["pv_estimate10"].sum() * 0.25
    daily_totals_90 = solar_data.resample("D")["pv_estimate90"].sum() * 0.25

    # Calculate value percentiles (handle division by zero)
    value_ratio = solar_data["value"] / (
        solar_data["pv_estimate"].replace(0, float("nan"))
    )
    solar_data["value10"] = solar_data["pv_estimate10"] * value_ratio.fillna(0)
    solar_data["value90"] = solar_data["pv_estimate90"] * value_ratio.fillna(0)
    daily_value_10 = solar_data.resample("D")["value10"].sum()
    daily_value_90 = solar_data.resample("D")["value90"].sum()

    # Calculate produced and remaining energy for today
    today_data = solar_data[solar_data.index.date == today]
    current_time = datetime.now()
    if today_data.index.tz is not None:
        current_time = current_time.astimezone(today_data.index.tz)

    # Calculate produced energy (up to current time)
    produced_data = today_data[today_data.index <= current_time]
    produced_energy = float(produced_data["pv_estimate"].sum() * 0.25)
    produced_energy10 = float(produced_data["pv_estimate10"].sum() * 0.25)
    produced_energy90 = float(produced_data["pv_estimate90"].sum() * 0.25)

    # Calculate remaining energy (after current time)
    remaining_data = today_data[today_data.index > current_time]
    remaining_energy = float(remaining_data["pv_estimate"].sum() * 0.25)
    remaining_energy10 = float(remaining_data["pv_estimate10"].sum() * 0.25)
    remaining_energy90 = float(remaining_data["pv_estimate90"].sum() * 0.25)

    daily_totals_dict = {
        timestamp.strftime("%Y-%m-%d"): {
            "energy": energy,
            "energy10": daily_totals_10[timestamp],
            "energy90": daily_totals_90[timestamp],
            "value": daily_value_totals[timestamp],
            "value10": daily_value_10[timestamp],
            "value90": daily_value_90[timestamp],
        }
        for timestamp, energy in daily_totals.items()
        if isinstance(timestamp, (pd.Timestamp, datetime))
    }

    # Log data being sent to frontend
    logger.info("Sample of prices data being sent to frontend:")
    logger.info(prices[:2] if prices else "No prices data")

    logger.info("Successfully prepared data for template")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "solar_data_today": solar_data_today,
            "solar_data_tomorrow": solar_data_tomorrow,
            "prices_today": prices_today,
            "prices_tomorrow": prices_tomorrow,
            "daily_totals": daily_totals_dict,
            "current_price": current_price,
            "produced_energy": produced_energy,
            "produced_energy10": produced_energy10,
            "produced_energy90": produced_energy90,
            "remaining_energy": remaining_energy,
            "remaining_energy10": remaining_energy10,
            "remaining_energy90": remaining_energy90,
            "current_time": datetime.now(),
        },
    )


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Solar Budget application")
    uvicorn.run(app, host="0.0.0.0", port=9000)
