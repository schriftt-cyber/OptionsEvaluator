from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
from .base import Indicator


@dataclass
class IndicatorRunner:
    indicators: List[Indicator]

    def run(self, df: pd.DataFrame, prefix: Optional[str] = None) -> pd.DataFrame:
        out = []
        for ind in self.indicators:
            res = ind.compute(df)
            base = ind.name if prefix is None else f"{prefix}{ind.name}"
            cols = {c: f"{base}_{c}" for c in res.columns}
            out.append(res.rename(columns=cols))
        return pd.concat(out, axis=1)
