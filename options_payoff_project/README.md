
# Options Payoff Project (One class per file)

This project plots **profit/loss (payoff) diagrams** for option strategies (Straddle and Strangle) with a clean,
extensible, one-class-per-file design.

## Structure
```
options_payoff_project/
├─ options/
│  ├─ option_base.py        # Abstract option base class
│  ├─ call_option.py        # CallOption class
│  └─ put_option.py         # PutOption class
├─ strategies/
│  ├─ strategy_base.py      # Abstract strategy base class
│  ├─ straddle.py           # Straddle strategy class
│  └─ strangle.py           # Strangle strategy class
├─ utils/
│  └─ plotter.py            # PayoffPlotter class (matplotlib)
├─ main.py                  # Example usage (plots Straddle & Strangle)
├─ requirements.txt
└─ README.md
```

## Quick Start
1. Create a virtual environment (recommended).
2. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the example:
   ```bash
   python main.py
   ```

This will generate two charts in the current directory:
- `straddle_payoff.png`
- `strangle_payoff.png`

### Notes
- Charts are produced with **matplotlib** (no seaborn, no style or color overrides).
- X-axis: Underlying price at expiration.
- Y-axis: Profit/Loss per strategy.
- Premiums are **included** in P/L (i.e., cost is subtracted).

## Customization
- Adjust strikes, premiums, and price ranges in `main.py`.
- Create new strategies by inheriting from `StrategyBase` and composing `Option` legs.


---

## NEW: Interactive Bokeh App

This project now includes an interactive **Bokeh** app that plots the payoff curve **and** overlays:
- A **current price** vertical marker,
- A **live P/L** marker and label at the current price,
- **Break-even** annotations for straddles and strangles.

### Install
```bash
pip install -r requirements.txt
```
> This will install `numpy`, `matplotlib`, and `bokeh`.

### Run the interactive app
```bash
bokeh serve --show main_bokeh.py
```
- Use the widgets to switch between **Straddle** and **Strangle** and adjust strikes & premiums.
- Set **Current Price (S)** to see the live P/L and the vertical marker.
- Break-even lines are displayed and labeled based on closed-form formulas:
  - **Straddle**: BE_low = K − (call_premium + put_premium), BE_high = K + (call_premium + put_premium)
  - **Strangle**: BE_low = K_put − (call_premium + put_premium), BE_high = K_call + (call_premium + put_premium)

### Notes
- The Bokeh app computes P/L **per share**; multiply by 100 for one standard contract.
- The static matplotlib version in `main.py` still works if you want non-interactive PNGs.
- All classes remain one-per-file. The Bokeh utilities live in `utils/plotter_bokeh.py` and `utils/breakeven.py`.
