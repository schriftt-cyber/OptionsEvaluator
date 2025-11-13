from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from indicators import (
    SMACrossover, RSIIndicator, MACDIndicator, BollingerBands,
    VolumeSpike, ATRBreakout, GapMove, IndicatorRunner
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    rng = pd.date_range("2024-01-01", periods=120, freq="B")
    np.random.seed(7)
    close = pd.Series(np.cumsum(np.random.normal(0, 1, len(rng))) + 50, index=rng)
    high = close + np.random.uniform(0.1, 0.9, len(rng))
    low = close - np.random.uniform(0.1, 0.9, len(rng))
    open_ = close.shift(1).fillna(close) + np.random.uniform(-0.4, 0.4, len(rng))
    volume = pd.Series(np.random.lognormal(mean=12, sigma=0.5, size=len(rng)).astype(int), index=rng)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def _assert_common(df_in: pd.DataFrame, out: pd.DataFrame):
    assert isinstance(out, pd.DataFrame)
    assert "value" in out.columns
    assert "signal" in out.columns
    assert out.shape[0] == df_in.shape[0]
    # signals in {-1,0,1} or NaN then cast int should be fine
    assert set(np.unique(out["signal"].dropna().values)).issubset({-1, 0, 1})


def test_sma_crossover(sample_df):
    ind = SMACrossover(short=10, long=20)
    out = ind.compute(sample_df)
    _assert_common(sample_df, out)


def test_rsi(sample_df):
    ind = RSIIndicator(length=14)
    out = ind.compute(sample_df)
    _assert_common(sample_df, out)


def test_macd(sample_df):
    ind = MACDIndicator()
    out = ind.compute(sample_df)
    _assert_common(sample_df, out)
    for extra in ("macd", "signal_line"):
        assert extra in out.columns


def test_bollinger(sample_df):
    ind = BollingerBands(length=20, stdev=2)
    out = ind.compute(sample_df)
    _assert_common(sample_df, out)
    for band in ("mid", "upper", "lower"):
        assert band in out.columns


def test_volume_spike(sample_df):
    ind = VolumeSpike(lookback=10, threshold=1.5)
    out = ind.compute(sample_df)
    _assert_common(sample_df, out)


def test_atr_breakout(sample_df):
    ind = ATRBreakout(length=14, multiple=1.5)
    out = ind.compute(sample_df)
    _assert_common(sample_df, out)
    assert "atr" in out.columns


def test_gap_move(sample_df):
    ind = GapMove(percent=2.0)
    out = ind.compute(sample_df)
    _assert_common(sample_df, out)


def test_runner(sample_df):
    inds = [SMACrossover(10, 20), RSIIndicator(14), MACDIndicator(), BollingerBands(), VolumeSpike(), ATRBreakout(), GapMove()]
    wide = IndicatorRunner(inds).run(sample_df)
    # Expect columns to be namespaced by indicator name
    assert any(c.startswith("sma_crossover_") for c in wide.columns)
    assert any(c.startswith("rsi_") for c in wide.columns)
    assert wide.shape[0] == sample_df.shape[0]


def test_sma_crossover_param_guard():
    with pytest.raises(ValueError):
        SMACrossover(short=50, long=20)
