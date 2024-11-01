from flask import Flask, render_template
from datetime import datetime, timedelta
import requests
import pandas as pd
import json
from cachetools import TTLCache
from dotenv import load_dotenv
import os
from io import StringIO

load_dotenv()

app = Flask(__name__)
solcast_cache = TTLCache(maxsize=100, ttl=int(os.getenv('CACHE_TIMEOUT')))
pse_cache = TTLCache(maxsize=100, ttl=86400)  # 24 hour cache for PSE data

def get_solcast_data():
    if 'forecast' in solcast_cache:
        return solcast_cache['forecast']
    
    site_id = os.getenv('SOLCAST_SITE_ID', '6803-0207-f7d6-3a1f')
    url = f"https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts"
    
    try:
        response = requests.get(
            url,
            headers={
                'Authorization': f"Bearer {os.getenv('SOLCAST_API_KEY')}",
                'Accept': 'application/json'
            }
        )
        response.raise_for_status()
        data = response.json()
        
        if 'forecasts' not in data:
            raise ValueError("No forecast data in response")
            
        df = pd.DataFrame(data['forecasts'])
        print("Available columns:", df.columns.tolist())
        
        df['period_end'] = pd.to_datetime(df['period_end'])
        df = df.set_index('period_end').resample('15T').interpolate()
        
        solcast_cache['forecast'] = df
        return df
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Solcast data: {e}")
        return pd.DataFrame()

def get_pse_prices():
    if 'prices' in pse_cache:
        return pse_cache['prices']
        
    current_time = datetime.now()
    today = current_time.strftime('%Y-%m-%d')
    tomorrow = (current_time + timedelta(days=1)).strftime('%Y-%m-%d')
    
    try:
        # Use RCE (energy prices) endpoint
        url = f"https://www.pse.pl/getcsv/-/export/csv/PL_CENY_RYN_EN/data/{today}"
        response = requests.get(url)
        response.raise_for_status()
        
        # Parse CSV response
        df = pd.read_csv(StringIO(response.text), sep=';')
        prices = []
        
        # Convert CSV data to required format
        for _, row in df.iterrows():
            prices.append({
                'datetime': f"{row['Data']}-{row['Godzina']}:00",
                'price': float(row['RCE'].replace(',', '.'))
            })
        
        if current_time.hour >= 16:
            tomorrow_url = f"https://www.pse.pl/getcsv/-/export/csv/PL_CENY_RYN_EN/data/{tomorrow}"
            tomorrow_response = requests.get(tomorrow_url)
            tomorrow_response.raise_for_status()
            
            tomorrow_df = pd.read_csv(StringIO(tomorrow_response.text), sep=';')
            for _, row in tomorrow_df.iterrows():
                prices.append({
                    'datetime': f"{row['Data']}-{row['Godzina']}:00",
                    'price': float(row['RCE'].replace(',', '.'))
                })
        
        pse_cache['prices'] = prices
        return prices
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching PSE data: {e}")
        return []

@app.route('/')
def index():
    solar_data = get_solcast_data()
    prices = get_pse_prices()
    
    if solar_data.empty:
        return "Error: Unable to fetch solar forecast data", 500
    
    if not prices:
        return "Error: Unable to fetch price data", 500
    
    # Convert index to ISO format strings for JSON serialization
    solar_data_dict = solar_data.reset_index().to_dict('records')
    for record in solar_data_dict:
        record['period_end'] = record['period_end'].isoformat()
        
    daily_totals = solar_data.resample('D')['pv_estimate'].sum() * 0.25
    daily_totals_dict = {
        timestamp.strftime('%Y-%m-%d'): value 
        for timestamp, value in daily_totals.items()
    }
    
    return render_template('index.html', 
                         solar_data=solar_data_dict,
                         prices=prices,
                         daily_totals=daily_totals_dict)

if __name__ == '__main__':
    app.run(debug=True)
