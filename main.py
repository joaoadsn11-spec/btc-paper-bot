import time
import pytz
import csv
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from binance.spot import Spot
from dotenv import load_dotenv
import numpy as np

# ============ LOAD .ENV ============
load_dotenv()
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# ============ CONFIG ============
SYMBOL = "BTCUSDT"
UPDATE_INTERVAL = 60  # seconds
HEARTBEAT_INTERVAL = 300
NY_TZ = pytz.timezone("America/New_York")
START_BALANCE = 10000
RISK_PERCENT = 0.01
MAX_RISK_PER_TRADE = 10
ATR_PERIOD = 14
EMA_PERIOD_5M = 50
EMA_PERIOD_15M = 50

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# ============ LOGGING SETUP ============
log_file = os.path.join(LOGS_DIR, "bot.log")
logger = logging.getLogger("TradeBot")
logger.setLevel(logging.INFO)

# Rotating log file (5MB max, keep 5 files)
file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(console_handler)

# ============ CONNECT TO BINANCE US ============
client = Spot(api_key=API_KEY, api_secret=API_SECRET, base_url="https://api.binance.us")

# ============ STATE MANAGEMENT ============
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"balance": START_BALANCE, "trades_count": 0, "wins": 0, "losses": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ============ CSV LOG SETUP ============
def get_csv_file():
    today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
    return os.path.join(LOGS_DIR, f"trade_log_{today}.csv")

def init_csv():
    csv_file = get_csv_file()
    if not os.path.exists(csv_file):
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["LogTime", "Action", "Price", "StopLoss", "TakeProfit", "PnL", "Balance"])
    return csv_file

def log_trade(action, price, stop_loss, take_profit, pnl="N/A", balance="N/A"):
    csv_file = init_csv()
    with open(csv_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                         action, price, stop_loss, take_profit, pnl, balance])
    logger.info(f"TRADE LOGGED: {action} | Price={price:.2f} | SL={stop_loss:.2f} | TP={take_profit:.2f} | PnL={pnl} | Bal={balance}")

# ============ HELPER FUNCTIONS ============
def get_first_4h_range(symbol=SYMBOL):
    while True:
        now_ny = datetime.now(NY_TZ)
        if now_ny.hour < 4:
            wait_seconds = (4 - now_ny.hour)*3600 - now_ny.minute*60 - now_ny.second
            logger.info(f"Waiting {wait_seconds//60}m {wait_seconds%60}s for 4H candle...")
            time.sleep(min(wait_seconds, 60))
            continue
        try:
            klines = client.klines(symbol=symbol, interval="4h", limit=2)
        except Exception as e:
            logger.error(f"API error fetching 4H candle: {e}")
            time.sleep(30)
            continue
        first_candle = None
        for kline in klines:
            close_time = int(kline[6])
            close_dt = datetime.fromtimestamp(close_time/1000, NY_TZ)
            if close_dt.date() == now_ny.date():
                first_candle = kline
                break
        if not first_candle:
            logger.warning("First 4H candle not found. Retrying...")
            time.sleep(60)
            continue
        high = float(first_candle[2])
        low = float(first_candle[3])
        logger.info(f"First 4H Candle: High={high}, Low={low}")
        return high, low

def get_atr(symbol=SYMBOL, interval="5m", period=ATR_PERIOD):
    try:
        klines = client.klines(symbol=symbol, interval=interval, limit=period+1)
        trs = []
        for i in range(1, len(klines)):
            high = float(klines[i][2])
            low = float(klines[i][3])
            close_prev = float(klines[i-1][4])
            tr = max(high-low, abs(high-close_prev), abs(low-close_prev))
            trs.append(tr)
        return sum(trs)/len(trs) if trs else None
    except Exception as e:
        logger.error(f"Error fetching ATR: {e}")
        return None

def get_ema(symbol=SYMBOL, interval="5m", period=50):
    klines = client.klines(symbol=symbol, interval=interval, limit=period+1)
    closes = [float(k[4]) for k in klines]
    return np.mean(closes[-period:]) if len(closes) >= period else None

def get_avg_volume(symbol=SYMBOL, interval="5m", period=10):
    klines = client.klines(symbol=symbol, interval=interval, limit=period)
    volumes = [float(k[5]) for k in klines]
    return np.mean(volumes) if volumes else None

def print_dashboard(balance, active_trade, price, trades_count, wins, losses):
    win_rate = (wins/trades_count*100) if trades_count else 0
    logger.info(f"Price={price:.2f} | Balance={balance:.2f} | Trades={trades_count} | Wins={wins} | Losses={losses} | WinRate={win_rate:.1f}%")
    if active_trade:
        logger.info(f"Active Trade: {active_trade}")

# ============ MAIN BOT LOOP ============
def run_bot():
    state = load_state()
    balance = state["balance"]
    trades_count = state["trades_count"]
    wins = state["wins"]
    losses = state["losses"]

    active_trade = None
    last_heartbeat = time.time()
    error_delay = 10

    while True:
        try:
            now_ny = datetime.now(NY_TZ)

            # Trading window
            if now_ny.hour < 3 or (now_ny.hour == 3 and now_ny.minute < 55):
                wait_seconds = ((3 - now_ny.hour)*3600 + (55 - now_ny.minute)*60 - now_ny.second)
                logger.info(f"Waiting {wait_seconds//60}m {wait_seconds%60}s for trading window...")
                time.sleep(min(wait_seconds, 60))
                continue

            # Fetch data
            klines = client.klines(symbol=SYMBOL, interval="5m", limit=2)
            if len(klines) < 2:
                time.sleep(UPDATE_INTERVAL)
                continue

            last_candle = klines[-2]
            close_price = float(last_candle[4])
            atr = get_atr()
            if not atr:
                time.sleep(UPDATE_INTERVAL)
                continue

            ema_5m = get_ema(interval="5m", period=EMA_PERIOD_5M)
            ema_15m = get_ema(interval="15m", period=EMA_PERIOD_15M)
            avg_volume = get_avg_volume(period=10)
            candle_volume = float(last_candle[5])

            # First 4H range
            if 'high' not in locals() or 'low' not in locals():
                high, low = get_first_4h_range()

            # Entry logic
            if not active_trade:
                breakout_buffer = atr * 0.5
                if (close_price > high + breakout_buffer and close_price > ema_5m and close_price > ema_15m
                    and candle_volume > avg_volume):
                    stop_loss = close_price - atr
                    tp = close_price + 2*atr
                    risk_amount = min(RISK_PERCENT * balance, MAX_RISK_PER_TRADE)
                    quantity = risk_amount / (close_price - stop_loss)
                    active_trade = {"side":"BUY","entry":close_price,"sl":stop_loss,"tp":tp,"quantity":quantity,"trail":stop_loss}
                    log_trade("BUY", close_price, stop_loss, tp, balance=balance)
                    logger.info(f"BUY triggered at {close_price:.2f}")

                elif (close_price < low - breakout_buffer and close_price < ema_5m and close_price < ema_15m
                      and candle_volume > avg_volume):
                    stop_loss = close_price + atr
                    tp = close_price - 2*atr
                    risk_amount = min(RISK_PERCENT * balance, MAX_RISK_PER_TRADE)
                    quantity = risk_amount / (stop_loss - close_price)
                    active_trade = {"side":"SELL","entry":close_price,"sl":stop_loss,"tp":tp,"quantity":quantity,"trail":stop_loss}
                    log_trade("SELL", close_price, stop_loss, tp, balance=balance)
                    logger.info(f"SELL triggered at {close_price:.2f}")

            else:
                pnl = 0
                if active_trade["side"] == "BUY":
                    if close_price - active_trade["trail"] > atr:
                        active_trade["trail"] = close_price - atr
                        active_trade["sl"] = active_trade["trail"]

                    if close_price >= active_trade["tp"]:
                        pnl = (active_trade["tp"] - active_trade["entry"])*active_trade["quantity"]
                        balance += pnl; wins += 1; trades_count += 1
                        log_trade("BUY-TP", close_price, active_trade["sl"], active_trade["tp"], pnl, balance)
                        active_trade = None
                    elif close_price <= active_trade["sl"]:
                        pnl = (close_price - active_trade["entry"])*active_trade["quantity"]
                        balance += pnl; losses += 1; trades_count += 1
                        log_trade("BUY-SL", close_price, active_trade["sl"], active_trade["tp"], pnl, balance)
                        active_trade = None

                elif active_trade["side"] == "SELL":
                    if active_trade["trail"] - close_price > atr:
                        active_trade["trail"] = close_price + atr
                        active_trade["sl"] = active_trade["trail"]

                    if close_price <= active_trade["tp"]:
                        pnl = (active_trade["entry"] - active_trade["tp"])*active_trade["quantity"]
                        balance += pnl; wins += 1; trades_count += 1
                        log_trade("SELL-TP", close_price, active_trade["sl"], active_trade["tp"], pnl, balance)
                        active_trade = None
                    elif close_price >= active_trade["sl"]:
                        pnl = (active_trade["entry"] - close_price)*active_trade["quantity"]
                        balance += pnl; losses += 1; trades_count += 1
                        log_trade("SELL-SL", close_price, active_trade["sl"], active_trade["tp"], pnl, balance)
                        active_trade = None

            # Dashboard
            print_dashboard(balance, active_trade, close_price, trades_count, wins, losses)

            # Save state
            save_state({"balance": balance, "trades_count": trades_count, "wins": wins, "losses": losses})

            # Reset error delay
            error_delay = 10

            time.sleep(UPDATE_INTERVAL)

        except KeyboardInterrupt:
            logger.warning("Bot stopped manually.")
            save_state({"balance": balance, "trades_count": trades_count, "wins": wins, "losses": losses})
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}. Retrying in {error_delay}s")
            time.sleep(error_delay)
            error_delay = min(error_delay*2, 300)  # exponential backoff

# ============ RUN ============
if __name__ == "__main__":
    run_bot()
