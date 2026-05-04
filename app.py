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
MAX_FETCH_RETRIES = 3
BACKOFF_SECONDS = [0.8, 1.5, 2.5]
REQUEST_INTERVAL_SECONDS = 0.4
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

def get_stock_data(ticker, english_name=None, chinese_name=None):
    try:
        time.sleep(REQUEST_INTERVAL_SECONDS)
        stock = yf.Ticker(ticker)
        hist = None
        last_history_error = None
        for attempt in range(MAX_FETCH_RETRIES + 1):
            try:
                hist = stock.history(period="2mo", timeout=12)
                if not hist.empty:
                    break
            except Exception as e:
                last_history_error = f"{type(e).__name__}: {str(e)[:120]}"
            if attempt < MAX_FETCH_RETRIES:
                time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
        if hist is None or hist.empty:
            if last_history_error:
                return None, f"history_error_after_retries({last_history_error})"
            return None, "empty_history_after_retries"
        current_price = hist['Close'].iloc[-1]
        rsi = calculate_rsi(hist['Close'], window=14)
        
        pb = None
        name = english_name or ticker
        
        try:
            info = stock.info
            if info:
                pb = info.get('priceToBook')
                name = english_name or info.get('longName') or info.get('shortName') or ticker
        except:
            pass
            
        return {
            "ticker": ticker,
            "name": name,
            "english_name": english_name or name,
            "chinese_name": chinese_name,
            "pb": pb,
            "rsi": rsi,
            "price": current_price,
            "url": f"https://finance.yahoo.com/quote/{ticker}"
        }, None
    except Exception as e:
        return None, f"fetch_exception({type(e).__name__}: {str(e)[:120]})"

def screen_stocks(market='US'):
    stock_list = []
    preload_failed_tickers = []
    if market == 'HK':
        try:
            df = pd.read_excel('HKEX_stock_names_and_numbers_with_Chinese_names.xlsx')
            stock_number_col = 'Stock Number' if 'Stock Number' in df.columns else None
            if stock_number_col is None:
                raise ValueError("missing Stock Number column")
            for _, row in df.iterrows():
                raw_num = row.get(stock_number_col)
                if pd.isna(raw_num):
                    continue
                raw_num_str = str(raw_num).strip()
                if raw_num_str.endswith('.0'):
                    raw_num_str = raw_num_str[:-2]
                if not raw_num_str.isdigit():
                    preload_failed_tickers.append({"ticker": raw_num_str or "unknown", "reason": "invalid_stock_number"})
                    continue
                ticker = f"{int(raw_num_str):04d}.HK"
                chinese_name = str(row.get('中文名称', '')).strip() or None
                english_name = None
                stock_list.append((ticker, english_name, chinese_name))
        except Exception:
            stock_list = [("0700.HK", None, None)]
            preload_failed_tickers.append({"ticker": "HK_LIST", "reason": "hk_excel_read_failed"})
    else:
        try:
            df = pd.read_excel('SPY_500_holdings_names_numbers_with_Chinese_names.xlsx')
            ticker_col = next((c for c in ['Ticker', 'ticker', 'Symbol', 'symbol'] if c in df.columns), None)
            if ticker_col is None:
                raise ValueError("missing ticker column")
            valid_df = df.dropna(subset=[ticker_col])
            for _, row in valid_df.iterrows():
                ticker = str(row[ticker_col]).strip().replace('.', '-')
                if ticker.lower() == 'ticker': continue
                chinese_name = str(row.get('中文名称', '')).strip() or None
                english_name = None
                stock_list.append((ticker, english_name, chinese_name))
        except Exception:
            stock_list = [("AAPL", None, None)]
            preload_failed_tickers.append({"ticker": "US_LIST", "reason": "us_excel_read_failed"})
    
    results = []
    failed_tickers = preload_failed_tickers[:]
    worker_count = 1 if market == 'HK' else MAX_WORKERS
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_stock = {executor.submit(get_stock_data, t, en, cn): t for t, en, cn in stock_list}
        for future in as_completed(future_to_stock):
            ticker = future_to_stock[future]
            data, error = future.result()
            if data:
                results.append(data)
            else:
                failed_tickers.append({"ticker": ticker, "reason": error or "unknown"})
            
    sec1 = sorted([s for s in results if s['pb'] is not None and 0 < s['pb'] < 1], key=lambda x: x['pb'])[:30]
    sec2 = sorted([s for s in results if s['rsi'] is not None and s['rsi'] < 35], key=lambda x: x['rsi'])[:30]
    sec3 = sorted([s for s in results if s['rsi'] is not None and s['rsi'] > 65], key=lambda x: x['rsi'], reverse=True)[:30]
    
    return {
        "date": get_hk_time().strftime("%Y-%m-%d %H:%M"),
        "market": market,
        "total_tickers": len(stock_list),
        "success_count": len(results),
        "failed_count": len(failed_tickers),
        "failed_tickers_sample": failed_tickers[:30],
        "failed_tickers": failed_tickers,
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
