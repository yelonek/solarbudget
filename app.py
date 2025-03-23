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
            return cached_data

    # If no valid cache, try to fetch new data
    site_id = os.getenv("SOLCAST_SITE_ID", "6803-0207-f7d6-3a1f")
    url = f"https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts"

    try:
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
        df = df.infer_objects(copy=False)  # Fix deprecation warning
        df = df.set_index("period_end").resample("15min").interpolate()

        solcast_cache["forecast"] = df
        return df

    except requests.exceptions.RequestException as e:
        print(f"Error fetching Solcast data: {e}")
        # If we have cached data, return it even if expired
        if "forecast" in solcast_cache:
            return solcast_cache["forecast"]
        return pd.DataFrame()


def get_pse_prices():
    if "prices" in pse_cache:
        return pse_cache["prices"]

    current_time = datetime.now()
    today = current_time.strftime("%Y-%m-%d")
    tomorrow = (current_time + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        # Use the correct API endpoint for RCE (Rynkowa cena energii)
        url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{today}'"
        response = requests.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()

        data = response.json()
        prices = []

        for item in data:
            prices.append(
                {
                    "datetime": f"{item['business_date']}-{item['udtczas_oreb']}:00",
                    "price": float(item["rce_pln"]),
                }
            )

        if current_time.hour >= 16:
            tomorrow_url = (
                f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{tomorrow}'"
            )
            tomorrow_response = requests.get(
                tomorrow_url, headers={"Accept": "application/json"}
            )
            tomorrow_response.raise_for_status()

            tomorrow_data = tomorrow_response.json()
            for item in tomorrow_data:
                prices.append(
                    {
                        "datetime": f"{item['business_date']}-{item['udtczas_oreb']}:00",
                        "price": float(item["rce_pln"]),
                    }
                )

        pse_cache["prices"] = prices
        return prices

    except requests.exceptions.RequestException as e:
        print(f"Error fetching PSE data: {e}")
        return []


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    solar_data = get_solcast_data()
    prices = get_pse_prices()

    if solar_data.empty:
        raise HTTPException(
            status_code=500, detail="Unable to fetch solar forecast data"
        )

    if not prices:
        raise HTTPException(status_code=500, detail="Unable to fetch price data")

    solar_data_dict = solar_data.reset_index().to_dict("records")
    for record in solar_data_dict:
        record["period_end"] = record["period_end"].isoformat()

    daily_totals = solar_data.resample("D")["pv_estimate"].sum() * 0.25
    daily_totals_dict = {
        timestamp.strftime("%Y-%m-%d"): value
        for timestamp, value in daily_totals.items()
    }

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

    uvicorn.run(app, host="0.0.0.0", port=8000)
