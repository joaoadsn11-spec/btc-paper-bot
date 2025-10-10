import time
import csv
from datetime import datetime, timezone, timedelta
from binance.spot import Spot

# ===============================
# CONFIGURATION
# ===============================
API_KEY = "YOUR_BINANCE_US_API_KEY"
API_SECRET = "YOUR_BINANCE_US_API_SECRET"
SYMBOL = "BTCUSDT"
CSV_FILE = "trade_log.csv"
TRADE_INTERVAL = 300  # 5 minutes
HEARTBEAT_INTERVAL = 900  # 15 minutes
SLEEP_START = (0, 0)  # Midnight NY time
SLEEP_END = (3, 55)   # 3:55 a.m. NY time (5 min before 4h close)

# ===============================
# INITIALIZATION
# ===============================
client = Spot(api_key=API_KEY, api_secret=API_SECRET, base_url="https://api.binance.us")
position = None
entry_price = None
stop_loss = None
take_profit = None
high_range = None
low_range = None
last_heartbeat = time.time()
balance = 10000.0  # paper trading balance

# ===============================
# HELPER FUNCTIONS
# ===============================
def log_trade(position, entry_price, stop_loss, take_profit, balance, pnl=None):
    now = datetime.now(timezone.utc).astimezone()
    with open(CSV_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([now.isoformat(), position, entry_price, stop_loss, take_profit, balance, pnl])
    print(f"[{now}] {position} | Entry: {entry_price} | SL: {stop_loss} | TP: {take_profit} | Balance: {balance} | PnL: {pnl}")

def get_first_4h_candle():
    """Return the high/low of the first fully closed 4h candle of the NY day."""
    now_ny = datetime.now(timezone(timedelta(hours=-4)))
    start_of_day = datetime(now_ny.year, now_ny.month, now_ny.day, tzinfo=timezone(timedelta(hours=-4)))
    candles = client.klines(SYMBOL, "4h", startTime=int(start_of_day.timestamp() * 1000), limit=2)
    if not candles:
        return None, None
    first_candle = candles[0]
    return float(first_candle[2]), float(first_candle[3])

def get_recent_5m_candles(n=3):
    """Return last n fully closed 5m candles."""
    candles = client.klines(SYMBOL, "5m", limit=n+1)
    return [
        {
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4])
        }
        for c in candles[:-1]
    ]

def ny_time_now():
    return datetime.now(timezone(timedelta(hours=-4)))

def in_sleep_window():
    now = ny_time_now()
    return SLEEP_START <= (now.hour, now.minute) < SLEEP_END

def heartbeat(balance, position):
    global last_heartbeat
    now = datetime.now(timezone.utc).astimezone()
    if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
        print(f"[HEARTBEAT] {now} | Balance: {balance} | Position: {position}")
        last_heartbeat = time.time()

# ===============================
# MAIN LOOP
# ===============================
while True:
    try:
        # Sleep window
        if in_sleep_window():
            now = ny_time_now()
            wake_time = datetime(now.year, now.month, now.day, SLEEP_END[0], SLEEP_END[1], tzinfo=timezone(timedelta(hours=-4)))
            wait_seconds = (wake_time - now).total_seconds()
            print(f"[INFO] Sleeping for {int(wait_seconds // 60)}m {int(wait_seconds % 60)}s until trading window...")
            time.sleep(wait_seconds)
            continue

        # Set range if not done
        if high_range is None or low_range is None:
            high_range, low_range = get_first_4h_candle()
            if high_range is None or low_range is None:
                time.sleep(TRADE_INTERVAL)
                continue
            print(f"[INFO] Range set: High={high_range}, Low={low_range}")

        # Get candles
        candles = get_recent_5m_candles(3)
        if len(candles) < 3:
            time.sleep(TRADE_INTERVAL)
            continue

        prev = candles[-2]  # candle before last closed
        curr = candles[-1]  # last closed (confirmation candle)

        # Check for entries with confirmation logic
        if position is None:
            # Short: previous candle closed above range, current closed back in below high_range
            if prev["close"] > high_range and curr["close"] < high_range:
                position = "SHORT"
                entry_price = curr["close"]
                stop_loss = high_range
                take_profit = entry_price - 2 * (stop_loss - entry_price)
                log_trade(position, entry_price, stop_loss, take_profit, balance)

            # Long: previous candle closed below range, current closed back in above low_range
            elif prev["close"] < low_range and curr["close"] > low_range:
                position = "LONG"
                entry_price = curr["close"]
                stop_loss = low_range
                take_profit = entry_price + 2 * (entry_price - stop_loss)
                log_trade(position, entry_price, stop_loss, take_profit, balance)

        # Manage open position
        elif position == "LONG":
            price = curr["close"]
            if price <= stop_loss or price >= take_profit:
                pnl = (price - entry_price)
                balance += pnl
                log_trade(f"EXIT LONG", entry_price, stop_loss, take_profit, balance, pnl)
                position = entry_price = stop_loss = take_profit = None

        elif position == "SHORT":
            price = curr["close"]
            if price >= stop_loss or price <= take_profit:
                pnl = (entry_price - price)
                balance += pnl
                log_trade(f"EXIT SHORT", entry_price, stop_loss, take_profit, balance, pnl)
                position = entry_price = stop_loss = take_profit = None

        # Heartbeat
        heartbeat(balance, position)
        time.sleep(TRADE_INTERVAL)

    except Exception as e:
        print("Error:", e)
        time.sleep(TRADE_INTERVAL)
