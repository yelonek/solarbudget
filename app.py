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

app = FastAPI(title="Solar Budget")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

solcast_cache = TTLCache(maxsize=100, ttl=int(os.getenv("CACHE_TIMEOUT", "10800")))
pse_cache = TTLCache(maxsize=100, ttl=86400)  # 24 hour cache for PSE data


def get_solcast_data():
    # First check if we have valid cached data
    if "forecast" in solcast_cache:
        cached_data = solcast_cache["forecast"]
        if not cached_data.empty:
            logger.info("Using cached Solcast data")
            return cached_data

    # If no valid cache, try to fetch new data
    site_id = os.getenv("SOLCAST_SITE_ID", "6803-0207-f7d6-3a1f")
    url = f"https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts"

    try:
        logger.info("Fetching new Solcast data")
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {os.getenv('SOLCAST_API_KEY')}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()

        if "forecasts" not in data:
            raise ValueError("No forecast data in response")

        df = pd.DataFrame(data["forecasts"])
        df["period_end"] = pd.to_datetime(df["period_end"])
        df = df.infer_objects()  # Fix deprecation warning
        df = df.set_index("period_end").resample("15min").interpolate()

        solcast_cache["forecast"] = df
        logger.info("Successfully fetched and cached Solcast data")
        return df

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Solcast data: {e}")
        # If we have cached data, return it even if expired
        if "forecast" in solcast_cache:
            logger.info("Using expired cached Solcast data due to API error")
            return solcast_cache["forecast"]
        return pd.DataFrame()


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

    solar_data_dict = solar_data.reset_index().to_dict("records")
    for record in solar_data_dict:
        record["period_end"] = record["period_end"].isoformat()

    daily_totals = solar_data.resample("D")["pv_estimate"].sum() * 0.25
    daily_totals_dict = {
        timestamp.strftime("%Y-%m-%d"): value
        for timestamp, value in daily_totals.items()
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
