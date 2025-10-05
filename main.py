import time
import csv
from datetime import datetime, timezone, timedelta
from binance.spot import Spot

# =============================
# CONFIGURATION
# =============================
API_KEY = "YOUR_BINANCE_US_API_KEY"
API_SECRET = "YOUR_BINANCE_US_API_SECRET"
SYMBOL = "BTCUSDT"
TRADE_INTERVAL = 300  # 5 minutes
CSV_FILE = "trade_log.csv"

# Paper trading settings
balance = 10000.0
position = None
entry_price = None
stop_loss = None
take_profit = None
high_range = None
low_range = None
last_heartbeat = 0


# =============================
# INITIALIZE CLIENT
# =============================
client = Spot(api_key=API_KEY, api_secret=API_SECRET, base_url="https://api.binance.us")


# =============================
# HELPER FUNCTIONS
# =============================
def log_trade(position, entry_price, exit_price, pnl, balance):
    now = datetime.now(timezone.utc).astimezone()
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([now.isoformat(), position, entry_price, exit_price, round(pnl, 2), round(balance, 2)])
    print(f"[{now}] {position} | Entry: {entry_price} | Exit: {exit_price} | PnL: {pnl:.2f} | Balance: {balance:.2f}")


def get_first_4h_candle():
    """Gets the first fully closed 4-hour candle of the current day (New York time)."""
    now_ny = datetime.now(timezone(timedelta(hours=-4)))
    start_of_day = datetime(now_ny.year, now_ny.month, now_ny.day, tzinfo=timezone(timedelta(hours=-4)))
    candles = client.klines(SYMBOL, "4h", startTime=int(start_of_day.timestamp() * 1000), limit=1)
    if not candles:
        return None, None
    c = candles[0]
    return float(c[2]), float(c[3])  # high, low


def get_last_5m_candle():
    """Gets the last fully closed 5-minute candle."""
    candles = client.klines(SYMBOL, "5m", limit=2)
    if len(candles) < 2:
        return None, None, None
    c = candles[-2]
    return float(c[2]), float(c[3]), float(c[4])  # high, low, close


def print_heartbeat():
    """Prints a heartbeat every 15 minutes with bot status."""
    global last_heartbeat
    now = time.time()
    if now - last_heartbeat >= 900:  # 15 minutes
        last_heartbeat = now
        now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if position:
            print(f"[{now_str}] 💓 Heartbeat: Bot active | Balance: ${balance:.2f} | Position: {position} "
                  f"(Entry: {entry_price}, TP: {take_profit}, SL: {stop_loss})")
        else:
            print(f"[{now_str}] 💓 Heartbeat: Bot active | Balance: ${balance:.2f} | Position: None")


# =============================
# MAIN LOOP
# =============================
print("🚀 Bot started successfully!")

while True:
    try:
        # New York time
        now_ny = datetime.now(timezone(timedelta(hours=-4)))

        # Sleep between midnight and 3:55 AM NY time
        if now_ny.hour == 0 and now_ny.minute < 55:
            print("⏸️ Sleeping until 03:55 AM NY time...")
            time.sleep(3 * 3600 + 55 * 60)
            continue

        # Set range if not yet defined
        if high_range is None or low_range is None:
            high_range, low_range = get_first_4h_candle()
            if high_range is None or low_range is None:
                time.sleep(TRADE_INTERVAL)
                continue
            print(f"📊 New 4H Range Set | High: {high_range} | Low: {low_range}")

        # Get latest 5m candle
        high, low, close = get_last_5m_candle()
        if high is None or low is None or close is None:
            time.sleep(TRADE_INTERVAL)
            continue

        print_heartbeat()

        # Entry logic
        if position is None:
            # SHORT: candle closed above range then back in
            if close < high_range and high > high_range:
                position = "SHORT"
                entry_price = close
                stop_loss = high_range
                take_profit = entry_price - 2 * (stop_loss - entry_price)
                print(f"🔻 Entering SHORT at {entry_price}")
                log_trade("ENTRY_SHORT", entry_price, "", 0, balance)

            # LONG: candle closed below range then back in
            elif close > low_range and low < low_range:
                position = "LONG"
                entry_price = close
                stop_loss = low_range
                take_profit = entry_price + 2 * (entry_price - stop_loss)
                print(f"🔼 Entering LONG at {entry_price}")
                log_trade("ENTRY_LONG", entry_price, "", 0, balance)

        # Exit logic
        elif position == "LONG":
            if close <= stop_loss or close >= take_profit:
                pnl = close - entry_price
                balance += pnl
                log_trade("EXIT_LONG", entry_price, close, pnl, balance)
                position = None

        elif position == "SHORT":
            if close >= stop_loss or close <= take_profit:
                pnl = entry_price - close
                balance += pnl
                log_trade("EXIT_SHORT", entry_price, close, pnl, balance)
                position = None

        time.sleep(TRADE_INTERVAL)

    except Exception as e:
        print("❌ Error:", e)
        time.sleep(TRADE_INTERVAL)
