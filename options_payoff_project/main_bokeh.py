
from __future__ import annotations
import numpy as np

from bokeh.io import curdoc
from bokeh.models import ColumnDataSource, Div, Select, Spinner, Button
from bokeh.layouts import column, row

from strategies.straddle import Straddle
from strategies.strangle import Strangle
from utils.plotter_bokeh import BokehPayoffPlotter
from utils.breakeven import compute_breakevens

# --- Widgets ---
strategy_select = Select(title="Strategy", value="Straddle", options=["Straddle", "Strangle"])

# Straddle inputs
K = Spinner(title="Strike (K)", low=0, step=0.5, value=80.0)
call_prem = Spinner(title="Call Premium", low=0, step=0.05, value=3.20)
put_prem = Spinner(title="Put Premium", low=0, step=0.05, value=3.10)

# Strangle inputs
K_put = Spinner(title="Put Strike (K_put)", low=0, step=0.5, value=75.0)
K_call = Spinner(title="Call Strike (K_call)", low=0, step=0.5, value=85.0)
put_prem2 = Spinner(title="Put Premium", low=0, step=0.05, value=2.10)
call_prem2 = Spinner(title="Call Premium", low=0, step=0.05, value=2.05)

# Shared inputs
S_min = Spinner(title="Min Price", low=0, step=1.0, value=40.0)
S_max = Spinner(title="Max Price", low=0, step=1.0, value=120.0)
S_step = Spinner(title="Step", low=0.01, step=0.01, value=0.25)
S_now = Spinner(title="Current Price (S)", low=0, step=0.01, value=79.50)

status = Div(text="", width=800)

plotter = BokehPayoffPlotter()

# Build initial plot
spot = np.arange(S_min.value, S_max.value + S_step.value, S_step.value)

def make_strategy():
    if strategy_select.value == "Straddle":
        return Straddle(strike=K.value, call_premium=call_prem.value, put_premium=put_prem.value)
    else:
        # ensure ordering
        kput = min(K_put.value, K_call.value)
        kcall = max(K_put.value, K_call.value)
        return Strangle(put_strike=kput, call_strike=kcall, put_premium=put_prem2.value, call_premium=call_prem2.value)

def compute_pl(strategy, spot_grid):
    return strategy.pl(spot_grid)

def render():
    global p
    spot_grid = np.arange(S_min.value, S_max.value + S_step.value, S_step.value)
    strategy = make_strategy()
    y = compute_pl(strategy, spot_grid)

    # Create/replace plot
    p, src, r = plotter.create_plot(spot_grid, y, title=f"{strategy.name()} (Total premium={strategy.total_premium():.2f})")

    # Current price P/L (interpolate)
    # Find nearest index
    idx = int(np.clip(round((S_now.value - spot_grid[0]) / (spot_grid[1] - spot_grid[0])), 0, len(spot_grid)-1))
    current_pl = float(y[idx])

    # Add current price marker
    plotter.add_current_price_marker(p, S_now.value, current_pl)

    # Add break-even annotations
    bes = compute_breakevens(strategy)
    plotter.add_breakeven_annotations(p, bes)

    # Update status
    be_text = ", ".join(f"{b:.2f}" for b in bes) if bes else "n/a"
    status.text = f"<b>Current Price:</b> {S_now.value:.2f} &nbsp; <b>Current P/L:</b> {current_pl:.2f} &nbsp; <b>Break-evens:</b> {be_text}"

    # Replace root layout
    controls_row1 = row(strategy_select, S_now, S_min, S_max, S_step)
    controls_row2 = row(K, call_prem, put_prem)
    controls_row3 = row(K_put, K_call, put_prem2, call_prem2)
    # Show only relevant controls
    if strategy_select.value == "Straddle":
        layout = column(controls_row1, controls_row2, status, p)
    else:
        layout = column(controls_row1, controls_row3, status, p)

    curdoc().clear()
    curdoc().add_root(layout)
    curdoc().title = "Options Payoff (Interactive)"

def on_change(attr, old, new):
    render()

# Wire up callbacks
for w in [strategy_select, K, call_prem, put_prem, K_put, K_call, put_prem2, call_prem2, S_min, S_max, S_step, S_now]:
    w.on_change("value", on_change)

# Initial render
render()
