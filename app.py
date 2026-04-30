import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import json
import os
import time
from flask import Flask, request, jsonify, render_template
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# Local storage configuration
RECORDS_DIR = "records"
if not os.path.exists(RECORDS_DIR):
    os.makedirs(RECORDS_DIR)

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
        stock = yf.Ticker(ticker)
        # Use a faster way to get basic info
        info = stock.info
        if not info:
            return None
            
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        pb = info.get('priceToBook')
        name = info.get('shortName') or info.get('longName') or ticker
        
        # We only need history if we want to check RSI
        # To speed up, we'll fetch 1mo history which is enough for 14d RSI
        hist = stock.history(period="1mo")
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
        # Silently fail for individual tickers to keep the loop going
        return None

def screen_stocks(market='US'):
    # Significantly expanded lists to cover more of the market
    if market == 'HK':
        # Top 200+ HK tickers (common ones)
        tickers = [f"{str(i).zfill(4)}.HK" for i in range(1, 200)] + \
                  ["0700.HK", "9988.HK", "3690.HK", "1299.HK", "0005.HK", "0939.HK", "1398.HK", "2318.HK", "3988.HK", "3968.HK",
                   "1810.HK", "1024.HK", "9618.HK", "9888.HK", "2015.HK", "2331.HK", "6618.HK", "9633.HK", "9961.HK", "9999.HK"]
    else: # US
        # S&P 500 + Nasdaq 100 subset (approx 300-400 tickers)
        # For a real "full market", we'd need a dynamic source, but this is a massive improvement
        tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK-B", "JPM", "V", "UNH", "MA", "PG", "HD", "DIS",
            "PYPL", "ADBE", "NFLX", "INTC", "CSCO", "PEP", "KO", "PFE", "XOM", "CVX", "ABT", "CRM", "BAC", "COST", "WMT",
            "TMO", "AVGO", "ORCL", "ACN", "LIN", "NKE", "DHR", "ABBV", "NEXT", "AMD", "TXN", "PM", "UPS", "NEE", "MS",
            "RTX", "HON", "LOW", "UNP", "BMY", "AMAT", "SBUX", "CAT", "GS", "GE", "DE", "INTU", "PLD", "AXP", "T",
            "VZ", "C", "MDLZ", "ISRG", "GILD", "BKNG", "TJX", "ADP", "MDT", "LMT", "SYK", "CI", "VRTX", "MMC", "REGN",
            "ADI", "ZTS", "BSX", "AMT", "CB", "BA", "MU", "LRCX", "PANW", "SNPS", "CDNS", "EQIX", "SCCO", "MO", "ETN",
            "ORLY", "SLB", "PGR", "SHW", "MPC", "VLO", "PSX", "COP", "EOG", "OXY", "HES", "DVN", "HAL", "BKR", "KMI",
            "WMB", "OKE", "TRGP", "FANG", "CTRA", "MRO", "APA", "EQT", "CHRD", "MTDR", "PDCE", "OVV", "SWN", "RRC",
            "AMCR", "AVY", "BALL", "BLL", "CC", "CE", "CF", "CTVA", "DOW", "DD", "EMN", "FMC", "IFF", "IP", "LIN",
            "LYB", "MLM", "MOS", "NEM", "NUE", "PKG", "PPG", "SEE", "SHW", "VMC", "WRK", "X", "A", "AAL", "AAPL", "ABBV",
            "ABT", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM",
            "ALB", "ALGN", "ALK", "ALL", "ALLE", "ALXN", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP", "AMT", "AMZN",
            "ANET", "ANSS", "ANTM", "AON", "AOS", "APA", "APD", "APH", "APTV", "ARE", "ATO", "ATVI", "AVB", "AVGO",
            "AVY", "AWK", "AXP", "AZO", "BA", "BAC", "BAX", "BBY", "BDX", "BEN", "BF.B", "BIIB", "BIO", "BK", "BKNG",
            "BKR", "BLK", "BLL", "BMY", "BR", "BRK.B", "BSX", "BWA", "BXP", "C", "CAG", "CAH", "CARR", "CAT", "CB",
            "CBOE", "CBRE", "CCI", "CCL", "CDNS", "CDW", "CE", "CERN", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI", "CINF",
            "CL", "CLX", "CMA", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC", "CNP", "COF", "COG", "COO", "COP", "COST",
            "CPB", "CPRT", "CRL", "CRM", "CSCO", "CSX", "CTAS", "CTLT", "CTSH", "CTVA", "CTXS", "CVS", "CVX", "CZR",
            "D", "DAL", "DD", "DE", "DFS", "DG", "DGX", "DHI", "DHR", "DIS", "DISCA", "DISCK", "DISH", "DLR", "DLTR",
            "DRE", "DRI", "DTE", "DUK", "DVA", "DVN", "DXC", "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EIX", "EL",
            "EMN", "EMR", "ENPH", "EOG", "EQIX", "EQR", "ES", "ESS", "ETN", "ETR", "ETSY", "EVRG", "EW", "EXC", "EXPD",
            "EXPE", "EXR", "F", "FANG", "FAST", "FB", "FBHS", "FCX", "FDX", "FE", "FFIV", "FIS", "FISV", "FITB", "FLT",
            "FMC", "FOX", "FOXA", "FRC", "FRT", "FTNT", "FTV", "GD", "GE", "GILD", "GIS", "GL", "GLW", "GM", "GNRC",
            "GOOG", "GOOGL", "GPC", "GPN", "GPS", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HES", "HIG",
            "HII", "HLT", "HOLX", "HON", "HPE", "HPQ", "HRL", "HSIC", "HST", "HSY", "HUM", "HWM", "IBM", "ICE", "IDXX",
            "IEX", "IFF", "ILMN", "INCY", "INFO", "INTC", "INTU", "IP", "IPG", "IQV", "IR", "IRM", "ISRG", "IT", "ITW",
            "IVZ", "J", "JBHT", "JCI", "JKHY", "JNJ", "JNPR", "JPM", "K", "KEY", "KEYS", "KHC", "KIM", "KLAC", "KMB",
            "KMI", "KMX", "KO", "KR", "KSU", "L", "LB", "LDOS", "LEG", "LEN", "LH", "LHX", "LIN", "LKQ", "LLY", "LMT",
            "LNC", "LNT", "LOW", "LRCX", "LUMN", "LUV", "LVS", "LW", "LYB", "LYV", "MA", "MAA", "MAR", "MAS", "MCD",
            "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MET", "MGM", "MHK", "MKC", "MKTX", "MLM", "MMC", "MMM", "MNST", "MO",
            "MOS", "MPC", "MPWR", "MRK", "MRO", "MS", "MSCI", "MSFT", "MSI", "MTB", "MTD", "MU", "MXIM", "MYL", "NCLH",
            "NDAQ", "NEE", "NEM", "NFLX", "NI", "NKE", "NLOK", "NLSN", "NOC", "NOV", "NRG", "NSC", "NTAP", "NTRS",
            "NUE", "NVDA", "NVR", "NWL", "NWS", "NWSA", "O", "ODFL", "OKE", "OMC", "ORCL", "ORLY", "OTIS", "OXY", "PAYC",
            "PAYX", "PBCT", "PCAR", "PEAK", "PEG", "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PKI", "PLD",
            "PM", "PNC", "PNR", "PNW", "POOL", "PPG", "PPL", "PRU", "PSA", "PSX", "PTC", "PVH", "PWR", "PXD", "PYPL",
            "QCOM", "QRVO", "RCL", "RE", "REG", "REGN", "RF", "RHI", "RJF", "RL", "RMD", "ROK", "ROL", "ROP", "ROST",
            "RSG", "RTX", "SBAC", "SBUX", "SCHW", "SEE", "SHW", "SIVB", "SJK", "SLB", "SLG", "SNA", "SNPS", "SO", "SPG",
            "SPGI", "SRE", "STE", "STT", "STX", "STZ", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG", "TDY",
            "TEL", "TER", "TFC", "TFX", "TGT", "TIF", "TJX", "TMO", "TMUS", "TPR", "TRMB", "TROW", "TRV", "TSCO", "TSLA",
            "TSN", "TT", "TTWO", "TWTR", "TXN", "TXT", "TYL", "UA", "UAA", "UAL", "UDR", "UHS", "ULTA", "UNH", "UNP",
            "UPS", "URI", "USB", "V", "VAR", "VFC", "VIAC", "VLO", "VMC", "VNO", "VRSK", "VRSN", "VRTX", "VTR", "VTRS",
            "VZ", "WAB", "WAT", "WBA", "WDC", "WEC", "WELL", "WFC", "WHR", "WLTW", "WM", "WMB", "WMT", "WRB", "WRK",
            "WST", "WU", "WY", "WYNN", "XEL", "XLNX", "XOM", "XRAY", "XYL", "YUM", "ZBH", "ZBRA", "ZION", "ZTS"
        ]
    
    # Remove duplicates
    tickers = list(set(tickers))
    
    results = []
    # Use more workers for larger list, but be careful of rate limits
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_ticker = {executor.submit(get_stock_data, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            try:
                data = future.result()
                if data:
                    results.append(data)
            except Exception:
                continue
            
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
    try:
        market = request.json.get('market', 'US')
        data = screen_stocks(market)
        success, filename = save_locally(data)
        return jsonify({
            "success": success,
            "data": data
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

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
