import ccxt
import pandas as pd
import numpy as np
import requests
import time
import threading
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# =============================================================================
# CONFIGURATION
# =============================================================================
BOT_TOKEN = "8261010818:AAEF5vFx2VDe82W1hykxkco2MfbLHqVrVZs"
CHAT_ID = "6842512113"

COINS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT", "LTC/USDT",
    "OP/USDT", "ARB/USDT", "INJ/USDT", "LINK/USDT", "UNI/USDT",
    "AAVE/USDT", "SUI/USDT", "SEI/USDT", "DOGE/USDT", "PEPE/USDT",
    "ATOM/USDT", "NEAR/USDT", "FIL/USDT", "ICP/USDT", "APT/USDT",
    "FTM/USDT", "RUNE/USDT", "GALA/USDT", "SAND/USDT", "MANA/USDT",
    "TRX/USDT", "EOS/USDT", "ALGO/USDT", "XTZ/USDT", "KAVA/USDT"
]

SCAN_INTERVAL = 60
COOLDOWN_MINUTES = 15
PORT = int(os.environ.get("PORT", 8000))

# =============================================================================
# STATE TRACKING
# =============================================================================
coin_states = {}
last_alert_time = {}
scan_count = 0
last_scan_time = "Not started"

# =============================================================================
# SIMPLE WEB SERVER FOR KOYEB
# =============================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        status = "Yellamma Scanner Running | Scans: " + str(scan_count) + " | Last: " + last_scan_time
        self.wfile.write(status.encode())
    
    def log_message(self, format, *args):
        pass

def start_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print("Web server started on port " + str(PORT))
    server.serve_forever()

# =============================================================================
# TELEGRAM FUNCTION
# =============================================================================
def send_telegram_message(message):
    try:
        telegram_url = "https://api.telegram.org/bot" + 8261010818:AAEF5vFx2VDe82W1hykxkco2MfbLHqVrVZs + "/sendMessage"
        payload = {
            "chat_id": 6842512113,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(telegram_url, json=payload, timeout=30)
        if response.status_code == 200:
            return True
        else:
            print("Telegram error: " + str(response.status_code))
            return False
    except Exception as e:
        print("Telegram exception: " + str(e))
        return False

# =============================================================================
# DATA FETCHING
# =============================================================================
def fetch_ohlcv(exchange, symbol, timeframe, limit=250):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.iloc[:-1].reset_index(drop=True)
        return df
    except Exception as e:
        print("Fetch error " + symbol + ": " + str(e))
        return None

# =============================================================================
# INDICATORS
# =============================================================================
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    avg_loss = avg_loss.replace(0, 0.0001)
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def calculate_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr

# =============================================================================
# FILTERS
# =============================================================================
def check_trend_filter(df_5m, df_15m):
    ema50_5m = calculate_ema(df_5m["close"], 50)
    ema200_5m = calculate_ema(df_5m["close"], 200)
    close_5m = df_5m["close"].iloc[-1]
    ema50_val_5m = ema50_5m.iloc[-1]
    ema200_val_5m = ema200_5m.iloc[-1]

    ema50_15m = calculate_ema(df_15m["close"], 50)
    close_15m = df_15m["close"].iloc[-1]
    ema50_val_15m = ema50_15m.iloc[-1]

    if close_5m > ema50_val_5m and ema50_val_5m > ema200_val_5m and close_15m > ema50_val_15m:
        return "BULLISH"

    if close_5m < ema50_val_5m and ema50_val_5m < ema200_val_5m and close_15m < ema50_val_15m:
        return "BEARISH"

    return None

def check_momentum_filter(df_5m, trend):
    rsi = calculate_rsi(df_5m["close"], 14)
    current_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]

    if trend == "BULLISH":
        return current_rsi > 50 and current_rsi > prev_rsi
    elif trend == "BEARISH":
        return current_rsi < 50 and current_rsi < prev_rsi
    return False

def check_volatility_filter(df_5m):
    atr = calculate_atr(df_5m, 14)
    atr_ma = atr.rolling(window=20).mean()
    current_atr = atr.iloc[-1]
    current_atr_ma = atr_ma.iloc[-1]

    if pd.isna(current_atr) or pd.isna(current_atr_ma):
        return False
    return current_atr > current_atr_ma

def check_volume_filter(df_5m):
    volume = df_5m["volume"]
    volume_ma = volume.rolling(window=20).mean()
    current_volume = volume.iloc[-1]
    current_volume_ma = volume_ma.iloc[-1]

    if pd.isna(current_volume) or pd.isna(current_volume_ma):
        return False
    return current_volume > current_volume_ma

# =============================================================================
# ANALYSIS
# =============================================================================
def analyze_coin(exchange, symbol):
    try:
        df_5m = fetch_ohlcv(exchange, symbol, "5m", 250)
        df_15m = fetch_ohlcv(exchange, symbol, "15m", 100)

        if df_5m is None or df_15m is None:
            return None, None

        if len(df_5m) < 220 or len(df_15m) < 60:
            return None, None

        trend = check_trend_filter(df_5m, df_15m)
        if trend is None:
            return False, None

        if not check_momentum_filter(df_5m, trend):
            return False, None

        if not check_volatility_filter(df_5m):
            return False, None

        if not check_volume_filter(df_5m):
            return False, None

        return True, trend

    except Exception as e:
        print("Analysis error " + symbol + ": " + str(e))
        return None, None

# =============================================================================
# COOLDOWN
# =============================================================================
def can_send_alert(symbol):
    if symbol not in last_alert_time:
        return True
    elapsed = time.time() - last_alert_time[symbol]
    cooldown_seconds = COOLDOWN_MINUTES * 60
    return elapsed >= cooldown_seconds

# =============================================================================
# MESSAGE FORMAT
# =============================================================================
def format_alert_message(symbol, bias):
    if bias == "BULLISH":
        emoji = "🟢"
        direction = "LONG"
    else:
        emoji = "🔴"
        direction = "SHORT"

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    coin_name = symbol.replace("/USDT", "")

    msg = emoji + " <b>SIGNAL: " + coin_name + "</b> " + emoji + "\n"
    msg = msg + "━━━━━━━━━━━━━━━━━━━━\n"
    msg = msg + "📊 <b>Pair:</b> " + symbol + "\n"
    msg = msg + "📈 <b>Bias:</b> " + bias + "\n"
    msg = msg + "🎯 <b>Direction:</b> " + direction + "\n"
    msg = msg + "⏱ <b>Timeframe:</b> 5M Scalping\n"
    msg = msg + "━━━━━━━━━━━━━━━━━━━━\n"
    msg = msg + "✅ <b>Filters Passed:</b>\n"
    msg = msg + "   • Trend (EMA 50/200)\n"
    msg = msg + "   • Momentum (RSI 14)\n"
    msg = msg + "   • Volatility (ATR 14)\n"
    msg = msg + "   • Volume (MA 20)\n"
    msg = msg + "━━━━━━━━━━━━━━━━━━━━\n"
    msg = msg + "🕐 " + timestamp
    return msg

# =============================================================================
# SCANNER LOOP
# =============================================================================
def run_scanner():
    global scan_count, last_scan_time

    print("=" * 60)
    print("YELLAMMA SCANNER - STARTING")
    print("=" * 60)

    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"}
    })

    print("Exchange: Binance")
    print("Coins: " + str(len(COINS)))
    print("Interval: " + str(SCAN_INTERVAL) + "s")
    print("=" * 60)

    startup_msg = "🤖 Yellamma Scanner Started\nScalping | 5M | Binance (ccxt)"
    send_telegram_message(startup_msg)
    print("Startup message sent")

    for coin in COINS:
        coin_states[coin] = False

    print("Scanner running...")
    print("=" * 60)

    while True:
        try:
            scan_start = time.time()
            current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            last_scan_time = current_time
            print("\n[SCAN] " + current_time)

            signals_found = 0

            for symbol in COINS:
                try:
                    is_valid, bias = analyze_coin(exchange, symbol)

                    if is_valid is None:
                        continue

                    prev_state = coin_states.get(symbol, False)

                    if is_valid and not prev_state:
                        if can_send_alert(symbol):
                            alert_msg = format_alert_message(symbol, bias)
                            if send_telegram_message(alert_msg):
                                last_alert_time[symbol] = time.time()
                                signals_found = signals_found + 1
                                print("  ALERT: " + symbol + " [" + bias + "]")

                    coin_states[symbol] = is_valid
                    time.sleep(0.3)

                except Exception as e:
                    print("  Error: " + symbol + " - " + str(e))
                    time.sleep(1)
                    continue

            scan_count = scan_count + 1
            scan_end = time.time()
            scan_duration = round(scan_end - scan_start, 2)
            print("[DONE] " + str(len(COINS)) + " coins | " + str(scan_duration) + "s | Signals: " + str(signals_found))

            sleep_time = max(SCAN_INTERVAL - scan_duration, 5)
            print("[WAIT] " + str(int(sleep_time)) + "s")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\nStopped")
            break
        except Exception as e:
            print("[ERROR] " + str(e))
            time.sleep(30)

# =============================================================================
# MAIN
# =============================================================================
def main():
    # Start scanner in background thread
    scanner_thread = threading.Thread(target=run_scanner, daemon=True)
    scanner_thread.start()
    
    # Start web server (keeps Koyeb happy)
    start_web_server()

if __name__ == "__main__":
    main()
