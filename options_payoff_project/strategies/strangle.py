
from __future__ import annotations
from dataclasses import dataclass
from options.call_option import CallOption
from options.put_option import PutOption
from .strategy_base import StrategyBase

@dataclass
class Strangle(StrategyBase):
    def __init__(self, put_strike: float, call_strike: float, put_premium: float, call_premium: float):
        if put_strike >= call_strike:
            raise ValueError("put_strike must be < call_strike for a standard long strangle.")
        super().__init__([
            PutOption(strike=put_strike, premium=put_premium),
            CallOption(strike=call_strike, premium=call_premium),
        ])

    def name(self) -> str:
        return "Long Strangle"
