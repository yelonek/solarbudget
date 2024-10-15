import sqlite3
import json
from datetime import datetime, timedelta

DATABASE = 'energy_forecast.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cache
                 (key TEXT PRIMARY KEY, data TEXT, timestamp DATETIME)''')
    conn.commit()
    conn.close()

def cache_data(key, data):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
              (key, json.dumps(data), datetime.now()))
    conn.commit()
    conn.close()

def get_cached_data(key):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT data, timestamp FROM cache WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    
    if result and datetime.now() - datetime.fromisoformat(result[1]) < timedelta(hours=1):
        return json.loads(result[0])
    return None
