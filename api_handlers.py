import requests
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

PSE_URL = "https://v1.api.raporty.pse.pl/api/rce-pln"

def get_solcast_data():
    proxy_url = os.getenv("SOLCAST_PROXY_URL")
    
    if proxy_url:
        # Use proxy service
        url = f"{proxy_url.rstrip('/')}/forecasts"
        params = {"format": "json"}
    else:
        # Use direct Solcast API
        site_id = os.getenv("SOLCAST_SITE_ID", "6803-0207-f7d6-3a1f")
        url = f"https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts"
        params = {
            "format": "json",
            "api_key": os.getenv("SOLCAST_API_KEY")
        }
    
    response = requests.get(url, params=params)
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
