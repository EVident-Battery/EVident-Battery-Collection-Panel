"""FFT Magnitude — single-sided amplitude spectrum."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AxisConfig, AnalysisResult, BaseAnalysis, infer_quantity,
)
from lib.analyses._transforms import apply_transform


@AnalysisRegistry.register
class FFTMagnitudeAnalysis(BaseAnalysis):
    name = "FFT Magnitude"
    category = "Frequency Domain"
    description = "Single-sided amplitude spectrum via FFT"

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
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

        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))
        y_quantity, y_unit = infer_quantity(channels)

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Frequency", "frequency", "Hz",
                              log_scale_default=False),
            y_axis=AxisConfig("Magnitude", y_quantity, y_unit,
                              log_scale_default=False),
            metadata={"n_samples": n, "fs": fs},
        )
