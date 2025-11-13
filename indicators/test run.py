# test_run.py
import pandas as pd
from indicators import (
    SMACrossover, RSIIndicator, MACDIndicator, BollingerBands,
    VolumeSpike, ATRBreakout, GapMove, IndicatorRunner
)

# --- 1. Load your CSV file ---
# ⚠️ Update the path below to where your sample_ohlcv.csv is saved
#csv_path = "sample_ohlcv.csv"  # or an absolute path like r"C:\\Users\\YourName\\Downloads\\sample_ohlcv.csv"
csv_path = r"C:\Users\Schri\Desktop\sample_ohlcv.csv"

# Read the CSV and set date as index
df = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date").sort_index()

# --- 2. Define your indicators ---
runner = IndicatorRunner([
    SMACrossover(short=10, long=50),
    RSIIndicator(length=14),
    MACDIndicator(),
    BollingerBands(length=20, stdev=2.0),
    VolumeSpike(lookback=20, threshold=2.0),
    ATRBreakout(length=14, multiple=1.5),
    GapMove(percent=2.0),
])

# --- 3. Run the indicators ---
signals = runner.run(df)

# --- 4. Inspect results ---
print(signals.tail(10))        # view last few rows
signals.to_csv("signals.csv")  # export to CSV
print("\\nSaved output as signals.csv")
