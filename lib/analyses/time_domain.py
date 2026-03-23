"""Time Domain — raw time-series plot."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AxisConfig, AnalysisResult, BaseAnalysis,
)


@AnalysisRegistry.register
class TimeDomainAnalysis(BaseAnalysis):
    name = "Raw Time Series"
    category = "Time Domain"
    description = "Plot raw sensor data versus time"

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str]) -> AnalysisResult:
        n_samples = len(signals[channels[0]])
        t = np.arange(n_samples) / fs

        x_data = {ch: t for ch in channels}
        y_data = {ch: signals[ch] for ch in channels}

        # Detect y-axis quantity from column name prefix
        y_quantity, y_unit = _infer_quantity(channels)

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Time", "time", "s", log_scale_default=False),
            y_axis=AxisConfig("Amplitude", y_quantity, y_unit, log_scale_default=False),
        )


def _infer_quantity(channels: List[str]) -> tuple[str, str]:
    """Guess physical quantity from column name prefixes."""
    has_accel = any(c.lower().startswith("accel") for c in channels)
    has_gyro = any(c.lower().startswith("gyro") for c in channels)
    if has_accel and not has_gyro:
        return "acceleration", "g"
    if has_gyro and not has_accel:
        return "angular_velocity", "dps"
    # Mixed or unknown — default to acceleration
    return "acceleration", "g"
