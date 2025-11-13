import os
import sys
import threading
import time
import tempfile
import webbrowser
import importlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import subprocess
import traceback

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from tkinter.scrolledtext import ScrolledText

# --- Optional plotting deps (installed via: pip install bokeh numpy) ---
try:
    import numpy as np
    from bokeh.plotting import figure, output_file, save
    from bokeh.models import Label, Span, Tabs, TabPanel
    from bokeh.resources import INLINE
except Exception:
    np = None

BASE_DIR = Path(__file__).resolve().parent

# ----------------------------
# Browser helper (prefer Chrome)
# ----------------------------
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
# Vol scanner module loader
# ----------------------------
import importlib.util

def _load_vol_scan_module(log_fn=print):
    """
    Load vol_scan_integration.py by absolute path so cwd / sys.path don't matter.
    Returns the loaded module object.
    """
    base = Path(__file__).resolve().parent
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


def _ticker_list_from_file(path):
    """
    Read tickers from a text file (one per line, '#' for comments).
    Returns a list of uppercased tickers.
    """
    p = Path(path)
    if not p.exists():
        return []

    tickers = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line.upper())
    return tickers


# ----------------------------
# Option payoff utilities
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
    import csv

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)

        # Required headers
        required = [
            "strategy", "ticker", "spot", "call_strike", "call_premium",
            "put_strike", "put_premium", "price_min", "price_max", "step",
        ]
        missing = [c for c in required if c not in rdr.fieldnames]
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        for i, r in enumerate(rdr, start=2):  # header is row 1
            try:
                strategy = (r["strategy"] or "").strip().lower()
                if strategy not in ("strangle", "straddle"):
                    raise ValueError(f"Row {i}: strategy must be 'strangle' or 'straddle'.")

                def fget(k):
                    return float(str(r[k]).strip())

                spot = fget("spot")
                kc = fget("call_strike")
                c = fget("call_premium")
                kp = fget("put_strike")
                p = fget("put_premium")
                pmin = fget("price_min")
                pmax = fget("price_max")
                step = fget("step")

                if strategy == "straddle":
                    kp = kc

                rows.append(OptionInputs(
                    ticker=r["ticker"].strip() or "TICKER",
                    spot=spot,
                    call_strike=kc, call_premium=c,
                    put_strike=kp, put_premium=p,
                    price_min=pmin, price_max=pmax, step=step,
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
    put_leg = np.maximum(0.0, inp.put_strike - S) - inp.put_premium
    payoff = call_leg + put_leg

    total_premium = inp.call_premium + inp.put_premium
    be_lower = inp.put_strike - total_premium
    be_upper = inp.call_strike + total_premium

    p = figure(
        title=f"{inp.ticker} Payoff (Strangle/Straddle)",
        x_axis_label="Stock Price at Expiration",
        y_axis_label="Profit / Loss (per 1x)",
        toolbar_location="right",
        sizing_mode="stretch_both",
        min_width=1000,
        min_height=500,
    )

    # Curve
    p.line(S, payoff, line_width=3)

    # Zero line
    p.add_layout(Span(location=0, dimension='width', line_color='gray',
                      line_dash='dashed', line_width=1))

    # Break-evens
    p.add_layout(Span(location=be_lower, dimension='height',
                      line_dash='dotted', line_width=2))
    p.add_layout(Span(location=be_upper, dimension='height',
                      line_dash='dotted', line_width=2))

    y_top = float(np.nanmax(payoff)) if payoff.size else 0.0
    p.add_layout(Label(x=be_lower, y=y_top, x_offset=5, y_offset=-20,
                       text=f"BE Lower ≈ {be_lower:.2f}"))
    p.add_layout(Label(x=be_upper, y=y_top, x_offset=5, y_offset=-20,
                       text=f"BE Upper ≈ {be_upper:.2f}"))

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
    p.add_layout(Span(location=0, dimension='width', line_color='gray',
                      line_dash='dashed', line_width=1))

    # Break-evens
    p.add_layout(Span(location=be_lower, dimension='height',
                      line_dash='dotted', line_width=2))
    p.add_layout(Span(location=be_upper, dimension='height',
                      line_dash='dotted', line_width=2))
    p.add_layout(Label(x=be_lower, y=max(payoff), x_offset=5, y_offset=-20,
                       text=f"BE Lower ≈ {be_lower:.2f}"))
    p.add_layout(Label(x=be_upper, y=max(payoff), x_offset=5, y_offset=-20,
                       text=f"BE Upper ≈ {be_upper:.2f}"))

    # Current price marker
    idx = int(np.clip(round((inp.spot - inp.price_min) / inp.step), 0, len(S) - 1))
    spot_payoff = payoff[idx]
    p.scatter([inp.spot], [spot_payoff], size=10)
    p.add_layout(Label(x=inp.spot, y=spot_payoff, x_offset=8, y_offset=8,
                       text=f"S0={inp.spot:.2f}, P/L={spot_payoff:.2f}"))

    output_file(out_path)
    save(p, resources=INLINE)

    log_fn("[Options] Using built-in payoff diagram.")
    return out_path


def plot_option_payoff_using_your_code(inp: OptionInputs, log_fn=print):
    """
    Currently we only use the built-in fallback plot.
    This is kept as a hook if you later wire your own payoff backend.
    """
    return _fallback_plot(inp, log_fn)


# ----------------------------
# Tkinter App
# ----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Trading Tools Launcher")
        self.geometry("700x420")

        # Top header
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=10)
        ttk.Label(top, text="Quick Launch", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)

        # Button row
        btns = ttk.Frame(self)
        btns.pack(side=tk.TOP, fill=tk.X, padx=12, pady=8)

        self.btn_ind = ttk.Button(btns, text="Run Indicators",
                                  command=self.run_indicators)
        self.btn_ind.pack(side=tk.LEFT, padx=6)

        # Button for CSV-based payoff plotting
        self.btn_csv = ttk.Button(btns, text="Strat/Strang Plot (CSV)",
                                  command=self._on_plot_from_csv)
        self.btn_csv.pack(side=tk.LEFT, padx=6)

        # Existing CSV-based vol scanner
        self.btn_vol = ttk.Button(btns, text="Run Vol Scanner",
                                  command=self._on_run_vol_scanner)
        self.btn_vol.pack(side=tk.LEFT, padx=6)

        # NEW: Schwab-based vol scanner
        self.btn_vol_schwab = ttk.Button(
            btns,
            text="Schwab Vol Scanner",
            command=self._on_run_vol_scanner_schwab,
        )
        self.btn_vol_schwab.pack(side=tk.LEFT, padx=6)

        # Status + log
        self.status = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(
            fill=tk.X, padx=12, pady=(0, 10)
        )

        self.log = ScrolledText(self, height=10, state="normal")
        self.log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self._style = ttk.Style()
        try:
            self._style.theme_use("vista")
        except Exception:
            pass

        self._log("Ready.")

    # --- helpers ---
    def _log(self, msg: str):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.status.set(msg)

    def _run_bg(self, target, *args, **kwargs):
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()

    # --- Run Indicators (popup + Schwab CSV) ---
    def run_indicators(self):
        """
        Ask the user for a ticker, then run the indicators dashboard using the
        already-downloaded Schwab OHLCV data.

        Prefers the GUI-generated Schwab CSV (schwab_ohlcv_gui.csv), but will
        fall back to schwab_ohlcv.csv if that one exists instead.
        """
        ticker = simpledialog.askstring(
            "Run Indicators",
            "Enter ticker symbol (e.g. AAPL, NVDA, SPY):",
            parent=self,
        )
        if not ticker:
            # user cancelled or left blank
            self._log("Indicators cancelled.")
            return

        ticker = ticker.strip().upper()
        if not ticker:
            messagebox.showerror("Error", "Ticker cannot be empty.")
            return

        # Prefer the GUI Schwab file, fall back to CLI one
        schwab_csv_gui = BASE_DIR / "csv_html" / "schwab_ohlcv_gui.csv"
        schwab_csv_cli = BASE_DIR / "csv_html" / "schwab_ohlcv.csv"

        if schwab_csv_gui.exists():
            schwab_csv = schwab_csv_gui
        elif schwab_csv_cli.exists():
            schwab_csv = schwab_csv_cli
        else:
            messagebox.showerror(
                "Error",
                "No Schwab OHLCV CSV found.\n\n"
                f"Tried:\n  {schwab_csv_gui}\n  {schwab_csv_cli}\n\n"
                "Run either the Schwab Vol Scanner from the GUI\n"
                "or schwab_vol_scan_prep.py first.",
            )
            return

        script = BASE_DIR / "indicators_dashboard_from_schwab.py"
        if not script.exists():
            messagebox.showerror(
                "Error",
                f"Indicator script not found:\n{script}\n\n"
                f"Make sure you saved indicators_dashboard_from_schwab.py in the repo root.",
            )
            return

        self._log(f"Running indicators for {ticker} using {schwab_csv.name}...")

        def job():
            # capture stdout/stderr so we can show the real error
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--ticker",
                    ticker,
                    "--schwab-csv",
                    str(schwab_csv),
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                self._log(f"Indicators dashboard generated for {ticker}.")
                if result.stdout.strip():
                    self._log("[Indicators stdout]")
                    self._log(result.stdout.strip())
            else:
                self._log(f"[Indicators] script exited with code {result.returncode}")
                if result.stdout.strip():
                    self._log("[Indicators stdout]")
                    self._log(result.stdout.strip())
                if result.stderr.strip():
                    self._log("[Indicators stderr]")
                    self._log(result.stderr.strip())

                messagebox.showerror(
                    "Indicators Error",
                    "Indicators script failed.\n\n"
                    f"Exit code: {result.returncode}\n\n"
                    f"STDOUT:\n{result.stdout[-1000:]}\n\n"
                    f"STDERR:\n{result.stderr[-1000:]}"
                )

        # Run in background so GUI doesn't freeze
        self._run_bg(job)

    # --- button handlers ---
    def _on_plot_from_csv(self):
        path = filedialog.askopenfilename(
            title="Select options_input.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
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
                panels = []
                for idx, inp in enumerate(inputs_list, 1):
                    try:
                        self._log(f"[{idx}/{len(inputs_list)}] {inp.ticker}: rendering figure…")
                        fig = _make_payoff_figure(inp)
                        label = (
                            f"{inp.ticker} | "
                            f"Kc={inp.call_strike:g}, C={inp.call_premium:g} | "
                            f"Kp={inp.put_strike:g}, P={inp.put_premium:g}"
                        )
                        panels.append(TabPanel(child=fig, title=label))
                    except Exception as e:
                        self._log(f"[{idx}/{len(inputs_list)}] {inp.ticker}: ERROR {e}")

                if not panels:
                    self._log("No valid rows to plot.")
                    return

                tabs = Tabs(tabs=panels, sizing_mode="stretch_both")
                tabs.width_policy = "max"

                ts = time.strftime("%Y%m%d_%H%M%S")
                fname = f"options_payoffs_{ts}.html"
                out_path = os.path.join(tempfile.gettempdir(), fname)

                output_file(out_path, title="Option Payoffs (Tabs)")
                save(tabs, resources=INLINE)

                self._log(f"Saved combined HTML: {out_path}")
                try:
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
                vol_mod = _load_vol_scan_module(self._log)

                csv_path = filedialog.askopenfilename(
                    title="Select OHLCV CSV File",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                )
                if not csv_path:
                    self._log("Vol Scanner cancelled — no file selected.")
                    return
                self._log(f"Selected CSV file: {csv_path}")

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

                self._log(f"Scanning {len(tickers)} tickers for volatility patterns…")
                df = vol_mod.build_vol_table_df(tickers, preset="15%", csv_file=csv_path)

                if df.empty:
                    self._log("No data found for volatility scan.")
                    return

                self._log("Rendering volatility table to HTML…")
                outfile = vol_mod.render_vol_table_html(df, outfile="vol_scanner_summary.html")
                self._log(f"Vol scanner output: {outfile}")

                url = f"file:///{os.path.abspath(outfile)}"
                if not _open_in_chrome(url):
                    webbrowser.open(url)
                self._log("Opened volatility summary in browser.")

            except FileNotFoundError as e:
                self._log(str(e))
                messagebox.showerror("Missing File", str(e))
            except Exception as e:
                self._log(f"[Vol Scanner] ERROR: {e}")
                self._log(traceback.format_exc())
                messagebox.showerror("Vol Scanner Error", str(e))
            finally:
                self.btn_vol.config(state=tk.NORMAL)
                self._log("Vol Scanner task finished.")

        self._run_bg(job)

    def _on_run_vol_scanner_schwab(self):
        """
        Fetch OHLCV from Schwab based on a tickers text file and
        run the vol scanner using that data.
        """
        self._log("Starting Schwab Vol Scanner…")
        self.btn_vol_schwab.config(state=tk.DISABLED)

        def job():
            try:
                try:
                    from schwab_vol_scan_prep import fetch_ohlcv_for_tickers
                except ImportError as e:
                    self._log(f"[Schwab] Could not import schwab_vol_scan_prep: {e}")
                    messagebox.showerror(
                        "Missing module",
                        "schwab_vol_scan_prep.py not found or import failed.\n"
                        "Make sure you've added it to the project.",
                    )
                    return

                ticker_file = filedialog.askopenfilename(
                    title="Select text file with tickers (one per line)",
                    filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                )
                if not ticker_file:
                    self._log("Schwab Vol Scanner cancelled — no tickers file selected.")
                    return

                tickers = _ticker_list_from_file(ticker_file)
                if not tickers:
                    self._log("Ticker file was empty or only comments.")
                    messagebox.showwarning(
                        "No tickers",
                        "No valid tickers found in the selected file.",
                    )
                    return

                self._log(f"[Schwab] Fetching OHLCV for {len(tickers)} ticker(s)…")
                df = fetch_ohlcv_for_tickers(tickers, lookback_days=260)
                if df.empty:
                    self._log("[Schwab] No data returned from Schwab.")
                    messagebox.showwarning(
                        "No data",
                        "No data was returned from Schwab for these tickers.",
                    )
                    return

                base_dir = os.path.dirname(os.path.abspath(__file__))
                csv_dir = os.path.join(base_dir, "csv_html")
                os.makedirs(csv_dir, exist_ok=True)

                csv_path = os.path.join(csv_dir, "schwab_ohlcv_gui.csv")
                df.to_csv(csv_path, index=False)
                self._log(f"[Schwab] Wrote OHLCV CSV to: {csv_path}")

                vol_mod = _load_vol_scan_module(self._log)

                self._log("Building volatility table from Schwab data…")
                vol_df = vol_mod.build_vol_table_df(
                    tickers,
                    preset="15%",
                    csv_file=csv_path,
                )
                if vol_df.empty:
                    self._log("Vol scanner returned no rows.")
                    messagebox.showwarning(
                        "Empty result",
                        "Vol scanner returned no rows.",
                    )
                    return

                self._log("Rendering volatility table to HTML…")
                outfile = vol_mod.render_vol_table_html(
                    vol_df,
                    outfile="vol_scanner_from_schwab.html",
                    title="Vol Scanner (Schwab Data)",
                )

                self._log(f"Schwab Vol scanner output: {outfile}")
                url = f"file:///{os.path.abspath(outfile)}"
                if not _open_in_chrome(url):
                    webbrowser.open(url)
                self._log("Opened Schwab volatility summary in browser.")

            except Exception as e:
                self._log(f"[Schwab Vol Scanner] ERROR: {e}")
                self._log(traceback.format_exc())
                messagebox.showerror("Schwab Vol Scanner Error", str(e))
            finally:
                self.btn_vol_schwab.config(state=tk.NORMAL)
                self._log("Schwab Vol Scanner task finished.")

        self._run_bg(job)


def main():
    sys.stdout.reconfigure(line_buffering=True)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
