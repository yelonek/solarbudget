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
    if "prices" in pse_cache:
        logger.info("Using cached PSE data")
        return pse_cache["prices"]

    current_time = datetime.now()
    today = current_time.strftime("%Y-%m-%d")
    tomorrow = (current_time + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        # Use the correct API endpoint for RCE (Rynkowa cena energii)
        url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{today}'"
        logger.info(f"Fetching PSE data for {today}")
        response = requests.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()

        data = response.json()
        logger.debug(f"PSE API response type: {type(data)}")
        logger.debug(f"PSE API response: {data}")

        # PSE API returns a dictionary with 'value' key containing the list
        if not isinstance(data, dict) or "value" not in data:
            logger.error(f"Unexpected PSE API response format: {type(data)}")
            return []

        prices = []
        for item in data["value"]:
            try:
                # Log each item for debugging
                logger.debug(f"Processing PSE item: {item}")
                if not isinstance(item, dict):
                    logger.error(f"Unexpected item format: {type(item)}")
                    continue

                prices.append(
                    {
                        "datetime": f"{item['doba']}-{item['udtczas_oreb']}:00",
                        "price": float(item["rce_pln"]),
                    }
                )
            except (KeyError, ValueError) as e:
                logger.error(f"Error processing PSE item: {e}, item: {item}")
                continue

        if current_time.hour >= 16:
            tomorrow_url = (
                f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{tomorrow}'"
            )
            logger.info(f"Fetching PSE data for {tomorrow}")
            tomorrow_response = requests.get(
                tomorrow_url, headers={"Accept": "application/json"}
            )
            tomorrow_response.raise_for_status()

            tomorrow_data = tomorrow_response.json()
            logger.debug(f"PSE API tomorrow response type: {type(tomorrow_data)}")
            logger.debug(f"PSE API tomorrow response: {tomorrow_data}")

            if not isinstance(tomorrow_data, dict) or "value" not in tomorrow_data:
                logger.error(
                    f"Unexpected PSE API tomorrow response format: {type(tomorrow_data)}"
                )
                return prices

            for item in tomorrow_data["value"]:
                try:
                    logger.debug(f"Processing PSE tomorrow item: {item}")
                    if not isinstance(item, dict):
                        logger.error(f"Unexpected tomorrow item format: {type(item)}")
                        continue

                    prices.append(
                        {
                            "datetime": f"{item['doba']}-{item['udtczas_oreb']}:00",
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
            return []

        pse_cache["prices"] = prices
        logger.info(f"Successfully fetched and cached {len(prices)} PSE price records")
        return prices

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching PSE data: {e}")
        return []


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

    # Convert DataFrame to records with ISO format timestamps
    solar_data_dict = solar_data.reset_index().to_dict("records")
    for record in solar_data_dict:
        if isinstance(record["period_end"], pd.Timestamp):
            record["period_end"] = record["period_end"].isoformat()

    # Calculate daily totals
    daily_totals = solar_data.resample("D")["pv_estimate"].sum() * 0.25
    daily_totals_dict = {
        timestamp.strftime("%Y-%m-%d"): value
        for timestamp, value in daily_totals.items()
        if isinstance(timestamp, (pd.Timestamp, datetime))
    }

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
