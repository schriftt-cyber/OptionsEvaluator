from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
from .base import Indicator
from .utils import sma


@dataclass
class SMACrossover(Indicator):
    short: int = 10
    long: int = 20
    name: str = field(init=False, default='sma_crossover')
    params: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        if self.short >= self.long:
            raise ValueError("short must be < long for SMACrossover")
        self.params = {"short": self.short, "long": self.long}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        s = sma(df['close'], self.short)
        l = sma(df['close'], self.long)
        value = s - l
        cross_up = (value > 0) & (value.shift(1) <= 0)
        cross_dn = (value < 0) & (value.shift(1) >= 0)
        signal = pd.Series(0, index=df.index)
        signal = signal.mask(cross_up, 1).mask(cross_dn, -1).ffill().fillna(0).astype(int)
        return pd.DataFrame({"value": value, "signal": signal})
