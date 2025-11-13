from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
from .base import Indicator
from .utils import true_range


@dataclass
class ATRBreakout(Indicator):
    length: int = 14
    multiple: float = 1.5
    name: str = field(init=False, default='atr_breakout')
    params: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        self.params = {"length": self.length, "multiple": self.multiple}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        tr = true_range(df)
        atr = tr.ewm(alpha=1/self.length, adjust=False, min_periods=self.length).mean()
        prev_close = df['close'].shift(1)
        up_break = df['close'] >= (prev_close + self.multiple * atr)
        dn_break = df['close'] <= (prev_close - self.multiple * atr)
        signal = pd.Series(0, index=df.index)
        signal = signal.mask(up_break, 1).mask(dn_break, -1)
        value = (df['close'] - prev_close) / (atr.replace(0, pd.NA))
        return pd.DataFrame({"value": value, "signal": signal.fillna(0).astype(int), "atr": atr})
