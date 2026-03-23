"""Reusable dark-themed matplotlib canvas for embedding plots in PyQt5."""
from __future__ import annotations

import matplotlib
matplotlib.use("Qt5Agg")  # must be set before importing FigureCanvas

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.colors import LogNorm
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QWidget, QVBoxLayout

from lib.analysis_registry import AnalysisResult, UnitConverter


class PlotWidget(QWidget):
    """Dark-themed matplotlib figure embedded in a PyQt5 widget."""

    BG_COLOR = "#0F172A"
    AXES_BG = "#1E293B"
    TEXT_COLOR = "#E2E8F0"
    GRID_COLOR = "#334155"
    ACCENT_COLORS = [
        "#3B82F6",  # blue
        "#EF4444",  # red
        "#10B981",  # green
        "#F59E0B",  # amber
        "#A78BFA",  # purple
        "#F97316",  # orange
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._figure = Figure(facecolor=self.BG_COLOR, tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        self._toolbar.setStyleSheet(
            f"background-color: {self.AXES_BG}; color: {self.TEXT_COLOR}; "
            f"border: none;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas, 1)

        # Double-click to reset view
        self._canvas.mpl_connect("button_press_event", self._on_mouse_press)

    # ------------------------------------------------------------------
    def plot(self, result: AnalysisResult,
             x_unit: str, y_unit: str,
             log_x: bool, log_y: bool,
             log_z: bool = False,
             all_channels: list | None = None) -> None:
        """Clear and re-draw from an *AnalysisResult*."""
        self._figure.clear()

        if result.is_2d:
            self._plot_spectrogram(result, x_unit, y_unit, log_y, log_z)
        else:
            self._plot_lines(result, x_unit, y_unit, log_x, log_y,
                             all_channels)

        self._canvas.draw_idle()

    def clear(self) -> None:
        self._figure.clear()
        self._canvas.draw_idle()

    # ------------------------------------------------------------------
    def _plot_lines(self, result: AnalysisResult,
                    x_unit: str, y_unit: str,
                    log_x: bool, log_y: bool,
                    all_channels: list | None = None) -> None:
        ax = self._figure.add_subplot(111)
        self._style_axes(ax)

        for i, channel in enumerate(result.x_data):
            x = UnitConverter.convert(
                result.x_data[channel],
                result.x_axis.default_unit, x_unit,
                result.x_axis.quantity,
            )
            y = UnitConverter.convert(
                result.y_data[channel],
                result.y_axis.default_unit, y_unit,
                result.y_axis.quantity,
            )
            # Use stable color based on position in the full channel list
            if all_channels and channel in all_channels:
                ci = all_channels.index(channel)
            else:
                ci = i
            color = self.ACCENT_COLORS[ci % len(self.ACCENT_COLORS)]
            ax.plot(x, y, color=color, linewidth=0.8, alpha=0.85,
                    label=channel)

        if log_x:
            ax.set_xscale("log")
        if log_y:
            ax.set_yscale("log")

        ax.set_xlabel(f"{result.x_axis.label} ({x_unit})",
                       color=self.TEXT_COLOR, fontsize=10)
        ax.set_ylabel(f"{result.y_axis.label} ({y_unit})",
                       color=self.TEXT_COLOR, fontsize=10)
        if len(result.x_data) > 1:
            ax.legend(facecolor=self.AXES_BG, edgecolor=self.GRID_COLOR,
                      labelcolor=self.TEXT_COLOR, fontsize=8)
        ax.grid(True, alpha=0.3, color=self.GRID_COLOR)

    # ------------------------------------------------------------------
    def _plot_spectrogram(self, result: AnalysisResult,
                          x_unit: str, y_unit: str,
                          log_y: bool, log_z: bool) -> None:
        ax = self._figure.add_subplot(111)
        self._style_axes(ax)

        channel = list(result.z_data.keys())[0]
        times = UnitConverter.convert(
            result.x_data[channel],
            result.x_axis.default_unit, x_unit,
            result.x_axis.quantity,
        )
        freqs = UnitConverter.convert(
            result.y_data_2d[channel],
            result.y_axis.default_unit, y_unit,
            result.y_axis.quantity,
        )
        Sxx = result.z_data[channel]

        # Determine colour-scale normalisation
        vmin = max(Sxx[Sxx > 0].min(), 1e-30) if log_z else None
        norm = LogNorm(vmin=vmin, vmax=Sxx.max()) if log_z else None

        im = ax.pcolormesh(times, freqs, Sxx, shading="gouraud",
                           cmap="inferno", norm=norm)

        # Dark-themed colorbar
        z_label = ""
        if result.z_axis:
            z_label = f"{result.z_axis.label} ({result.z_axis.default_unit})"
        cbar = self._figure.colorbar(im, ax=ax)
        cbar.set_label(z_label, color=self.TEXT_COLOR, fontsize=9)
        cbar.ax.yaxis.set_tick_params(color=self.TEXT_COLOR)
        for lbl in cbar.ax.yaxis.get_ticklabels():
            lbl.set_color(self.TEXT_COLOR)

        ax.set_xlabel(f"{result.x_axis.label} ({x_unit})",
                       color=self.TEXT_COLOR, fontsize=10)
        ax.set_ylabel(f"{result.y_axis.label} ({y_unit})",
                       color=self.TEXT_COLOR, fontsize=10)
        if log_y:
            ax.set_yscale("log")
        ax.set_title(f"Spectrogram \u2014 {channel}",
                      color=self.TEXT_COLOR, fontsize=11)

    # ------------------------------------------------------------------
    def _on_mouse_press(self, event) -> None:
        """Double-click resets the view to home."""
        if event.dblclick:
            self._toolbar.home()

    # ------------------------------------------------------------------
    def _style_axes(self, ax) -> None:
        ax.set_facecolor(self.AXES_BG)
        ax.tick_params(colors=self.TEXT_COLOR, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(self.GRID_COLOR)
