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
    
    avg_gain = gain.ewm(alpha=1/window, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1/window, min_periods=window).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_stock_data(ticker, display_name=None):
    """Fetch stock data with fallback logic for stability"""
    try:
        stock = yf.Ticker(ticker)
        
        # 1. Get history (More stable than info)
        hist = stock.history(period="2mo")
        if hist.empty:
            return None
            
        current_price = hist['Close'].iloc[-1]
        rsi = calculate_rsi(hist['Close'], window=14)
            
        # 2. Get PB and Name from info (With fallback)
        pb = None
        name = display_name or ticker
        
        try:
            # info is unstable, we wrap it in its own try-except
            info = stock.info
            if info:
                pb = info.get('priceToBook')
                # Use info name if available, otherwise keep display_name from Excel
                name = info.get('longName') or info.get('shortName') or name
        except Exception:
            # If info fails, we still have price and RSI, which is enough to show the stock
            pass
        
        return {
            "ticker": ticker,
            "name": name,
            "pb": pb,
            "rsi": rsi,
            "price": current_price,
            "url": f"https://finance.yahoo.com/quote/{ticker}"
        }
    except Exception:
        return None

def screen_stocks(market='US'):
    stock_list = []
    if market == 'HK':
        try:
            df = pd.read_excel('hk_stocks.xlsx')
            for _, row in df.iterrows():
                ticker = f"{int(row['Stock Number']):04d}.HK"
                name = row.get('Stock Name', ticker)
                stock_list.append((ticker, name))
        except Exception as e:
            print(f"Error loading HK list: {e}")
            stock_list = [("0700.HK", "Tencent"), ("9988.HK", "Alibaba")]
    else: # US
        try:
            # Skip the header rows in the provided Excel
            df = pd.read_excel('us_stocks.xlsx', skiprows=7)
            # Filter out rows where Ticker (Unnamed: 1) is NaN
            valid_df = df.dropna(subset=['Unnamed: 1'])
            for _, row in valid_df.iterrows():
                ticker = str(row['Unnamed: 1']).strip().replace('.', '-')
                if ticker.lower() == 'ticker': continue
                name = row.get('Unnamed: 2', ticker)
                stock_list.append((ticker, name))
        except Exception as e:
            print(f"Error loading US list: {e}")
            stock_list = [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA")]
    
    results = []
    # Use smaller batch size to avoid rate limiting from Yahoo Finance
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_stock = {executor.submit(get_stock_data, t, n): t for t, n in stock_list}
        for future in as_completed(future_to_stock):
            try:
                data = future.result()
                if data:
                    results.append(data)
            except:
                continue
            
    # Section 1: 0 < PB < 1
    sec1 = [s for s in results if s['pb'] is not None and 0 < s['pb'] < 1]
    sec1 = sorted(sec1, key=lambda x: x['pb'])[:30]
    
    # Section 2: RSI < 35
    sec2 = [s for s in results if s['rsi'] is not None and s['rsi'] < 35]
    sec2 = sorted(sec2, key=lambda x: x['rsi'])[:30]
    
    # Section 3: RSI > 65
    sec3 = [s for s in results if s['rsi'] is not None and s['rsi'] > 65]
    sec3 = sorted(sec3, key=lambda x: x['rsi'], reverse=True)[:30]
    
    return {
        "date": get_hk_time().strftime("%Y-%m-%d %H:%M"),
        "market": market,
        "pb_less_1": sec1,
        "rsi_less_35": sec2,
        "rsi_greater_65": sec3
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/screen', methods=['POST'])
def api_screen():
    try:
        market = request.json.get('market', 'US')
        data = screen_stocks(market)
        
        # Save locally
        timestamp = get_hk_time().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{market}.json"
        file_path = os.path.join(RECORDS_DIR, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        return jsonify({"success": True, "data": data})
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
