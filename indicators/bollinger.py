from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import numpy as np
import pandas as pd
from .base import Indicator
from .utils import sma


@dataclass
class BollingerBands(Indicator):
    length: int = 20
    stdev: float = 2.0
    name: str = field(init=False, default='bollinger')
    params: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        self.params = {"length": self.length, "stdev": self.stdev}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        m = sma(df['close'], self.length)
        sd = df['close'].rolling(self.length, min_periods=self.length).std()
        upper = m + self.stdev * sd
        lower = m - self.stdev * sd
        value = (df['close'] - m) / (sd.replace(0, np.nan))
        signal = pd.Series(0, index=df.index)
        signal = signal.mask(df['close'] < lower, 1).mask(df['close'] > upper, -1)
        return pd.DataFrame({"value": value, "signal": signal.fillna(0).astype(int), "mid": m, "upper": upper, "lower": lower})
