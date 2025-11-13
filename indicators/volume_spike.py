from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
from .base import Indicator


@dataclass
class VolumeSpike(Indicator):
    lookback: int = 20
    threshold: float = 2.0  # multiples of mean volume
    name: str = field(init=False, default='volume_spike')
    params: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        self.params = {"lookback": self.lookback, "threshold": self.threshold}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        vol_ma = df['volume'].rolling(self.lookback, min_periods=self.lookback).mean()
        ratio = df['volume'] / vol_ma
        day_ret = df['close'].pct_change()
        signal = pd.Series(0, index=df.index)
        spike = ratio >= self.threshold
        signal = signal.mask(spike & (day_ret > 0), 1).mask(spike & (day_ret < 0), -1)
        return pd.DataFrame({"value": ratio, "signal": signal.fillna(0).astype(int)})
