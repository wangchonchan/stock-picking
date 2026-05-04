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
    hk_tz = pytz.timezone('Asia/Hong_Kong')
    return datetime.datetime.now(hk_tz)

def calculate_rsi(data, window=14):
    """Calculate 14-day RSI using Wilder's Smoothing Method"""
    if len(data) < window + 1:
        return None
    
    delta = data.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # Standard Wilder's smoothing
    avg_gain = gain.ewm(alpha=1/window, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1/window, min_periods=window).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_stock_data(ticker):
    """Fetch REAL stock data from Yahoo Finance"""
    try:
        stock = yf.Ticker(ticker)
        
        # 1. Get history for price and RSI (Most reliable)
        hist = stock.history(period="2mo")
        if hist.empty:
            return None
            
        current_price = hist['Close'].iloc[-1]
        rsi = calculate_rsi(hist['Close'], window=14)
            
        # 2. Get PB and Name from info (Only real data)
        info = stock.info
        if not info:
            return None
            
        pb = info.get('priceToBook')
        name = info.get('shortName') or info.get('longName') or ticker
        
        # We only return if we have the core data requested
        return {
            "ticker": ticker,
            "name": name,
            "pb": pb,
            "rsi": rsi,
            "price": current_price
        }
    except Exception:
        return None

def screen_stocks(market='US'):
    if market == 'HK':
        # Load HK stocks from Excel file
        try:
            df = pd.read_excel('hk_stocks.xlsx')
            # Assuming 'Stock Number' column exists as seen in the file preview
            # Format to 4-digit HK stock code (e.g., 700 -> 0700.HK)
            tickers = [f"{int(row['Stock Number']):04d}.HK" for _, row in df.iterrows()]
        except Exception as e:
            print(f"Error loading hk_stocks.xlsx: {e}")
            # Fallback to a minimal list if file loading fails
            tickers = ["0700.HK", "9988.HK", "0005.HK"]
    else: # US
        # Top 80 US stocks (S&P 100 / Nasdaq 100)
        tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK-B", "JPM", "V", "UNH", "MA", "PG", "HD", "DIS",
            "PYPL", "ADBE", "NFLX", "INTC", "CSCO", "PEP", "KO", "PFE", "XOM", "CVX", "ABT", "CRM", "BAC", "COST", "WMT",
            "TMO", "AVGO", "ORCL", "ACN", "LIN", "NKE", "DHR", "ABBV", "AMD", "TXN", "PM", "UPS", "NEE", "MS", "RTX",
            "HON", "LOW", "UNP", "BMY", "AMAT", "SBUX", "CAT", "GS", "GE", "DE", "INTU", "PLD", "AXP", "T", "VZ", "C",
            "MDLZ", "ISRG", "GILD", "BKNG", "TJX", "ADP", "MDT", "LMT", "SYK", "CI", "VRTX", "MMC", "REGN", "ADI", "ZTS",
            "BSX", "AMT", "CB", "BA", "MU"
        ]
    
    tickers = list(set(tickers))
    results = []
    
    # Use ThreadPoolExecutor for real-time fetching
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(get_stock_data, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            try:
                data = future.result()
                if data:
                    results.append(data)
            except:
                continue
            
    # Section 1: 0 < PB < 1 (Strictly positive and less than 1)
    sec1 = [s for s in results if s['pb'] is not None and 0 < s['pb'] < 1]
    sec1 = sorted(sec1, key=lambda x: x['pb'])[:20]
    
    # Section 2: RSI < 35
    sec2 = [s for s in results if s['rsi'] is not None and s['rsi'] < 35]
    sec2 = sorted(sec2, key=lambda x: x['rsi'])[:20]
    
    # Section 3: RSI > 65
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
