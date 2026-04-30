import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import json
import os
from flask import Flask, request, jsonify, render_template
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Local storage configuration
RECORDS_DIR = "records"
if not os.path.exists(RECORDS_DIR):
    os.makedirs(RECORDS_DIR)

def calculate_rsi(data, window=14):
    """Calculate 14-day RSI using Wilder's Smoothing Method (standard)"""
    if len(data) < window + 1:
        return None
    
    delta = data.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # Use Wilder's smoothing (EMA with alpha = 1/window)
    avg_gain = gain.ewm(alpha=1/window, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1/window, min_periods=window).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        # Try to get info with a timeout or fallback
        info = stock.info
        
        # Robust price and PB retrieval
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        pb = info.get('priceToBook')
        name = info.get('shortName') or info.get('longName') or ticker
        
        # Get history for RSI (need at least 30 days for stable 14-day RSI)
        hist = stock.history(period="2mo")
        rsi = None
        if not hist.empty and len(hist) >= 14:
            rsi = calculate_rsi(hist['Close'], window=14)
            
        return {
            "ticker": ticker,
            "name": name,
            "pb": pb,
            "rsi": rsi,
            "price": price
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def screen_stocks(market='US'):
    # Expanded ticker lists to ensure we find enough matches
    if market == 'HK':
        # Top 80 HK stocks
        tickers = [
            "0700.HK", "9988.HK", "3690.HK", "1299.HK", "0005.HK", "0939.HK", "1398.HK", "2318.HK", "3988.HK", "3968.HK",
            "1810.HK", "1024.HK", "9618.HK", "9888.HK", "2015.HK", "2331.HK", "0001.HK", "0002.HK", "0003.HK", "0006.HK",
            "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0027.HK", "0066.HK", "0101.HK", "0151.HK", "0175.HK", "0267.HK",
            "0288.HK", "0386.HK", "0388.HK", "0669.HK", "0688.HK", "0762.HK", "0823.HK", "0857.HK", "0883.HK", "0941.HK",
            "0960.HK", "0992.HK", "1038.HK", "1044.HK", "1088.HK", "1093.HK", "1109.HK", "1113.HK", "1177.HK", "1199.HK",
            "1211.HK", "1313.HK", "1378.HK", "1928.HK", "1929.HK", "2020.HK", "2269.HK", "2313.HK", "2319.HK", "2382.HK",
            "2388.HK", "2628.HK", "2688.HK", "3323.HK", "3328.HK", "3333.HK", "3888.HK", "6030.HK", "6098.HK", "6618.HK",
            "6690.HK", "6862.HK", "9633.HK", "9961.HK", "9999.HK", "0010.HK", "0019.HK", "0083.HK", "0101.HK", "0291.HK"
        ]
    else: # US
        # Top 80 US stocks (S&P 100 subset)
        tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK-B", "JPM", "V", "UNH", "MA", "PG", "HD", "DIS",
            "PYPL", "ADBE", "NFLX", "INTC", "CSCO", "PEP", "KO", "PFE", "XOM", "CVX", "ABT", "CRM", "BAC", "COST", "WMT",
            "TMO", "AVGO", "ORCL", "ACN", "LIN", "NKE", "DHR", "ABBV", "NEXT", "AMD", "TXN", "PM", "UPS", "NEE", "MS",
            "RTX", "HON", "LOW", "UNP", "BMY", "AMAT", "SBUX", "CAT", "GS", "GE", "DE", "INTU", "PLD", "AXP", "T",
            "VZ", "C", "MDLZ", "ISRG", "GILD", "BKNG", "TJX", "ADP", "MDT", "LMT", "SYK", "CI", "VRTX", "MMC", "REGN",
            "ADI", "ZTS", "BSX", "AMT", "CB"
        ]
    
    results = []
    # Use ThreadPoolExecutor for faster fetching
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(filter(None, executor.map(get_stock_data, tickers)))
            
    # Section 1: PB < 1
    sec1 = [s for s in results if s['pb'] is not None and s['pb'] < 1]
    sec1 = sorted(sec1, key=lambda x: x['pb'])[:20]
    
    # Section 2: RSI < 35
    sec2 = [s for s in results if s['rsi'] is not None and s['rsi'] < 35]
    sec2 = sorted(sec2, key=lambda x: x['rsi'])[:20]
    
    # Section 3: RSI > 65
    sec3 = [s for s in results if s['rsi'] is not None and s['rsi'] > 65]
    sec3 = sorted(sec3, key=lambda x: x['rsi'], reverse=True)[:20]
    
    return {
        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market": market,
        "pb_less_1": sec1,
        "rsi_less_35": sec2,
        "rsi_greater_65": sec3
    }

def save_locally(data):
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{data['market']}.json"
        file_path = os.path.join(RECORDS_DIR, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True, filename
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/screen', methods=['POST'])
def api_screen():
    market = request.json.get('market', 'US')
    data = screen_stocks(market)
    success, filename = save_locally(data)
    return jsonify({
        "success": success,
        "data": data
    })

@app.route('/api/records', methods=['GET'])
def get_records():
    if not os.path.exists(RECORDS_DIR):
        return jsonify([])
    files = sorted([f for f in os.listdir(RECORDS_DIR) if f.endswith('.json')], reverse=True)
    return jsonify(files)

@app.route('/api/records/<filename>', methods=['GET'])
def get_record_detail(filename):
    file_path = os.path.join(RECORDS_DIR, filename)
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({"error": "File not found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
