import time
import csv
from datetime import datetime, timezone, timedelta
from binance.spot import Spot

# -----------------------------
# CONFIGURATION
# -----------------------------
API_KEY = "YOUR_BINANCE_US_API_KEY"
API_SECRET = "YOUR_BINANCE_US_API_SECRET"
SYMBOL = "BTCUSDT"  # Change as needed
TRADE_INTERVAL = 300  # 5 minutes in seconds
HEARTBEAT_INTERVAL = 900  # 15 minutes in seconds
CSV_FILE = "trade_log.csv"

# -----------------------------
# INITIALIZE CLIENT
# -----------------------------
client = Spot(api_key=API_KEY, api_secret=API_SECRET, base_url="https://api.binance.us")

# -----------------------------
# PAPER TRADING STATE
# -----------------------------
position = None  # "LONG" or "SHORT"
entry_price = None
stop_loss = None
take_profit = None
high_range = None
low_range = None
balance = 10000.0  # Starting paper balance
last_heartbeat = time.time() - HEARTBEAT_INTERVAL

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def log_trade(timestamp, position, entry, sl, tp, balance, pnl=None):
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([timestamp.isoformat(), position, entry, sl, tp, balance, pnl])
    print(f"[{timestamp}] {position} | Entry: {entry} | SL: {sl} | TP: {tp} | Balance: {balance} | PnL: {pnl}")

def get_first_4h_candle():
    now = datetime.now(timezone(timedelta(hours=-4)))  # New York time
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone(timedelta(hours=-4)))
    candles = client.klines(SYMBOL, "4h", startTime=int(start_of_day.timestamp()*1000), limit=1)
    if not candles:
        return None, None
    first_candle = candles[0]
    return float(first_candle[2]), float(first_candle[3])  # high, low

def get_last_5m_candle():
    candles = client.klines(SYMBOL, "5m", limit=2)
    if len(candles) < 2:
        return None, None, None
    last_closed = candles[-2]
    return float(last_closed[2]), float(last_closed[3]), float(last_closed[4])  # high, low, close

def in_sleep_window():
    now = datetime.now(timezone(timedelta(hours=-4)))  # New York time
    # Sleep from 00:00 to 03:55
    if now.hour == 0 or (now.hour == 3 and now.minute < 55):
        return True
    return False

# -----------------------------
# MAIN LOOP
# -----------------------------
while True:
    try:
        # Sleep/wake logic
        if in_sleep_window():
            wait_seconds = 300  # check every 5 minutes
            print(f"[INFO] Waiting {wait_seconds} seconds for trading window...")
            time.sleep(wait_seconds)
            continue

        # Heartbeat logging
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
            now = datetime.now(timezone.utc).astimezone()
            print(f"[HEARTBEAT] {now} | Balance: {balance} | Position: {position}")
            last_heartbeat = time.time()

        # Set range if not set
        if high_range is None or low_range is None:
            high_range, low_range = get_first_4h_candle()
            if high_range is None or low_range is None:
                time.sleep(TRADE_INTERVAL)
                continue

        # Get last 5m candle
        high, low, close = get_last_5m_candle()
        if high is None or low is None or close is None:
            time.sleep(TRADE_INTERVAL)
            continue

        # Check for entries
        if position is None:
            # SHORT: Candle closed above range then back in
            if close < high_range and high > high_range:
                position = "SHORT"
                entry_price = close
                stop_loss = high_range
                take_profit = entry_price - 2 * (stop_loss - entry_price)
                log_trade(datetime.now(timezone.utc).astimezone(), position, entry_price, stop_loss, take_profit, balance)

            # LONG: Candle closed below range then back in
            elif close > low_range and low < low_range:
                position = "LONG"
                entry_price = close
                stop_loss = low_range
                take_profit = entry_price + 2 * (entry_price - stop_loss)
                log_trade(datetime.now(timezone.utc).astimezone(), position, entry_price, stop_loss, take_profit, balance)

        # Check for exits
        if position is not None:
            pnl = None
            if position == "LONG":
                if close <= stop_loss or close >= take_profit:
                    pnl = (close - entry_price) * (balance / entry_price)
                    balance += pnl
                    log_trade(datetime.now(timezone.utc).astimezone(), f"EXIT {position}", entry_price, stop_loss, take_profit, balance, pnl)
                    position = None
                    entry_price = None
                    stop_loss = None
                    take_profit = None
            elif position == "SHORT":
                if close >= stop_loss or close <= take_profit:
                    pnl = (entry_price - close) * (balance / entry_price)
                    balance += pnl
                    log_trade(datetime.now(timezone.utc).astimezone(), f"EXIT {position}", entry_price, stop_loss, take_profit, balance, pnl)
                    position = None
                    entry_price = None
                    stop_loss = None
                    take_profit = None

        time.sleep(TRADE_INTERVAL)

    except Exception as e:
        print("Error:", e)
        time.sleep(TRADE_INTERVAL)
