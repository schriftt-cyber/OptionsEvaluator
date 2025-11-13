import os
import sys
import threading
import time
import tempfile
import webbrowser
import importlib
from tkinter import filedialog
from bokeh.resources import INLINE



from dataclasses import dataclass

# --- Tkinter UI ---
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from tkinter import filedialog
import csv

# --- Optional plotting deps (installed via: pip install bokeh numpy) ---
try:
    import numpy as np
    from bokeh.plotting import figure, output_file, save
    from bokeh.models import Label, Span
    from bokeh.layouts import gridplot, column
    from bokeh.models import Tabs, TabPanel
except Exception:
    np = None

# =========================================================
# TRY TO USE YOUR EXISTING PAYOFF CODE (from your chat)
# We attempt common import paths that match your logs:
#   - StrangleDriverX.CalculateStrangle(...)
#   - (optional) StraddleDriverX.CalculateStraddle(...)
# If not found, we fall back to a built-in demo plot.
# =========================================================
PAYOFF_BACKEND = {"strangle": None, "straddle": None}
_IMPORT_ERRORS = []

#def _try_import_payoff_backends():
#    global PAYOFF_BACKEND
#    # Add more candidate paths here if your files live in a package/folder
#    candidates = [
#        ("StrangleDriverX", "CalculateStrangle", "strangle"),
#        ("StraddleDriverX", "CalculateStraddle", "straddle"),
#        # Example: if your files are inside OptionPlotter/
#        ("OptionPlotter.StrangleDriverX", "CalculateStrangle", "strangle"),
#        ("OptionPlotter.StraddleDriverX", "CalculateStraddle", "straddle"),
#    ]
#    for mod_name, func_name, key in candidates:
#        try:
#            module = __import__(mod_name, fromlist=[func_name])
#            fn = getattr(module, func_name, None)
#            if callable(fn):
#                PAYOFF_BACKEND[key] = fn
#        except Exception as e:
#            _IMPORT_ERRORS.append(f"{mod_name}.{func_name}: {e!r}")
#
#_try_import_payoff_backends()
import webbrowser, os, shutil

def _open_in_chrome(url: str) -> bool:
    """
    Try to open a URL specifically in Google Chrome on Windows.
    Returns True if successful, False otherwise (so caller can fall back).
    """
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        shutil.which("google-chrome"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                webbrowser.register("chrome", None, webbrowser.BackgroundBrowser(path))
                webbrowser.get("chrome").open(url)
                return True
            except Exception:
                pass
    return False





# ----------------------------
# Hooks you can wire to YOUR indicators code
# ----------------------------
def run_indicators_pipeline(log_fn=print):
    """
    DROP-IN ZONE #1: Replace this with your real indicators pipeline.
    Keep it non-blocking to the UI by running in a thread (already handled).
    """
    try:
        # Example:
        # from indicators.IndicatorDriver import IndicatorDriver
        # drv = IndicatorDriver(log=log_fn)
        # drv.load_data(...)
        # drv.run_all()
        # drv.save(...)
        steps = [
            "Loading data",
            "Calculating indicators (RSI, MACD, ATR, OBV…)",
            "Validating results",
            "Writing outputs"
        ]
        for s in steps:
            log_fn(f"[Indicators] {s}...")
            time.sleep(0.6)
        log_fn("[Indicators] Done ✅")
    except Exception as e:
        log_fn(f"[Indicators] ERROR: {e}")

# ----------------------------
# Payoff utilities and fallback
# ----------------------------
@dataclass
class OptionInputs:
    ticker: str
    spot: float        # current price S0
    call_strike: float
    call_premium: float
    put_strike: float
    put_premium: float
    price_min: float
    price_max: float
    step: float


def read_option_inputs_csv(path):
    """
    Reads a CSV file with columns:
      strategy,ticker,spot,call_strike,call_premium,put_strike,put_premium,price_min,price_max,step

    Returns:
      list[OptionInputs] — one OptionInputs object per CSV row.
    """
    import csv  # local import is fine

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)

        # Required headers
        required = [
            "strategy","ticker","spot","call_strike","call_premium",
            "put_strike","put_premium","price_min","price_max","step"
        ]
        missing = [c for c in required if c not in rdr.fieldnames]
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        # Parse each row
        for i, r in enumerate(rdr, start=2):  # header is row 1
            try:
                strategy = (r["strategy"] or "").strip().lower()
                if strategy not in ("strangle","straddle"):
                    raise ValueError(f"Row {i}: strategy must be 'strangle' or 'straddle'.")

                # Helper to safely get floats
                def fget(k): return float(str(r[k]).strip())

                spot = fget("spot")
                kc   = fget("call_strike")
                c    = fget("call_premium")
                kp   = fget("put_strike")
                p    = fget("put_premium")
                pmin = fget("price_min")
                pmax = fget("price_max")
                step = fget("step")

                # If strategy is straddle, force both strikes equal
                if strategy == "straddle":
                    kp = kc

                rows.append(OptionInputs(
                    ticker=r["ticker"].strip() or "TICKER",
                    spot=spot,
                    call_strike=kc, call_premium=c,
                    put_strike=kp, put_premium=p,
                    price_min=pmin, price_max=pmax, step=step
                ))
            except Exception as e:
                raise ValueError(f"Error parsing row {i}: {e}") from e
    return rows


def _make_payoff_figure(inp: OptionInputs):
    """
    Return a single Bokeh Figure for one straddle/strangle input.
    No disk writes, no browser opens—just a figure to compose later.
    """
    if np is None:
        raise RuntimeError("Missing dependencies. Install with: pip install bokeh numpy")

    S = np.arange(inp.price_min, inp.price_max + inp.step, inp.step)
    call_leg = np.maximum(0.0, S - inp.call_strike) - inp.call_premium
    put_leg  = np.maximum(0.0, inp.put_strike - S) - inp.put_premium
    payoff   = call_leg + put_leg

    total_premium = inp.call_premium + inp.put_premium
    be_lower = inp.put_strike - total_premium
    be_upper = inp.call_strike + total_premium

    p = figure(
        title=f"{inp.ticker} Payoff (Strangle/Straddle)",
        x_axis_label="Stock Price at Expiration",
        y_axis_label="Profit / Loss (per 1x)",
        toolbar_location="right",
        sizing_mode="stretch_both",  # ⬅ fully responsive in both directions
        min_width=1000,  # ⬅ keeps it from getting too narrow
        min_height=500,
    )

    # Curve
    p.line(S, payoff, line_width=3)

    # Zero line
    p.add_layout(Span(location=0, dimension='width', line_color='gray', line_dash='dashed', line_width=1))

    # Break-evens
    p.add_layout(Span(location=be_lower, dimension='height', line_dash='dotted', line_width=2))
    p.add_layout(Span(location=be_upper, dimension='height', line_dash='dotted', line_width=2))

    # Labels (use safe y for labels)
    y_top = float(np.nanmax(payoff)) if payoff.size else 0.0
    p.add_layout(Label(x=be_lower, y=y_top, x_offset=5, y_offset=-20, text=f"BE Lower ≈ {be_lower:.2f}"))
    p.add_layout(Label(x=be_upper, y=y_top, x_offset=5, y_offset=-20, text=f"BE Upper ≈ {be_upper:.2f}"))


    # Current price marker
    idx = int(np.clip(round((inp.spot - inp.price_min) / inp.step), 0, len(S) - 1))
    spot_payoff = payoff[idx]
    p.scatter([inp.spot], [spot_payoff], size=10)
    p.add_layout(Label(x=inp.spot, y=spot_payoff, x_offset=8, y_offset=8,
                       text=f"S0={inp.spot:.2f}, P/L={spot_payoff:.2f}"))

    return p







def _fallback_compute_strangle(inp: OptionInputs):
    S = np.arange(inp.price_min, inp.price_max + inp.step, inp.step)
    call_leg = np.maximum(0.0, S - inp.call_strike) - inp.call_premium
    put_leg = np.maximum(0.0, inp.put_strike - S) - inp.put_premium
    total = call_leg + put_leg
    return S, total

def _fallback_plot(inp: OptionInputs, log_fn):
    if np is None:
        raise RuntimeError("Missing dependencies. Install with: pip install bokeh numpy")

    S, payoff = _fallback_compute_strangle(inp)
    total_premium = inp.call_premium + inp.put_premium
    be_lower = inp.put_strike - total_premium
    be_upper = inp.call_strike + total_premium

    title = f"{inp.ticker} Long Strangle Payoff (Fallback)"
    fname = f"{inp.ticker.replace('/', '-')}_payoff.html"
    out_path = os.path.join(tempfile.gettempdir(), fname)

    p = figure(
        title=title,
        x_axis_label="Stock Price at Expiration",
        y_axis_label="Profit / Loss (per 1x)",
        width=900,
        height=520,
        toolbar_location="right",
    )

    p.line(S, payoff, line_width=3)
    p.add_layout(Span(location=0, dimension='width', line_color='gray', line_dash='dashed', line_width=1))

    # Break-evens
    p.add_layout(Span(location=be_lower, dimension='height', line_dash='dotted', line_width=2))
    p.add_layout(Span(location=be_upper, dimension='height', line_dash='dotted', line_width=2))
    p.add_layout(Label(x=be_lower, y=max(payoff), x_offset=5, y_offset=-20, text=f"BE Lower ≈ {be_lower:.2f}"))
    p.add_layout(Label(x=be_upper, y=max(payoff), x_offset=5, y_offset=-20, text=f"BE Upper ≈ {be_upper:.2f}"))

    # Current price marker
    idx = int(np.clip(round((inp.spot - inp.price_min) / inp.step), 0, len(S) - 1))
    spot_payoff = payoff[idx]
    p.scatter([inp.spot], [spot_payoff], size=10)
    p.add_layout(Label(x=inp.spot, y=spot_payoff, x_offset=8, y_offset=8,
                       text=f"S0={inp.spot:.2f}, P/L={spot_payoff:.2f}"))

    output_file(out_path)
    save(p, resources=INLINE)

    try:
        #webbrowser.open(f"file:///{out_path}")
        print("[Options] Using your Payoff diagram.")
    except Exception:
        pass
    return out_path

def plot_option_payoff_using_your_code(inp: OptionInputs, log_fn=print):
    """
    DROP-IN ZONE #2: Use YOUR Payoff code from the Payoff diagram chat.
    We try to call StrangleDriverX.CalculateStrangle(...).
    If unavailable or signature mismatch, we fall back to the built-in plot.
    """
    # Prefer your Strangle implementation
    if PAYOFF_BACKEND["strangle"]:
        try:
            log_fn("[Options] Using your StrangleDriverX.CalculateStrangle(...)")
            # We pass common, self-describing keywords; your function can ignore extras
            # if it doesn't use them. Adjust names below if your function expects different ones.
            return PAYOFF_BACKEND["strangle"](
                ticker=inp.ticker,
                spot=inp.spot,
                call_strike=inp.call_strike,
                call_premium=inp.call_premium,
                put_strike=inp.put_strike,
                put_premium=inp.put_premium,
                price_min=inp.price_min,
                price_max=inp.price_max,
                step=inp.step,
                # You can add any extra flags your code supports, e.g. output path, open browser, etc.
            )
        except TypeError as te:
            # Signature mismatch—guide the user and fall back
            log_fn(f"[Options] Your CalculateStrangle signature didn’t match keywords. Details: {te}")
            log_fn("[Options] Falling back to built-in plot. To fix, open gui_launcher.py and adjust the call in plot_option_payoff_using_your_code().")
        except Exception as e:
            log_fn(f"[Options] Your backend raised an error: {e}. Falling back to built-in plot.")

    # Fallback if your module not found or errored
    if _IMPORT_ERRORS:
        log_fn("[Options] Couldn’t import your payoff module. Tried:")
        for line in _IMPORT_ERRORS:
            log_fn(f"         - {line}")
        log_fn("[Options] Using built-in fallback plot.")

    return _fallback_plot(inp, log_fn)

# ---- robust loader for vol_scan_integration.py ----
import sys, pathlib, importlib.util, traceback

def _load_vol_scan_module(log_fn=print):
    """
    Load vol_scan_integration.py by absolute path so cwd / sys.path don't matter.
    Returns the loaded module object.
    """
    base = pathlib.Path(__file__).resolve().parent
    candidates = [
        base / "vol_scan_integration.py",
        base / "scanners" / "vol_scan_integration.py",  # optional fallback folder
    ]

    for path in candidates:
        if path.exists():
            try:
                mod_name = "vol_scan_integration"  # fixed name
                spec = importlib.util.spec_from_file_location(mod_name, str(path))
                if spec is None or spec.loader is None:
                    raise ImportError(f"Could not create spec for {path}")
                mod = importlib.util.module_from_spec(spec)
                # replace any stale cached module
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
                log_fn(f"[Vol Scanner] Loaded module from: {path}")
                return mod
            except Exception as e:
                log_fn(f"[Vol Scanner] Import failed from {path}: {e}")
                log_fn(traceback.format_exc())
                raise
    raise FileNotFoundError("vol_scan_integration.py not found in expected locations.")


# ----------------------------
# Tkinter App
# ----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Trading Tools Launcher")
        self.geometry("700x420")

        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=10)
        ttk.Label(top, text="Quick Launch", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)

        btns = ttk.Frame(self); btns.pack(side=tk.TOP, fill=tk.X, padx=12, pady=8)

        self.btn_ind = ttk.Button(btns, text="Run Indicators", command=self._on_run_indicators)
        self.btn_ind.pack(side=tk.LEFT, padx=6)

        #self.btn_opt = ttk.Button(btns, text="Plot Option Payoff", command=self._on_plot_options)
        #self.btn_opt.pack(side=tk.LEFT, padx=6)

        self.btn_csv = ttk.Button(btns, text="Strat/Strang Plot", command=self._on_plot_from_csv)
        self.btn_csv.pack(side=tk.LEFT, padx=6)

        self.btn_vol = ttk.Button(btns, text="Run Vol Scanner", command=self._on_run_vol_scanner)
        self.btn_vol.pack(side=tk.LEFT, padx=6)

        self.log = ScrolledText(self, height=16)
        self.log.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=8)

        self.status = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill=tk.X, padx=12, pady=(0, 10))

        self._log("Ready.")

        self._style = ttk.Style()
        try: self._style.theme_use("vista")
        except Exception: pass

    def _log(self, msg: str):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.status.set(msg)

    def _run_bg(self, target, *args, **kwargs):
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()

    def _on_run_indicators(self):
        self._log("Starting Indicators…")
        self.btn_ind.config(state=tk.DISABLED)
        def job():
            try:
                run_indicators_pipeline(log_fn=self._log)
            finally:
                self.btn_ind.config(state=tk.NORMAL)
                self._log("Indicators task finished.")
        self._run_bg(job)

    def _on_plot_options(self):
        try:
            ticker = simpledialog.askstring("Ticker", "Ticker (e.g., NVDA):", parent=self) or "TICKER"
            spot = float(simpledialog.askstring("Spot", "Current price (S0):", parent=self) or "100")
            kc = float(simpledialog.askstring("Call strike", "Call strike (Kc):", parent=self) or "105")
            c = float(simpledialog.askstring("Call premium", "Call premium (C):", parent=self) or "2.50")
            kp = float(simpledialog.askstring("Put strike", "Put strike (Kp):", parent=self) or "95")
            p = float(simpledialog.askstring("Put premium", "Put premium (P):", parent=self) or "2.50")
            pmin = float(simpledialog.askstring("Range min", "Price range min:", parent=self) or "70")
            pmax = float(simpledialog.askstring("Range max", "Price range max:", parent=self) or "130")
            step = float(simpledialog.askstring("Step", "Price step:", parent=self) or "0.5")

            inp = OptionInputs(
                ticker=ticker, spot=spot,
                call_strike=kc, call_premium=c,
                put_strike=kp, put_premium=p,
                price_min=pmin, price_max=pmax, step=step
            )
        except Exception as e:
            messagebox.showerror("Invalid Input", f"Please enter numeric values.\n\nDetails: {e}")
            return

        self._log("Generating option payoff…")
        self.btn_opt.config(state=tk.DISABLED)

        def job():
            try:
                path_or_result = plot_option_payoff_using_your_code(inp, log_fn=self._log)
                # If your function returns an HTML path, open it. If it already opens a browser, no worries.
                if isinstance(path_or_result, str) and path_or_result.lower().endswith(".html"):
                    try: webbrowser.open(f"file:///{path_or_result}")
                    except Exception: pass
                self._log(f"Done. {path_or_result if path_or_result else ''}")
            except Exception as e:
                self._log(f"[Options] ERROR: {e}")
                messagebox.showerror("Plot Error", str(e))
            finally:
                self.btn_opt.config(state=tk.NORMAL)
                self._log("Option payoff task finished.")
        self._run_bg(job)

    def _on_plot_from_csv(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select options_input.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            inputs_list = read_option_inputs_csv(path)
        except Exception as e:
            messagebox.showerror("CSV Error", str(e))
            return

        if not inputs_list:
            messagebox.showinfo("No rows", "CSV has no data rows.")
            return

        self._log(f"Loaded {len(inputs_list)} row(s) from CSV. Building combined HTML with tabs…")
        self.btn_csv.config(state=tk.DISABLED)

        def job():
            try:
                # Build one figure per row (use our internal builder so we can compose them)
                panels = []
                for idx, inp in enumerate(inputs_list, 1):
                    try:
                        self._log(f"[{idx}/{len(inputs_list)}] {inp.ticker}: rendering figure…")
                        fig = _make_payoff_figure(inp)
                        label = f"{inp.ticker} | Kc={inp.call_strike:g}, C={inp.call_premium:g} | Kp={inp.put_strike:g}, P={inp.put_premium:g}"
                        panels.append(TabPanel(child=fig, title=label))
                    except Exception as e:
                        self._log(f"[{idx}/{len(inputs_list)}] {inp.ticker}: ERROR {e}")

                if not panels:
                    self._log("No valid rows to plot.")
                    return

                tabs = Tabs(tabs=panels, sizing_mode="stretch_both")  # ⬅ enable responsiveness
                tabs.width_policy = "max"
                tabs.styles = {"width": "98vw"}  # ⬅ let the tabs span almost the entire viewport

                # Single output file in tempdir
                import tempfile, time, os
                ts = time.strftime("%Y%m%d_%H%M%S")
                fname = f"options_payoffs_{ts}.html"
                out_path = os.path.join(tempfile.gettempdir(), fname)

                from bokeh.plotting import output_file, save
                output_file(out_path, title="Option Payoffs (Tabs)")
                save(tabs, resources=INLINE)

                self._log(f"Saved combined HTML: {out_path}")
                try:
                    import webbrowser
                    webbrowser.open(f"file:///{out_path}")
                except Exception:
                    pass
            finally:
                self.btn_csv.config(state=tk.NORMAL)
                self._log("CSV plotting finished.")

        self._run_bg(job)

    def _on_run_vol_scanner(self):
        """
        Prompt user for a CSV file and run vol_scan_integration using that data.
        """
        self._log("Starting Vol Scanner…")
        self.btn_vol.config(state=tk.DISABLED)

        def job():
            try:
                # Dynamically load vol_scan_integration.py (using the robust loader)
                vol_mod = _load_vol_scan_module(self._log)

                # === Prompt for CSV file ===
                csv_path = filedialog.askopenfilename(
                    title="Select OHLCV CSV File",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
                )
                if not csv_path:
                    self._log("Vol Scanner cancelled — no file selected.")
                    return
                self._log(f"Selected CSV file: {csv_path}")

                # === Detect tickers in the CSV ===
                try:
                    import pandas as pd
                    df_all = pd.read_csv(csv_path)
                    if "Ticker" in df_all.columns:
                        tickers = sorted(df_all["Ticker"].dropna().unique().tolist())
                        self._log(f"Found {len(tickers)} ticker(s) in CSV: {tickers}")
                    else:
                        self._log("No 'Ticker' column in CSV — using default tickers list.")
                        tickers = ["NVDA", "AAPL", "MSFT"]
                except Exception as e:
                    self._log(f"Could not parse CSV to detect tickers: {e}")
                    tickers = ["NVDA", "AAPL", "MSFT"]

                # === Run the Vol Scanner ===
                self._log(f"Scanning {len(tickers)} tickers for volatility patterns…")
                cfg = vol_mod.DEFAULTS.copy()
                cfg["LOCAL_CSV_PATH"] = csv_path  # pass file path into scanner

                df = vol_mod.build_vol_table_df(tickers, preset="15%", csv_file=csv_path)

                if df.empty:
                    self._log("No data found for volatility scan.")
                    return

                # === Render output ===
                self._log("Rendering volatility table to HTML…")
                outfile = vol_mod.render_vol_table_html(df, outfile="vol_scanner_summary.html")
                self._log(f"Vol scanner output: {outfile}")

                url = f"file:///{os.path.abspath(outfile)}"
                if not _open_in_chrome(url):
                    webbrowser.open(url)  # fallback to system default if Chrome not found
                self._log("Opened volatility summary in Chrome.")


            except FileNotFoundError as e:
                self._log(str(e))
                messagebox.showerror("Missing File", str(e))
            except Exception as e:
                import traceback
                self._log(f"[Vol Scanner] ERROR: {e}")
                self._log(traceback.format_exc())
                messagebox.showerror("Vol Scanner Error", str(e))
            finally:
                self.btn_vol.config(state=tk.NORMAL)
                self._log("Vol Scanner task finished.")

        self._run_bg(job)


def main():
    sys.stdout.reconfigure(line_buffering=True)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()