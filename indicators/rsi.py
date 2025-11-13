from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import numpy as np
import pandas as pd
from .base import Indicator


@dataclass
class RSIIndicator(Indicator):
    length: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    name: str = field(init=False, default='rsi')
    params: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        self.params = {"length": self.length, "oversold": self.oversold, "overbought": self.overbought}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df['close']
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/self.length, adjust=False, min_periods=self.length).mean()
        avg_loss = loss.ewm(alpha=1/self.length, adjust=False, min_periods=self.length).mean()
        rs = avg_gain / (avg_loss.replace(0, np.nan))
        rsi = 100 - (100 / (1 + rs))
        signal = pd.Series(0, index=df.index)
        signal = signal.mask(rsi < self.oversold, 1).mask(rsi > self.overbought, -1)
        return pd.DataFrame({"value": rsi, "signal": signal.fillna(0).astype(int)})
