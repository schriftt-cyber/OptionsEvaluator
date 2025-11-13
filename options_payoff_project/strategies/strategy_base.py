
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List
import numpy as np

from options.option_base import Option

@dataclass
class StrategyBase(ABC):
    legs: List[Option] = field(default_factory=list)

    def add_leg(self, leg: Option) -> None:
        self.legs.append(leg)

    @abstractmethod
    def name(self) -> str:
        ...

    def pl(self, spot: np.ndarray) -> np.ndarray:
        """
        Sum of leg P/L per share (long-only legs). For multi-contract sizing, scale externally.
        """
        if not self.legs:
            return np.zeros_like(spot, dtype=float)
        total = sum((leg.pl(spot) for leg in self.legs))
        return total

    def total_premium(self) -> float:
        return sum(leg.premium for leg in self.legs)
