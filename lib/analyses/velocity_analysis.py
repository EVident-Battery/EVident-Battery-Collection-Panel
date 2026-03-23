"""Velocity analyses — time-domain and frequency-domain via omega arithmetic."""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AnalysisParameter, AxisConfig, AnalysisResult,
    BaseAnalysis,
)


# ------------------------------------------------------------------
# Shared helper
# ------------------------------------------------------------------

def _velocity_spectrum(sig: np.ndarray, fs: float,
                       low_freq_cutoff: float,
                       remove_mean: bool) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(freqs, V_complex)`` — the velocity spectrum in freq domain.

    *V_complex* is the complex single-sided spectrum after integration and
    cosine tapering.  Callers can take ``np.fft.irfft`` for time domain or
    ``np.abs`` for magnitude spectrum.
    """
    n = len(sig)
    if remove_mean:
        sig = sig - np.mean(sig)

    A = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)

    # Integrate: divide by j·omega
    omega = 2.0 * np.pi * freqs
    V = np.zeros_like(A)
    idx = freqs > 0
    V[idx] = A[idx] / (1j * omega[idx])
    # DC bin stays zero

    # Cosine taper below cutoff to suppress low-frequency noise
    taper_mask = (freqs > 0) & (freqs < low_freq_cutoff)
    V[taper_mask] *= 0.5 * (1.0 - np.cos(np.pi * freqs[taper_mask]
                                           / low_freq_cutoff))

    return freqs, V


def _velocity_params() -> list:
    """Parameters shared by both velocity analyses."""
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


def _parse_params(params: dict, fs: float) -> Tuple[float, bool]:
    """Extract and clamp shared parameters."""
    low_freq_cutoff = float(params.get("low_freq_cutoff", 2.0))
    remove_mean = params.get("remove_mean", "Yes") == "Yes"
    low_freq_cutoff = min(low_freq_cutoff, fs / 2.0 * 0.9)
    return low_freq_cutoff, remove_mean


# ------------------------------------------------------------------
# Time Domain — velocity vs time
# ------------------------------------------------------------------

@AnalysisRegistry.register
class VelocityTimeDomainAnalysis(BaseAnalysis):
    name = "Velocity (FFT Integration)"
    category = "Time Domain"
    description = "Integrate acceleration to velocity via omega arithmetic"

    def get_parameters(self) -> list:
        return _velocity_params()

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        low_freq_cutoff, remove_mean = _parse_params(params, fs)

        x_data: Dict[str, np.ndarray] = {}
        y_data: Dict[str, np.ndarray] = {}

        for ch in channels:
            if ch.lower().startswith("gyro"):
                continue

            sig = signals[ch]
            n = len(sig)

            if n < 4 or not np.all(np.isfinite(sig)):
                x_data[ch] = np.arange(n) / fs
                y_data[ch] = np.zeros(n)
                continue

            _freqs, V = _velocity_spectrum(sig, fs, low_freq_cutoff, remove_mean)
            x_data[ch] = np.arange(n) / fs
            y_data[ch] = np.fft.irfft(V, n=n)

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Time", "time", "s", log_scale_default=False),
            y_axis=AxisConfig("Velocity", "velocity", "m/s",
                              log_scale_default=False),
            metadata={"low_freq_cutoff": low_freq_cutoff,
                      "remove_mean": remove_mean, "fs": fs},
        )


# ------------------------------------------------------------------
# Frequency Domain — velocity magnitude spectrum
# ------------------------------------------------------------------

@AnalysisRegistry.register
class VelocitySpectrumAnalysis(BaseAnalysis):
    name = "Velocity Spectrum"
    category = "Frequency Domain"
    description = "Single-sided velocity amplitude spectrum via FFT integration"

    def get_parameters(self) -> list:
        return _velocity_params()

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        low_freq_cutoff, remove_mean = _parse_params(params, fs)

        x_data: Dict[str, np.ndarray] = {}
        y_data: Dict[str, np.ndarray] = {}

        for ch in channels:
            if ch.lower().startswith("gyro"):
                continue

            sig = signals[ch]
            n = len(sig)

            if n < 4 or not np.all(np.isfinite(sig)):
                freqs = np.fft.rfftfreq(n, d=1.0 / fs)
                x_data[ch] = freqs
                y_data[ch] = np.zeros(len(freqs))
                continue

            freqs, V = _velocity_spectrum(sig, fs, low_freq_cutoff, remove_mean)

            # Single-sided amplitude scaling (same convention as FFT Magnitude)
            magnitude = np.abs(V) * (2.0 / n)
            magnitude[0] /= 2.0  # DC bin not doubled
            if n % 2 == 0:
                magnitude[-1] /= 2.0  # Nyquist bin not doubled

            x_data[ch] = freqs
            y_data[ch] = magnitude

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Frequency", "frequency", "Hz",
                              log_scale_default=False),
            y_axis=AxisConfig("Velocity", "velocity", "m/s",
                              log_scale_default=False),
            metadata={"low_freq_cutoff": low_freq_cutoff,
                      "remove_mean": remove_mean, "fs": fs},
        )
