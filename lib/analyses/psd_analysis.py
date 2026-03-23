"""Power Spectral Density — Welch estimate."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
from scipy.signal import welch

from lib.analysis_registry import (
    AnalysisRegistry, AnalysisParameter, AxisConfig, AnalysisResult,
    BaseAnalysis, infer_quantity,
)


@AnalysisRegistry.register
class PSDAnalysis(BaseAnalysis):
    name = "Power Spectral Density"
    category = "Frequency Domain"
    description = "Welch PSD estimate"

    def get_parameters(self) -> list:
        return [
            AnalysisParameter(
                "nperseg", "FFT Length", "int",
                default=1024, min_val=64, max_val=65536, step=256,
                tooltip="Number of samples per FFT segment",
            ),
            AnalysisParameter(
                "overlap_pct", "Overlap %", "float",
                default=50.0, min_val=0.0, max_val=95.0, step=5.0,
                tooltip="Percentage overlap between segments",
            ),
        ]

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        nperseg = int(params.get("nperseg", 1024))
        overlap_pct = float(params.get("overlap_pct", 50.0))
        noverlap = int(nperseg * overlap_pct / 100.0)

        x_data: Dict[str, np.ndarray] = {}
        y_data: Dict[str, np.ndarray] = {}

        for ch in channels:
            sig = signals[ch] - np.mean(signals[ch])
            actual_nperseg = min(nperseg, len(sig))
            actual_noverlap = min(noverlap, actual_nperseg - 1)
            freqs, psd = welch(sig, fs=fs, nperseg=actual_nperseg,
                               noverlap=actual_noverlap, scaling="density")
            x_data[ch] = freqs
            y_data[ch] = psd  # (m/s²)²/Hz

        y_quantity, _ = infer_quantity(channels)
        psd_quantity = f"psd_{y_quantity}"  # e.g. "psd_acceleration"

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Frequency", "frequency", "Hz",
                              log_scale_default=True),
            y_axis=AxisConfig("PSD", psd_quantity, "(m/s\u00b2)\u00b2/Hz",
                              log_scale_default=True),
            metadata={"nperseg": nperseg, "overlap_pct": overlap_pct, "fs": fs},
        )
