
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt

class PayoffPlotter:
    """
    Simple payoff plotter for strategies.
    - Uses matplotlib
    - Single plot per image
    - Does not set colors or styles
    """
    def __init__(self, dpi: int = 120):
        self.dpi = dpi

    def plot_strategy(self, spot_grid: np.ndarray, pl_values: np.ndarray, title: str, outfile: str) -> None:
        fig = plt.figure(dpi=self.dpi)
        ax = fig.add_subplot(111)
        ax.plot(spot_grid, pl_values, linewidth=2)
        ax.axhline(0.0, linewidth=1)
        ax.set_xlabel("Underlying Price at Expiration")
        ax.set_ylabel("Profit / Loss (per share)")
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(outfile)
        plt.close(fig)
