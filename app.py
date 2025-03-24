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
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, JSON
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
engine = create_engine("sqlite:///solarbudget.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

app = FastAPI(title="Solar Budget")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

pse_cache = TTLCache(maxsize=100, ttl=86400)  # 24 hour cache for PSE data


def get_solcast_data():
    session = Session()
    try:
        # Check if we have recent data (less than 2 hours old)
        latest_data = (
            session.query(SolcastData).order_by(SolcastData.timestamp.desc()).first()
        )
        if latest_data is not None and (
            datetime.utcnow() - latest_data.timestamp
        ) < timedelta(hours=2):
            logger.info("Using cached Solcast data from database")
            df = pd.DataFrame.from_records(latest_data.data)
            # Convert period_end to datetime and set as index
            df["period_end"] = pd.to_datetime(df["period_end"])
            df = df.set_index("period_end")
            return df

        # If no recent data, fetch new data
        logger.info("Fetching new Solcast data")
        site_id = os.getenv("SOLCAST_SITE_ID", "6803-0207-f7d6-3a1f")
        url = f"https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts"
        params = {"format": "json"}
        headers = {
            "Authorization": f"Bearer {os.getenv('SOLCAST_API_KEY')}",
            "Accept": "application/json",
        }

        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict) or "forecasts" not in data:
            logger.error("Invalid Solcast API response format")
            if latest_data is not None:
                logger.info("Using expired cached data due to invalid response")
                df = pd.DataFrame.from_records(latest_data.data)
                df["period_end"] = pd.to_datetime(df["period_end"])
                df = df.set_index("period_end")
                return df
            return pd.DataFrame()

        # Process the data
        df = pd.DataFrame(data["forecasts"])
        df["period_end"] = pd.to_datetime(df["period_end"])
        df = df.infer_objects()
        df = df.set_index("period_end").resample("15min").interpolate()

        # Convert DataFrame to records with ISO format timestamps
        records = df.reset_index().to_dict(orient="records")
        for record in records:
            if isinstance(record["period_end"], pd.Timestamp):
                record["period_end"] = record["period_end"].isoformat()

        # Save to database
        new_data = SolcastData(timestamp=datetime.utcnow(), data=records)
        session.add(new_data)
        session.commit()

        logger.info("Successfully fetched and cached Solcast data")
        return df

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Solcast data: {e}")
        if latest_data is not None:
            logger.info("Using expired cached data due to API error")
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
        # Check if we have recent data (less than 24 hours old)
        latest_data = session.query(PSEData).order_by(PSEData.timestamp.desc()).first()
        if latest_data is not None and (
            datetime.utcnow() - latest_data.timestamp
        ) < timedelta(hours=24):
            logger.info("Using cached PSE data from database")
            # Convert cached data to proper format
            try:
                prices = []
                for item in latest_data.data:
                    try:
                        # Parse the datetime string
                        dt_str = item["datetime"]
                        if " - " in dt_str:  # Handle old format
                            # Split into date and time parts
                            parts = dt_str.split(
                                "-", 3
                            )  # ['2025', '03', '24', '00:00 - 00:15:00']
                            date_str = "-".join(parts[:3])  # '2025-03-24'
                            time_str = parts[3].split(" - ")[0].strip()  # '00:00'

                            # Parse the complete datetime
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

                if prices:  # Only return processed data if we have valid entries
                    return prices
                logger.error("No valid prices after processing cached data")
                return latest_data.data  # Return original data if no valid entries
            except Exception as e:
                logger.error(f"Error processing cached data: {e}")
                return latest_data.data  # Return original data if processing fails

        # If no recent data, fetch new data
        logger.info("Fetching new PSE data")
        current_time = datetime.now()
        today = current_time.strftime("%Y-%m-%d")
        tomorrow = (current_time + timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{today}'"
            logger.info(f"Fetching PSE data for {today}")
            response = requests.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()

            data = response.json()
            logger.debug(f"PSE API response: {data}")

            if not isinstance(data, dict) or "value" not in data:
                logger.error(f"Unexpected PSE API response format: {type(data)}")
                if latest_data is not None:
                    logger.info("Using expired cached data due to invalid response")
                    return latest_data.data
                return []

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

            prices = []
            for item in data["value"]:
                try:
                    if not isinstance(item, dict):
                        logger.error(f"Unexpected item format: {type(item)}")
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

            if current_time.hour >= 16:
                tomorrow_url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{tomorrow}'"
                logger.info(f"Fetching PSE data for {tomorrow}")
                tomorrow_response = requests.get(
                    tomorrow_url, headers={"Accept": "application/json"}
                )
                tomorrow_response.raise_for_status()

                tomorrow_data = tomorrow_response.json()
                logger.debug(f"PSE API tomorrow response: {tomorrow_data}")

                if not isinstance(tomorrow_data, dict) or "value" not in tomorrow_data:
                    logger.error(
                        f"Unexpected PSE API tomorrow response format: {type(tomorrow_data)}"
                    )
                    return prices

                for item in tomorrow_data["value"]:
                    try:
                        if not isinstance(item, dict):
                            logger.error(
                                f"Unexpected tomorrow item format: {type(item)}"
                            )
                            continue

                        dt = parse_pse_datetime(item["doba"], item["udtczas_oreb"])
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
                if latest_data is not None:
                    logger.info("Using expired cached data due to empty response")
                    return latest_data.data
                return []

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
            if latest_data is not None:
                logger.info("Using expired cached data due to API error")
                return latest_data.data
            return []

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

    # Calculate daily totals
    daily_totals = solar_data.resample("D")["pv_estimate"].sum() * 0.25
    daily_value_totals = solar_data.resample("D")["value"].sum()

    daily_totals_dict = {
        timestamp.strftime("%Y-%m-%d"): {
            "energy": energy,
            "value": daily_value_totals[timestamp],
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
            "solar_data": solar_data_dict,
            "prices": prices,
            "daily_totals": daily_totals_dict,
        },
    )


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Solar Budget application")
    uvicorn.run(app, host="0.0.0.0", port=8000)
