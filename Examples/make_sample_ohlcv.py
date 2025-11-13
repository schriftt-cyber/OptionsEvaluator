import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def make_sample(symbol, start_price):
    np.random.seed(hash(symbol) % (2**32))
    days = pd.bdate_range(datetime(2024, 2, 15), datetime(2025, 2, 14))
    prices = [start_price]
    for _ in range(1, len(days)):
        # small random walk ±2%
        change = np.random.normal(0, 0.01)
        prices.append(prices[-1] * (1 + change))
    prices = np.array(prices)

    df = pd.DataFrame({
        "Date": days,
        "Open": prices * (1 + np.random.normal(0, 0.002, len(prices))),
        "High": prices * (1 + np.random.uniform(0.005, 0.02, len(prices))),
        "Low":  prices * (1 - np.random.uniform(0.005, 0.02, len(prices))),
        "Close": prices,
        "Adj Close": prices,
        "Volume": np.random.randint(25_000_000, 60_000_000, len(prices)),
        "Ticker": symbol
    })
    return df

# Generate three tickers
tickers = {
    "NVDA": 120.0,
    "AAPL": 180.0,
    "MSFT": 400.0
}

frames = [make_sample(sym, price) for sym, price in tickers.items()]
df_all = pd.concat(frames).sort_values(["Ticker", "Date"])
df_all.to_csv("sample_ohlcv.csv", index=False)
print("✅ sample_ohlcv.csv created with", len(df_all), "rows.")
