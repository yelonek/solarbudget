from flask import Flask, render_template, jsonify
from api_handlers import get_solcast_data, get_pse_data
from database import init_db, cache_data, get_cached_data

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/solcast')
def get_solcast():
    solcast_data = get_cached_data('solcast') or get_solcast_data()
    if solcast_data:
        cache_data('solcast', solcast_data)
    return jsonify(solcast_data)

@app.route('/api/pse')
def get_pse():
    pse_data = get_cached_data('pse') or get_pse_data()
    if pse_data:
        cache_data('pse', pse_data)
    return jsonify(pse_data)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
