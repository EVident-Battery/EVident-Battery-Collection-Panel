"""Time Domain — raw time-series plot."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AxisConfig, AnalysisResult, BaseAnalysis, infer_quantity,
)
from lib.analyses._transforms import apply_transform


@AnalysisRegistry.register
class TimeDomainAnalysis(BaseAnalysis):
    name = "Raw Time Series"
    category = "Time Domain"
    description = "Plot raw sensor data versus time"

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        n_samples = len(signals[channels[0]])
        t = np.arange(n_samples) / fs

        x_data = {ch: t for ch in channels}
        y_data = {ch: signals[ch] for ch in channels}
        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))
        y_quantity, y_unit = infer_quantity(channels)

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Time", "time", "s", log_scale_default=False),
            y_axis=AxisConfig("Amplitude", y_quantity, y_unit, log_scale_default=False),
        )
