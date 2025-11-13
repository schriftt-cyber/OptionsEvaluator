
from __future__ import annotations
from dataclasses import dataclass
from options.call_option import CallOption
from options.put_option import PutOption
from .strategy_base import StrategyBase

@dataclass
class Straddle(StrategyBase):
    def __init__(self, strike: float, call_premium: float, put_premium: float):
        super().__init__([
            CallOption(strike=strike, premium=call_premium),
            PutOption(strike=strike, premium=put_premium),
        ])

    def name(self) -> str:
        return "Long Straddle"
