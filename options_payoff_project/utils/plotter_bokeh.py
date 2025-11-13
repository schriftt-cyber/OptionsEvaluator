
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, List
import numpy as np

from bokeh.plotting import figure
from bokeh.models import Span, Label, HoverTool, ColumnDataSource
from bokeh.layouts import column
from bokeh.models.annotations import Title

@dataclass
class BokehPayoffPlotter:
    width: int = 800
    height: int = 420
    tools: str = "pan,wheel_zoom,box_zoom,reset,save,hover"

    def create_plot(self, x: np.ndarray, y: np.ndarray, title: str) -> Tuple:
        source = ColumnDataSource(dict(x=x, y=y))
        p = figure(width=self.width, height=self.height, tools=self.tools, active_drag="pan",
                   x_axis_label="Underlying Price at Expiration",
                   y_axis_label="Profit / Loss (per share)")
        # Payoff line
        r = p.line("x", "y", line_width=2, source=source)
        # Zero P/L line
        zero = Span(location=0.0, dimension='width', line_width=1)
        p.add_layout(zero)

        # Hover follows the line
        hover = p.select_one(HoverTool)
        hover.tooltips = [("Price", "@x{0.00}"), ("P/L", "@y{0.00}")]
        hover.mode = "vline"

        # Title
        p.title = Title(text=title, align="left")

        return p, source, r

    def add_current_price_marker(self, p, current_price: float, current_pl: float):
        vline = Span(location=current_price, dimension='height', line_dash='dashed', line_width=1)
        p.add_layout(vline)
        # Marker and label
        p.circle([current_price], [current_pl], size=8)
        label = Label(x=current_price, y=current_pl, x_offset=8, y_offset=8,
                      text=f"Current: S={current_price:.2f}, P/L={current_pl:.2f}", text_font_size="10pt")
        p.add_layout(label)

    def add_breakeven_annotations(self, p, breakevens: List[float]):
        for be in breakevens:
            span = Span(location=be, dimension='height', line_width=1)
            p.add_layout(span)
            lbl = Label(x=be, y=p.y_range.end if hasattr(p.y_range, "end") and p.y_range.end is not None else 0,
                        x_offset=5, y_offset=5, text=f"BE: {be:.2f}", text_font_size="9pt")
            p.add_layout(lbl)
