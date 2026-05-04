import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import json
import time
from pathlib import Path
from flask import Flask, request, jsonify, render_template, abort
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz

app = Flask(__name__)
MAX_FETCH_RETRIES = 2
BACKOFF_SECONDS = [0.5, 1.0]
REQUEST_INTERVAL_SECONDS = 0.25
MAX_WORKERS = 2

# Local storage configuration
RECORDS_DIR = Path("records")
RECORDS_DIR.mkdir(exist_ok=True)

def get_hk_time():
    hk_tz = pytz.timezone('Asia/Hong_Kong')
    return datetime.datetime.now(hk_tz)

def calculate_rsi(data, window=14):
    if len(data) < window + 1:
        return None
    delta = data.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/window, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1/window, min_periods=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_stock_data(ticker, display_name=None):
    try:
        time.sleep(REQUEST_INTERVAL_SECONDS)
        stock = yf.Ticker(ticker)
        hist = None
        for attempt in range(MAX_FETCH_RETRIES + 1):
            hist = stock.history(period="2mo")
            if not hist.empty:
                break
            if attempt < MAX_FETCH_RETRIES:
                time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
        if hist is None or hist.empty:
            return None
        current_price = hist['Close'].iloc[-1]
        rsi = calculate_rsi(hist['Close'], window=14)
        
        pb = None
        name = ticker
        
        try:
            info = stock.info
            if info:
                pb = info.get('priceToBook')
                name = info.get('longName') or info.get('shortName') or ticker
        except:
            pass
            
        return {
            "ticker": ticker,
            "name": name,
            "pb": pb,
            "rsi": rsi,
            "price": current_price,
            "url": f"https://finance.yahoo.com/quote/{ticker}"
        }
    except:
        return None

def screen_stocks(market='US'):
    stock_list = []
    if market == 'HK':
        try:
            df = pd.read_excel('hk_stocks.xlsx')
            for _, row in df.iterrows():
                ticker = f"{int(row['Stock Number']):04d}.HK"
                stock_list.append((ticker, None))
        except:
            stock_list = [("0700.HK", None)]
    else:
        try:
            df = pd.read_excel('us_stocks.xlsx', skiprows=7)
            valid_df = df.dropna(subset=['Unnamed: 1'])
            for _, row in valid_df.iterrows():
                ticker = str(row['Unnamed: 1']).strip().replace('.', '-')
                if ticker.lower() == 'ticker': continue
                stock_list.append((ticker, None))
        except:
            stock_list = [("AAPL", None)]
    
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(get_stock_data, t, n): t for t, n in stock_list}
        for future in as_completed(future_to_stock):
            data = future.result()
            if data: results.append(data)
            
    sec1 = sorted([s for s in results if s['pb'] is not None and 0 < s['pb'] < 1], key=lambda x: x['pb'])[:30]
    sec2 = sorted([s for s in results if s['rsi'] is not None and s['rsi'] < 35], key=lambda x: x['rsi'])[:30]
    sec3 = sorted([s for s in results if s['rsi'] is not None and s['rsi'] > 65], key=lambda x: x['rsi'], reverse=True)[:30]
    
    return {
        "date": get_hk_time().strftime("%Y-%m-%d %H:%M"),
        "market": market,
        "pb_less_1": sec1,
        "rsi_less_35": sec2,
        "rsi_greater_65": sec3
    }

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/screen', methods=['POST'])
def api_screen():
    payload = request.get_json(silent=True) or {}
    market = str(payload.get('market', 'US')).upper()
    if market not in {'US', 'HK'}:
        return jsonify({"success": False, "message": "invalid market, only US/HK supported"}), 400
    data = screen_stocks(market)
    filename = f"{get_hk_time().strftime('%Y%m%d_%H%M%S')}_{market}.json"
    with open(RECORDS_DIR / filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    return jsonify({"success": True, "data": data})

@app.route('/api/records', methods=['GET'])
def get_records():
    files = sorted([p.name for p in RECORDS_DIR.glob('*.json')], reverse=True)
    return jsonify(files)

@app.route('/api/records/<filename>', methods=['GET'])
def get_record_detail(filename):
    safe_path = (RECORDS_DIR / filename).resolve()
    if safe_path.parent != RECORDS_DIR.resolve() or safe_path.suffix.lower() != '.json' or not safe_path.exists():
        abort(404)
    with open(safe_path, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
