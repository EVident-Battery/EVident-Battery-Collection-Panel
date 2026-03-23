"""FFT Magnitude — single-sided amplitude spectrum."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AxisConfig, AnalysisResult, BaseAnalysis,
)


@AnalysisRegistry.register
class FFTMagnitudeAnalysis(BaseAnalysis):
    name = "FFT Magnitude"
    category = "Frequency Domain"
    description = "Single-sided amplitude spectrum via FFT"

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str]) -> AnalysisResult:
        n = len(signals[channels[0]])
        freqs = np.fft.rfftfreq(n, d=1.0 / fs)

        x_data: Dict[str, np.ndarray] = {}
        y_data: Dict[str, np.ndarray] = {}

        for ch in channels:
            sig = signals[ch] - np.mean(signals[ch])  # remove DC offset
            spectrum = np.fft.rfft(sig)
            magnitude = np.abs(spectrum) * (2.0 / n)
            # DC and Nyquist bins should not be doubled
            magnitude[0] /= 2.0
            if n % 2 == 0:
                magnitude[-1] /= 2.0
            x_data[ch] = freqs
            y_data[ch] = magnitude

        # Detect y-axis quantity from column names
        y_quantity, y_unit = _infer_quantity(channels)

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Frequency", "frequency", "Hz",
                              log_scale_default=False),
            y_axis=AxisConfig("Magnitude", y_quantity, y_unit,
                              log_scale_default=False),
            metadata={"n_samples": n, "fs": fs},
        )


def _infer_quantity(channels: List[str]) -> tuple[str, str]:
    """Guess physical quantity from column name prefixes."""
    has_accel = any(c.lower().startswith("accel") for c in channels)
    has_gyro = any(c.lower().startswith("gyro") for c in channels)
    if has_accel and not has_gyro:
        return "acceleration", "g"
    if has_gyro and not has_accel:
        return "angular_velocity", "dps"
    return "acceleration", "g"
