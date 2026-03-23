"""Velocity (FFT Integration) — frequency-domain integration of acceleration."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AnalysisParameter, AxisConfig, AnalysisResult,
    BaseAnalysis,
)


@AnalysisRegistry.register
class VelocityAnalysis(BaseAnalysis):
    name = "Velocity (FFT Integration)"
    category = "Derived Quantities"
    description = "Integrate acceleration to velocity via omega arithmetic"

    def get_parameters(self) -> list:
        return [
            AnalysisParameter(
                "low_freq_cutoff", "Low-Freq Cutoff (Hz)", "float",
                default=2.0, min_val=0.1, max_val=100.0, step=0.5,
                tooltip="Frequencies below this are tapered to suppress drift",
            ),
            AnalysisParameter(
                "remove_mean", "Remove DC Offset", "choice",
                default="Yes", choices=["Yes", "No"],
                tooltip="Subtract mean from acceleration before integration",
            ),
        ]

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        low_freq_cutoff = float(params.get("low_freq_cutoff", 2.0))
        remove_mean = params.get("remove_mean", "Yes") == "Yes"

        # Clamp cutoff to avoid tapering the entire spectrum
        nyquist = fs / 2.0
        low_freq_cutoff = min(low_freq_cutoff, nyquist * 0.9)

        x_data: Dict[str, np.ndarray] = {}
        y_data: Dict[str, np.ndarray] = {}

        for ch in channels:
            # Skip gyro channels — integrating angular velocity ≠ linear velocity
            if ch.lower().startswith("gyro"):
                continue

            sig = signals[ch].copy()
            n = len(sig)

            # Guard against very short or invalid signals
            if n < 4 or not np.all(np.isfinite(sig)):
                t = np.arange(n) / fs
                x_data[ch] = t
                y_data[ch] = np.zeros(n)
                continue

            if remove_mean:
                sig -= np.mean(sig)

            # Forward FFT (real-valued)
            A = np.fft.rfft(sig)
            freqs = np.fft.rfftfreq(n, d=1.0 / fs)

            # Frequency-domain integration: divide by j·omega
            omega = 2.0 * np.pi * freqs
            V = np.zeros_like(A)
            idx = freqs > 0
            V[idx] = A[idx] / (1j * omega[idx])
            # DC bin stays zero (no constant of integration)

            # Cosine taper below cutoff to suppress low-frequency noise
            taper_mask = (freqs > 0) & (freqs < low_freq_cutoff)
            V[taper_mask] *= 0.5 * (1.0 - np.cos(np.pi * freqs[taper_mask]
                                                   / low_freq_cutoff))

            # Back to time domain
            v = np.fft.irfft(V, n=n)
            t = np.arange(n) / fs

            x_data[ch] = t
            y_data[ch] = v  # m/s (base velocity unit)

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Time", "time", "s", log_scale_default=False),
            y_axis=AxisConfig("Velocity", "velocity", "m/s",
                              log_scale_default=False),
            metadata={"low_freq_cutoff": low_freq_cutoff,
                      "remove_mean": remove_mean, "fs": fs},
        )
