from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from bokeh.plotting import figure
from bokeh.layouts import column, gridplot
from bokeh.models import ColumnDataSource, HoverTool, Span, Band


# -----------------------------
# Helpers
# -----------------------------

def _as_cds(df: pd.DataFrame) -> ColumnDataSource:
    data = df.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        # Try common columns
        for c in ("date", "timestamp"):
            if c in data.columns:
                data[c] = pd.to_datetime(data[c])
                data = data.set_index(c)
                break
    data = data.sort_index()
    data["dt"] = data.index.to_pydatetime()
    return ColumnDataSource(data)


# -----------------------------
# Individual indicator plotters
# -----------------------------

def plot_price(df: pd.DataFrame) -> figure:
    cds = _as_cds(df)
    p = figure(x_axis_type="datetime", height=280, sizing_mode="stretch_width", title="Close Price")
    p.line("dt", "close", source=cds, line_width=2)
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("Close", "@close{0.00}")], formatters={"@dt": "datetime"}))
    return p


def plot_sma_crossover(df: pd.DataFrame, signals: pd.DataFrame) -> figure:
    cds = _as_cds(df.join(signals))
    p = figure(x_axis_type="datetime", height=240, sizing_mode="stretch_width", title="SMA Crossover")
    # Rebuild the two SMAs from value + close is not trivial; instead overlay signals as markers and show value
    p.line("dt", "close", source=cds, alpha=0.4)
    # If user wants the actual SMA lines, compute here using lookbacks from names (not stored); recommend computing externally
    # Mark crossover points
    ups = cds.data.get("sma_crossover_signal")
    if ups is not None:
        # Boolean masks in data source aren't supported; precompute indices
        pass
    p.scatter("dt", "sma_crossover_value", source=cds, size=4, alpha=0.6, legend_label="S(short)-S(long)")
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("ΔSMA", "@sma_crossover_value{0.00}"), ("Signal", "@sma_crossover_signal")], formatters={"@dt": "datetime"}))
    p.legend.click_policy = "hide"
    return p


def plot_rsi(df: pd.DataFrame, signals: pd.DataFrame, overbought: float = 70, oversold: float = 30) -> figure:
    cds = _as_cds(df.join(signals))
    p = figure(x_axis_type="datetime", height=200, sizing_mode="stretch_width", title="RSI")
    p.line("dt", "rsi_value", source=cds, line_width=2)
    for lvl in (overbought, oversold, 50):
        s = Span(location=lvl, dimension="width", line_dash="dashed", line_alpha=0.5)
        p.add_layout(s)
    p.y_range.start = 0
    p.y_range.end = 100
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("RSI", "@rsi_value{0.0}"), ("Sig", "@rsi_signal")], formatters={"@dt": "datetime"}))
    return p


def plot_macd(df: pd.DataFrame, signals: pd.DataFrame) -> figure:
    cds = _as_cds(df.join(signals))
    p = figure(x_axis_type="datetime", height=220, sizing_mode="stretch_width", title="MACD")
    p.vbar(x="dt", top="macd_value", width=12*60*60*1000, source=cds, alpha=0.5)  # hist
    p.line("dt", "macd_macd", source=cds, line_width=2, legend_label="MACD")
    p.line("dt", "macd_signal_line", source=cds, line_width=1, legend_label="Signal")
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("Hist", "@macd_value{0.00}"), ("MACD", "@macd_macd{0.00}"), ("Signal", "@macd_signal_line{0.00}")], formatters={"@dt": "datetime"}))
    p.legend.click_policy = "hide"
    return p


def plot_bollinger(df: pd.DataFrame, signals: pd.DataFrame) -> figure:
    cds = _as_cds(df.join(signals))
    p = figure(x_axis_type="datetime", height=240, sizing_mode="stretch_width", title="Bollinger Bands")
    p.line("dt", "close", source=cds, line_width=1.5)
    p.line("dt", "bollinger_mid", source=cds, line_dash="dashed")
    band = Band(base='dt', lower='bollinger_lower', upper='bollinger_upper', source=cds, level='underlay', fill_alpha=0.15)
    p.add_layout(band)
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("Close", "@close{0.00}"), ("Upper", "@bollinger_upper{0.00}"), ("Mid", "@bollinger_mid{0.00}"), ("Lower", "@bollinger_lower{0.00}")], formatters={"@dt": "datetime"}))
    return p


def plot_volume_spike(df: pd.DataFrame, signals: pd.DataFrame) -> figure:
    cds = _as_cds(df.join(signals))
    p = figure(x_axis_type="datetime", height=200, sizing_mode="stretch_width", title="Volume & Spike Ratio")
    p.vbar(x="dt", top="volume", width=12*60*60*1000, source=cds, alpha=0.5, legend_label="Volume")
    p.extra_y_ranges = {"ratio": p.y_range.clone()}
    p.add_layout(p.yaxis[0], 'left')
    p.line("dt", "volume_spike_value", source=cds, line_width=2, legend_label="Vol / MA")
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("Vol", "@volume{0,0}"), ("Ratio", "@volume_spike_value{0.00}")], formatters={"@dt": "datetime"}))
    p.legend.click_policy = "hide"
    return p


def plot_atr_breakout(df: pd.DataFrame, signals: pd.DataFrame, multiple: Optional[float] = None) -> figure:
    merged = df.join(signals)
    # If multiple provided, reconstruct bands from prev_close and ATR
    if multiple is not None and "atr_breakout_atr" in merged:
        merged = merged.copy()
        merged["prev_close"] = merged["close"].shift(1)
        merged["atr_up"] = merged["prev_close"] + multiple * merged["atr_breakout_atr"]
        merged["atr_dn"] = merged["prev_close"] - multiple * merged["atr_breakout_atr"]
    cds = _as_cds(merged)
    p = figure(x_axis_type="datetime", height=220, sizing_mode="stretch_width", title="ATR Breakout")
    p.line("dt", "close", source=cds, line_width=1.5)
    if "atr_up" in cds.data:
        p.line("dt", "atr_up", source=cds, line_dash="dashed")
        p.line("dt", "atr_dn", source=cds, line_dash="dashed")
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("Close", "@close{0.00}"), ("ATR", "@atr_breakout_atr{0.00}")], formatters={"@dt": "datetime"}))
    return p


def plot_gap_move(df: pd.DataFrame, signals: pd.DataFrame, threshold: Optional[float] = None) -> figure:
    cds = _as_cds(df.join(signals))
    p = figure(x_axis_type="datetime", height=200, sizing_mode="stretch_width", title="Gap %")
    p.vbar(x="dt", top="gap_move_value", width=12*60*60*1000, source=cds, alpha=0.6)
    if threshold is not None:
        for lvl in (threshold, -threshold):
            p.add_layout(Span(location=lvl, dimension="width", line_dash="dashed", line_alpha=0.6))
    p.add_tools(HoverTool(tooltips=[("Date", "@dt{%F}"), ("Gap %", "@gap_move_value{0.0}")], formatters={"@dt": "datetime"}))
    return p


# -----------------------------
# Dashboard factory
# -----------------------------

def build_dashboard(df: pd.DataFrame, signals: pd.DataFrame,
                    atr_multiple: Optional[float] = 1.5,
                    gap_threshold: Optional[float] = 2.0):
    """Return a Bokeh layout with one panel per indicator plus price."""
    p_price = plot_price(df)
    p_sma = plot_sma_crossover(df, signals)
    p_rsi = plot_rsi(df, signals)
    p_macd = plot_macd(df, signals)
    p_boll = plot_bollinger(df, signals)
    p_vol = plot_volume_spike(df, signals)
    p_atr = plot_atr_breakout(df, signals, multiple=atr_multiple)
    p_gap = plot_gap_move(df, signals, threshold=gap_threshold)
    return column(p_price, p_sma, p_rsi, p_macd, p_boll, p_vol, p_atr, p_gap, sizing_mode="stretch_width")
