from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
from .base import Indicator


@dataclass
class GapMove(Indicator):
    percent: float = 2.0  # gap size as % of prior close to count
    name: str = field(init=False, default='gap_move')
    params: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        self.params = {"percent": self.percent}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        prev_close = df['close'].shift(1)
        gap = (df['open'] - prev_close) / prev_close * 100.0
        signal = pd.Series(0, index=df.index)
        signal = signal.mask(gap >= self.percent, 1).mask(gap <= -self.percent, -1)
        return pd.DataFrame({"value": gap, "signal": signal.fillna(0).astype(int)})
