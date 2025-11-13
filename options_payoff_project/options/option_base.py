
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable
import numpy as np

@dataclass
class Option(ABC):
    strike: float
    premium: float  # price paid per share (e.g., $2.18). Strategy assumes 1 contract = 100 shares elsewhere if desired.

    @abstractmethod
    def payoff(self, spot: np.ndarray) -> np.ndarray:
        """
        Payoff at expiration per share BEFORE premium.
        Implement as intrinsic value only (no time value): max(..., 0).
        """
        ...

    def pl(self, spot: np.ndarray) -> np.ndarray:
        """
        Profit/Loss per share at expiration INCLUDING premium paid.
        For long options, P/L = payoff - premium.
        """
        return self.payoff(spot) - self.premium
