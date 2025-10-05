import time
import csv
from datetime import datetime, timezone, timedelta
from binance.spot import Spot

# -----------------------------
# CONFIGURATION
# -----------------------------
API_KEY = "YOUR_BINANCE_US_API_KEY"
API_SECRET = "YOUR_BINANCE_US_API_SECRET"
SYMBOL = "BTCUSDT"
TRADE_INTERVAL = 300  # 5 minutes in seconds
CSV_FILE = "trade_log.csv"
HEARTBEAT_INTERVAL = 900  # 15 minutes in seconds

# -----------------------------
# INITIALIZE CLIENT
# -----------------------------
client = Spot(api_key=API_KEY, api_secret=API_SECRET, base_url="https://api.binance.us")

# -----------------------------
# PAPER TRADING STATE
# -----------------------------
balance = 10000.0  # start paper balance
position = None  # "LONG" or "SHORT"
entry_price = None
stop_loss = None
take_profit = None
high_range = None
low_range = None
last_heartbeat = 0
current_trading_day = None  # track which NY day we're on

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def log_trade(position, entry_price, stop_loss, take_profit, pnl=None):
    now = datetime.now(timezone.utc).astimezone()
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([now.isoformat(), position, entry_price, stop_loss, take_profit, balance, pnl])
    print(f"[{now}] {position} | Entry: {entry_price} | SL: {stop_loss} | TP: {take_profit} | Balance: {balance} | PnL: {pnl}")

def get_first_4h_close_time():
    """Return datetime of first fully closed 4h candle of NY day."""
    now_ny = datetime.now(timezone(timedelta(hours=-4)))  # New York time
    start_of_day = datetime(now_ny.year, now_ny.month, now_ny.day, tzinfo=timezone(timedelta(hours=-4)))
    # First 4h candle closes at 4:00 NY time
    first_close = start_of_day + timedelta(hours=4)
    return first_close

def get_first_4h_candle():
    """Get the first fully closed 4-hour candle of the day (New York time)."""
    first_close = get_first_4h_close_time()
    candles = client.klines(SYMBOL, "4h", startTime=int((first_close - timedelta(hours=4)).timestamp()*1000), limit=1)
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
        now = datetime.now(timezone.utc).astimezone()
        ny_now = now.astimezone(timezone(timedelta(hours=-4)))
        today_ny = ny_now.date()

        # -----------------------------
        # DAILY RESET
        # -----------------------------
        if current_trading_day != today_ny:
            print(f"[RESET] New trading day detected: {today_ny}")
            # Clear range and positions
            high_range, low_range = None, None
            position, entry_price, stop_loss, take_profit = None, None, None, None
            current_trading_day = today_ny

        # -----------------------------
        # Sleep until 5 minutes before first 4h candle closes
        # -----------------------------
        first_close = get_first_4h_close_time()
        wake_time = first_close - timedelta(minutes=5)
        if ny_now < wake_time and high_range is None:
            wait_sec = (wake_time - ny_now).total_seconds()
            print(f"[INFO] Sleeping until {wake_time} NY time ({wait_sec/60:.1f} min)...")
            time.sleep(wait_sec)

        # -----------------------------
        # Set range if not already done
        # -----------------------------
        if high_range is None or low_range is None:
            high_range, low_range = get_first_4h_candle()
            if high_range and low_range:
                print(f"[INFO] Range set | High: {high_range} | Low: {low_range}")

        # -----------------------------
        # Get last 5m candle
        # -----------------------------
        high, low, close = get_last_5m_candle()
        if high is None or low is None or close is None:
            time.sleep(TRADE_INTERVAL)
            continue

        # -----------------------------
        # Entry Logic
        # -----------------------------
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

        # -----------------------------
        # Exit Logic
        # -----------------------------
        if position is not None:
            pnl = 0
            if position == "LONG":
                if close <= stop_loss or close >= take_profit:
                    pnl = close - entry_price
                    balance_change = pnl
                    balance += balance_change
                    print(f"[EXIT] LONG at {close} | PnL: {pnl} | Balance: {balance}")
                    log_trade("EXIT LONG", entry_price, stop_loss, take_profit, pnl)
                    position, entry_price, stop_loss, take_profit = None, None, None, None

            elif position == "SHORT":
                if close >= stop_loss or close <= take_profit:
                    pnl = entry_price - close
                    balance_change = pnl
                    balance += balance_change
                    print(f"[EXIT] SHORT at {close} | PnL: {pnl} | Balance: {balance}")
                    log_trade("EXIT SHORT", entry_price, stop_loss, take_profit, pnl)
                    position, entry_price, stop_loss, take_profit = None, None, None, None

        # -----------------------------
        # Heartbeat every 15 min
        # -----------------------------
        if (time.time() - last_heartbeat) >= HEARTBEAT_INTERVAL:
            print(f"[HEARTBEAT] {now} | Balance: {balance} | Position: {position}")
            last_heartbeat = time.time()

        time.sleep(TRADE_INTERVAL)

    except Exception as e:
        print("Error:", e)
        time.sleep(TRADE_INTERVAL)
