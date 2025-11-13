from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
from .base import Indicator
from .utils import ema


@dataclass
class MACDIndicator(Indicator):
    fast: int = 12
    slow: int = 26
    signal_len: int = 9
    name: str = field(init=False, default='macd')
    params: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        if self.fast >= self.slow:
            raise ValueError("fast must be < slow for MACD")
        self.params = {"fast": self.fast, "slow": self.slow, "signal": self.signal_len}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        ema_fast = ema(df['close'], self.fast)
        ema_slow = ema(df['close'], self.slow)
        macd = ema_fast - ema_slow
        sig = macd.ewm(span=self.signal_len, adjust=False, min_periods=self.signal_len).mean()
        hist = macd - sig
        cross_up = (macd > sig) & (macd.shift(1) <= sig.shift(1))
        cross_dn = (macd < sig) & (macd.shift(1) >= sig.shift(1))
        signal = pd.Series(0, index=df.index)
        signal = signal.mask(cross_up, 1).mask(cross_dn, -1).ffill().fillna(0).astype(int)
        return pd.DataFrame({"value": hist, "signal": signal, "macd": macd, "signal_line": sig})
