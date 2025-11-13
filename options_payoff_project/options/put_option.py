
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .option_base import Option

@dataclass
class PutOption(Option):
    def payoff(self, spot: np.ndarray) -> np.ndarray:
        return np.maximum(self.strike - spot, 0.0)
