
from __future__ import annotations
import numpy as np

from strategies.straddle import Straddle
from strategies.strangle import Strangle
from utils.plotter import PayoffPlotter

def demo():
    # Example parameters (adjust as needed)
    S_min, S_max, S_step = 40.0, 120.0, 0.25
    spot = np.arange(S_min, S_max + S_step, S_step)

    # Long Straddle: same strike for call/put (typically near-the-money)
    K = 80.0
    call_prem = 3.20
    put_prem = 3.10
    straddle = Straddle(strike=K, call_premium=call_prem, put_premium=put_prem)

    pl_straddle = straddle.pl(spot)
    PayoffPlotter().plot_strategy(
        spot_grid=spot,
        pl_values=pl_straddle,
        title=f"{straddle.name()} (K={K}, total premium={call_prem+put_prem:.2f})",
        outfile="straddle_payoff.png"
    )

    # Long Strangle: different strikes (both typically OTM)
    K_put = 75.0
    K_call = 85.0
    put_prem2 = 2.10
    call_prem2 = 2.05
    strangle = Strangle(put_strike=K_put, call_strike=K_call, put_premium=put_prem2, call_premium=call_prem2)

    pl_strangle = strangle.pl(spot)
    PayoffPlotter().plot_strategy(
        spot_grid=spot,
        pl_values=pl_strangle,
        title=f"{strangle.name()} (K_put={K_put}, K_call={K_call}, total premium={put_prem2+call_prem2:.2f})",
        outfile="strangle_payoff.png"
    )

    print("Wrote: straddle_payoff.png, strangle_payoff.png")

if __name__ == "__main__":
    demo()
