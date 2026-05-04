import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import json
import os
import time
import requests
from flask import Flask, request, jsonify, render_template
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz

app = Flask(__name__)

# Local storage configuration
RECORDS_DIR = "records"
if not os.path.exists(RECORDS_DIR):
    os.makedirs(RECORDS_DIR)

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

def get_chinese_name(ticker):
    """Try to get Chinese name from various sources"""
    try:
        # For HK stocks, we can use a simple mapping or a specific query
        if ticker.endswith('.HK'):
            symbol = ticker.split('.')[0].lstrip('0')
            # Try to get from a public API or known source if possible
            # For now, we'll use yfinance info but try to force a locale if supported
            pass
            
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # Some stocks have 'longName' in Chinese if the locale is set or available
        # But yfinance is mostly English. Let's try to find Chinese in common fields.
        name = info.get('longName') or info.get('shortName') or ticker
        
        # If it's a major stock, we can provide a manual override for better UX
        overrides = {
            "0700.HK": "腾讯控股",
            "9988.HK": "阿里巴巴-W",
            "0005.HK": "汇丰控股",
            "1299.HK": "友邦保险",
            "3690.HK": "美团-W",
            "1810.HK": "小米集团-W",
            "9618.HK": "京东集团-SW",
            "9999.HK": "网易-S",
            "2318.HK": "中国平安",
            "0939.HK": "建设银行",
            "1398.HK": "工商银行",
            "3988.HK": "中国银行",
            "AAPL": "苹果公司",
            "TSLA": "特斯拉",
            "NVDA": "英伟达",
            "MSFT": "微软",
            "GOOGL": "谷歌-A",
            "AMZN": "亚马逊",
            "META": "脸书 (Meta)",
            "BABA": "阿里巴巴 (美股)",
            "PDD": "拼多多",
            "JD": "京东 (美股)"
        }
        return overrides.get(ticker, name)
    except:
        return ticker

def get_stock_data(ticker, display_name=None):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2mo")
        if hist.empty:
            return None
        current_price = hist['Close'].iloc[-1]
        rsi = calculate_rsi(hist['Close'], window=14)
        
        pb = None
        name = display_name or ticker
        
        try:
            info = stock.info
            if info:
                pb = info.get('priceToBook')
                # Try to get Chinese name
                name = get_chinese_name(ticker)
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
    with ThreadPoolExecutor(max_workers=5) as executor:
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
    market = request.json.get('market', 'US')
    data = screen_stocks(market)
    filename = f"{get_hk_time().strftime('%Y%m%d_%H%M%S')}_{market}.json"
    with open(os.path.join(RECORDS_DIR, filename), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    return jsonify({"success": True, "data": data})

@app.route('/api/records', methods=['GET'])
def get_records():
    files = sorted([f for f in os.listdir(RECORDS_DIR) if f.endswith('.json')], reverse=True)
    return jsonify(files)

@app.route('/api/records/<filename>', methods=['GET'])
def get_record_detail(filename):
    with open(os.path.join(RECORDS_DIR, filename), 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
