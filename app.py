import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import json
import os
import requests
import base64
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Configuration
GITHUB_REPO = "wangchonchan/stock-picking"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") # User needs to provide this in HF Secrets

def calculate_rsi(data, window=14):
    if len(data) < window + 1:
        return pd.Series([np.nan] * len(data))
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        pb = info.get('priceToBook')
        
        hist = stock.history(period="1mo")
        if not hist.empty and len(hist) >= 14:
            rsi_series = calculate_rsi(hist['Close'])
            current_rsi = rsi_series.iloc[-1]
        else:
            current_rsi = None
            
        return {
            "ticker": ticker,
            "name": info.get('shortName', ticker),
            "pb": pb,
            "rsi": current_rsi,
            "price": info.get('currentPrice') or info.get('regularMarketPrice')
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def screen_stocks(market='US'):
    # In a real scenario, we'd have a larger list. 
    # For this demo/tool, we'll use a representative list of top stocks.
    if market == 'HK':
        tickers = [
            "0700.HK", "9988.HK", "3690.HK", "1299.HK", "0005.HK", "0939.HK", "1398.HK", "2318.HK", "3988.HK", "3968.HK",
            "1810.HK", "1024.HK", "9618.HK", "9888.HK", "2015.HK", "2331.HK", "0001.HK", "0002.HK", "0003.HK", "0006.HK",
            "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0027.HK", "0066.HK", "0101.HK", "0151.HK", "0175.HK", "0267.HK",
            "0288.HK", "0386.HK", "0388.HK", "0669.HK", "0688.HK", "0762.HK", "0823.HK", "0857.HK", "0883.HK", "0941.HK"
        ]
    else: # US
        tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK-B", "JPM", "V", "UNH", "MA", "PG", "HD", "DIS",
            "PYPL", "ADBE", "NFLX", "INTC", "CSCO", "PEP", "KO", "PFE", "XOM", "CVX", "ABT", "CRM", "BAC", "COST", "WMT",
            "TMO", "AVGO", "ORCL", "ACN", "LIN", "NKE", "DHR", "ABBV", "NEXT", "AMD"
        ]
    
    results = []
    for t in tickers:
        data = get_stock_data(t)
        if data:
            results.append(data)
            
    # Section 1: PB < 1
    sec1 = [s for s in results if s['pb'] is not None and s['pb'] < 1][:20]
    # Section 2: RSI < 35
    sec2 = [s for s in results if s['rsi'] is not None and s['rsi'] < 35][:20]
    # Section 3: RSI > 65
    sec3 = [s for s in results if s['rsi'] is not None and s['rsi'] > 65][:20]
    
    return {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "market": market,
        "pb_less_1": sec1,
        "rsi_less_35": sec2,
        "rsi_greater_65": sec3
    }

def save_to_github(data):
    if not GITHUB_TOKEN:
        return False, "Missing GITHUB_TOKEN"
    
    date_str = data['date']
    market = data['market']
    file_path = f"records/{date_str}_{market}.json"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Check if file exists to get SHA
    res = requests.get(url, headers=headers)
    sha = None
    if res.status_code == 200:
        sha = res.json()['sha']
        
    content = base64.b64encode(json.dumps(data, indent=4, ensure_ascii=False).encode()).decode()
    
    payload = {
        "message": f"Add daily record for {date_str} ({market})",
        "content": content,
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha
        
    res = requests.put(url, headers=headers, json=payload)
    if res.status_code in [200, 201]:
        return True, "Success"
    else:
        return False, res.text

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/screen', methods=['POST'])
def api_screen():
    market = request.json.get('market', 'US')
    data = screen_stocks(market)
    success, msg = save_to_github(data)
    return jsonify({
        "success": success,
        "message": msg,
        "data": data
    })

@app.route('/api/records', methods=['GET'])
def get_records():
    # This would ideally list files in the 'records/' directory of the repo
    # For now, we'll return an empty list or implement a basic fetch
    if not GITHUB_TOKEN:
        return jsonify([])
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/records"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        files = res.json()
        return jsonify([f['name'] for f in files if f['name'].endswith('.json')])
    return jsonify([])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
