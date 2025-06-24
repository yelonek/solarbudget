import requests
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

SOLCAST_URL = "https://api.solcast.com.au/rooftop_sites/6803-0207-f7d6-3a1f/forecasts"
PSE_URL = "https://v1.api.raporty.pse.pl/api/rce-pln"

def get_solcast_data():
    params = {
        "format": "json",
        "api_key": os.getenv("SOLCAST_API_KEY")
    }
    response = requests.get(SOLCAST_URL, params=params)
    if response.status_code == 200:
        return response.json()['forecasts']
    return None

def get_pse_data(date_obj):
    """
    date_obj: datetime.date lub datetime.datetime
    """
    if isinstance(date_obj, datetime):
        date_str = date_obj.strftime("%Y-%m-%d")
    else:
        date_str = date_obj.isoformat()
    params = {
        "$filter": f"business_date eq '{date_str}'"
    }
    response = requests.get(PSE_URL, params=params)
    if response.status_code == 200:
        return response.json().get('value', [])
    return None
