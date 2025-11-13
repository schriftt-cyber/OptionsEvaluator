
from __future__ import annotations
from typing import List
from strategies.straddle import Straddle
from strategies.strangle import Strangle

def compute_breakevens(strategy) -> List[float]:
    """
    Closed-form break-even points for supported strategies.
    Returns lower->upper sorted list.
    """
    total_prem = strategy.total_premium()
    if isinstance(strategy, Straddle):
        # Straddle K_put = K_call = K
        K = strategy.legs[0].strike  # either leg
        return sorted([K - total_prem, K + total_prem])
    if isinstance(strategy, Strangle):
        # Strangle lower BE at K_put - total_prem, upper BE at K_call + total_prem
        K_put = min(l.strike for l in strategy.legs)
        K_call = max(l.strike for l in strategy.legs)
        return sorted([K_put - total_prem, K_call + total_prem])
    # Fallback: none
    return []
