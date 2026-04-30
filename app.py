import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import json
import os
import time
from flask import Flask, request, jsonify, render_template
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz

app = Flask(__name__)

# Local storage configuration
RECORDS_DIR = "records"
if not os.path.exists(RECORDS_DIR):
    os.makedirs(RECORDS_DIR)

def get_hk_time():
    """Get current time in Hong Kong timezone"""
    hk_tz = pytz.timezone('Asia/Hong Kong')
    return datetime.datetime.now(hk_tz)

def calculate_rsi(data, window=14):
    """Calculate 14-day RSI using Wilder's Smoothing Method"""
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

def get_stock_data(ticker):
    try:
        # For HK stocks, ensure the ticker format is correct (e.g., 0005.HK)
        stock = yf.Ticker(ticker)
        
        # Use fast_info for basic metrics if possible, or history for price
        hist = stock.history(period="1mo")
        if hist.empty:
            return None
            
        # Calculate RSI
        rsi = None
        if len(hist) >= 14:
            rsi = calculate_rsi(hist['Close'], window=14)
            
        # Get price and PB from info
        info = stock.info
        price = info.get('currentPrice') or info.get('regularMarketPrice') or hist['Close'].iloc[-1]
        pb = info.get('priceToBook')
        name = info.get('shortName') or info.get('longName') or ticker
        
        return {
            "ticker": ticker,
            "name": name,
            "pb": pb,
            "rsi": rsi,
            "price": price
        }
    except Exception as e:
        return None

def screen_stocks(market='US'):
    if market == 'HK':
        # Expanded HK list: 0001.HK to 0300.HK + common tech stocks
        tickers = [f"{str(i).zfill(4)}.HK" for i in range(1, 301)] + \
                  ["9988.HK", "3690.HK", "1810.HK", "1024.HK", "9618.HK", "9888.HK", "2015.HK", "6618.HK", "9633.HK", "9961.HK", "9999.HK"]
    else: # US
        # S&P 500 subset
        tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK-B", "JPM", "V", "UNH", "MA", "PG", "HD", "DIS",
            "PYPL", "ADBE", "NFLX", "INTC", "CSCO", "PEP", "KO", "PFE", "XOM", "CVX", "ABT", "CRM", "BAC", "COST", "WMT",
            "TMO", "AVGO", "ORCL", "ACN", "LIN", "NKE", "DHR", "ABBV", "NEXT", "AMD", "TXN", "PM", "UPS", "NEE", "MS",
            "RTX", "HON", "LOW", "UNP", "BMY", "AMAT", "SBUX", "CAT", "GS", "GE", "DE", "INTU", "PLD", "AXP", "T",
            "VZ", "C", "MDLZ", "ISRG", "GILD", "BKNG", "TJX", "ADP", "MDT", "LMT", "SYK", "CI", "VRTX", "MMC", "REGN",
            "ADI", "ZTS", "BSX", "AMT", "CB", "BA", "MU", "LRCX", "PANW", "SNPS", "CDNS", "EQIX", "SCCO", "MO", "ETN"
        ]
    
    tickers = list(set(tickers))
    results = []
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_ticker = {executor.submit(get_stock_data, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            data = future.result()
            if data:
                results.append(data)
            
    sec1 = [s for s in results if s['pb'] is not None and s['pb'] < 1]
    sec1 = sorted(sec1, key=lambda x: x['pb'])[:20]
    
    sec2 = [s for s in results if s['rsi'] is not None and s['rsi'] < 35]
    sec2 = sorted(sec2, key=lambda x: x['rsi'])[:20]
    
    sec3 = [s for s in results if s['rsi'] is not None and s['rsi'] > 65]
    sec3 = sorted(sec3, key=lambda x: x['rsi'], reverse=True)[:20]
    
    return {
        "date": get_hk_time().strftime("%Y-%m-%d %H:%M"),
        "market": market,
        "pb_less_1": sec1,
        "rsi_less_35": sec2,
        "rsi_greater_65": sec3
    }

def save_locally(data):
    try:
        timestamp = get_hk_time().strftime("%Y%m%d_%H%M%S")
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
    try:
        market = request.json.get('market', 'US')
        data = screen_stocks(market)
        success, filename = save_locally(data)
        return jsonify({"success": success, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

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

@app.route('/api/records/<filename>', methods=['DELETE'])
def delete_record(filename):
    file_path = os.path.join(RECORDS_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return jsonify({"success": True})
    return jsonify({"error": "File not found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
