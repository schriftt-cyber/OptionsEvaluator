from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, Protocol
import pandas as pd

class Indicator(Protocol):
    name: str
    params: Dict[str, Any]
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with at least columns: 'value' and 'signal' (-1/0/+1)."""
        ...
