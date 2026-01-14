import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

PSE_URL = "https://api.raporty.pse.pl/api/rce-pln"


def get_pse_data(date_obj):
    """
    date_obj: datetime.date lub datetime.datetime
    """
    if isinstance(date_obj, datetime):
        date_str = date_obj.strftime("%Y-%m-%d")
    else:
        date_str = date_obj.isoformat()
    params = {"$filter": f"business_date eq '{date_str}'"}
    response = requests.get(PSE_URL, params=params)
    if response.status_code == 200:
        return response.json().get("value", [])
    return None
