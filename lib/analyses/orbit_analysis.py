"""Orbit plot — parametric channel-vs-channel visualization."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AxisConfig, AnalysisResult,
    BaseAnalysis, infer_quantity,
)


@AnalysisRegistry.register
class OrbitAnalysis(BaseAnalysis):
    name = "Orbit Plot"
    category = "Multi-Channel"
    description = "Plot one channel against another (e.g. X vs Y acceleration)"

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        if len(channels) < 2:
            raise ValueError(
                "Orbit Plot requires at least 2 channels selected. "
                "The first channel is the X axis, the second is the Y axis."
            )

        ch_x, ch_y = channels[0], channels[1]
        x_quantity, x_unit = infer_quantity([ch_x])
        y_quantity, y_unit = infer_quantity([ch_y])

        series_key = f"{ch_x} vs {ch_y}"

        return AnalysisResult(
            x_data={series_key: signals[ch_x]},
            y_data={series_key: signals[ch_y]},
            x_axis=AxisConfig(ch_x, x_quantity, x_unit),
            y_axis=AxisConfig(ch_y, y_quantity, y_unit),
            metadata={"equal_aspect": True, "ch_x": ch_x, "ch_y": ch_y},
        )
