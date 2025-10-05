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

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def log_trade(position, entry_price, stop_loss, take_profit):
    now = datetime.now(timezone.utc).astimezone()
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([now.isoformat(), position, entry_price, stop_loss, take_profit])
    print(f"[{now}] {position} | Entry: {entry_price} | SL: {stop_loss} | TP: {take_profit}")

def get_first_4h_candle():
    """Get the first fully closed 4-hour candle of the day (New York time)."""
    now = datetime.now(timezone(timedelta(hours=-4)))  # New York time
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone(timedelta(hours=-4)))
    candles = client.klines(SYMBOL, "4h", startTime=int(start_of_day.timestamp()*1000), limit=1)
    if not candles:
        return None, None
    first_candle = candles[0]
    high = float(first_candle[2])
    low = float(first_candle[3])
    return high, low

def get_last_5m_candle():
    """Get the last fully closed 5-minute candle."""
    candles = client.klines(SYMBOL, "5m", limit=2)
    if len(candles) < 2:
        return None, None, None
    last_closed = candles[-2]
    high = float(last_closed[2])
    low = float(last_closed[3])
    close = float(last_closed[4])
    return high, low, close

# -----------------------------
# MAIN LOOP
# -----------------------------
while True:
    try:
        # Set range if not set
        if high_range is None or low_range is None:
            high_range, low_range = get_first_4h_candle()
            if high_range is None or low_range is None:
                time.sleep(TRADE_INTERVAL)
                continue

        # Get last 5m candle
        high, low, close = get_last_5m_candle()

        # Skip if data not ready
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
                log_trade(position, entry_price, stop_loss, take_profit)

            # LONG: Candle closed below range then back in
            elif close > low_range and low < low_range:
                position = "LONG"
                entry_price = close
                stop_loss = low_range
                take_profit = entry_price + 2 * (entry_price - stop_loss)
                log_trade(position, entry_price, stop_loss, take_profit)

        # Check for exits
        if position is not None:
            if position == "LONG":
                if close <= stop_loss or close >= take_profit:
                    print(f"Exiting LONG at {close}")
                    position = None
                    entry_price = None
                    stop_loss = None
                    take_profit = None
            elif position == "SHORT":
                if close >= stop_loss or close <= take_profit:
                    print(f"Exiting SHORT at {close}")
                    position = None
                    entry_price = None
                    stop_loss = None
                    take_profit = None

        time.sleep(TRADE_INTERVAL)

    except Exception as e:
        print("Error:", e)
        time.sleep(TRADE_INTERVAL)
