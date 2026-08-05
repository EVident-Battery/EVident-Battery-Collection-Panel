"""Velocity and displacement analyses — time/frequency domain via omega arithmetic."""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AnalysisParameter, AxisConfig, AnalysisResult,
    BaseAnalysis,
)
from lib.analyses._transforms import apply_transform


# ------------------------------------------------------------------
# Shared helper
# ------------------------------------------------------------------

def _integrated_spectrum(sig: np.ndarray, fs: float,
                         low_freq_cutoff: float,
                         remove_mean: bool,
                         order: int = 1) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(freqs, V_complex)`` — acceleration integrated *order* times.

    ``order=1`` gives velocity, ``order=2`` displacement.  *V_complex* is the
    complex single-sided spectrum after integration and cosine tapering.
    Callers can take ``np.fft.irfft`` for time domain or ``np.abs`` for
    magnitude spectrum.  The DC bin is zeroed, so the time-domain result is
    always mean-zero (relative motion, not absolute position).
    """
    n = len(sig)
    if remove_mean:
        sig = sig - np.mean(sig)

    A = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)

    # Integrate: divide by (j·omega)^order
    omega = 2.0 * np.pi * freqs
    V = np.zeros_like(A)
    idx = freqs > 0
    V[idx] = A[idx] / (1j * omega[idx]) ** order
    # DC bin stays zero

    # Cosine taper below cutoff to suppress low-frequency noise; raised to
    # *order* since noise gain grows as 1/omega^order
    taper_mask = (freqs > 0) & (freqs < low_freq_cutoff)
    V[taper_mask] *= (0.5 * (1.0 - np.cos(np.pi * freqs[taper_mask]
                                            / low_freq_cutoff))) ** order

    return freqs, V


def _integration_params(default_cutoff: float) -> list:
    """Parameters shared by the velocity and displacement analyses."""
    return [
        AnalysisParameter(
            "low_freq_cutoff", "Low-Freq Cutoff (Hz)", "float",
            default=default_cutoff, min_val=0.1, max_val=100.0, step=0.5,
            tooltip="Frequencies below this are tapered to suppress drift",
        ),
        AnalysisParameter(
            "remove_mean", "Remove DC Offset", "choice",
            default="Yes", choices=["Yes", "No"],
            tooltip="Subtract mean from acceleration before integration",
        ),
    ]


def _parse_params(params: dict, fs: float,
                  default_cutoff: float) -> Tuple[float, bool]:
    """Extract and clamp shared parameters."""
    low_freq_cutoff = float(params.get("low_freq_cutoff", default_cutoff))
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
        return _integration_params(default_cutoff=2.0)

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        low_freq_cutoff, remove_mean = _parse_params(params, fs,
                                                     default_cutoff=2.0)

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

            _freqs, V = _integrated_spectrum(sig, fs, low_freq_cutoff,
                                             remove_mean)
            x_data[ch] = np.arange(n) / fs
            y_data[ch] = np.fft.irfft(V, n=n)

        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))
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
# Time Domain — displacement vs time
# ------------------------------------------------------------------

@AnalysisRegistry.register
class DisplacementTimeDomainAnalysis(BaseAnalysis):
    name = "Displacement (FFT Integration)"
    category = "Time Domain"
    description = "Double-integrate acceleration to displacement via omega arithmetic"

    def get_parameters(self) -> list:
        return _integration_params(default_cutoff=5.0)

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        low_freq_cutoff, remove_mean = _parse_params(params, fs,
                                                     default_cutoff=5.0)

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

            _freqs, D = _integrated_spectrum(sig, fs, low_freq_cutoff,
                                             remove_mean, order=2)
            disp = np.fft.irfft(D, n=n) * 1e3  # m -> mm

            # Double integration is exact mid-record but the FFT's circular
            # wrap-around corrupts ~2/cutoff seconds at each edge (verified
            # up to ~7x the true amplitude).  Crop that margin, capped at
            # 10% of the record per side, and re-center to mean zero.
            margin = min(int(2.0 / low_freq_cutoff * fs), n // 10)
            disp = disp[margin:n - margin]
            disp = disp - np.mean(disp)
            x_data[ch] = np.arange(margin, n - margin) / fs
            y_data[ch] = disp

        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))
        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Time", "time", "s", log_scale_default=False),
            y_axis=AxisConfig("Displacement", "displacement", "mm",
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
        return _integration_params(default_cutoff=2.0)

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        low_freq_cutoff, remove_mean = _parse_params(params, fs,
                                                     default_cutoff=2.0)

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

            freqs, V = _integrated_spectrum(sig, fs, low_freq_cutoff,
                                            remove_mean)

            # Single-sided amplitude scaling (same convention as FFT Magnitude)
            magnitude = np.abs(V) * (2.0 / n)
            magnitude[0] /= 2.0  # DC bin not doubled
            if n % 2 == 0:
                magnitude[-1] /= 2.0  # Nyquist bin not doubled

            x_data[ch] = freqs
            y_data[ch] = magnitude

        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))
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


# ------------------------------------------------------------------
# Frequency Domain — displacement magnitude spectrum
# ------------------------------------------------------------------

@AnalysisRegistry.register
class DisplacementSpectrumAnalysis(BaseAnalysis):
    name = "Displacement Spectrum"
    category = "Frequency Domain"
    description = "Single-sided displacement amplitude spectrum via double FFT integration"

    def get_parameters(self) -> list:
        return _integration_params(default_cutoff=5.0)

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        low_freq_cutoff, remove_mean = _parse_params(params, fs,
                                                     default_cutoff=5.0)

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

            freqs, D = _integrated_spectrum(sig, fs, low_freq_cutoff,
                                            remove_mean, order=2)

            # Single-sided amplitude scaling (same convention as FFT Magnitude)
            magnitude = np.abs(D) * (2.0 / n) * 1e3  # m -> mm
            magnitude[0] /= 2.0  # DC bin not doubled
            if n % 2 == 0:
                magnitude[-1] /= 2.0  # Nyquist bin not doubled

            x_data[ch] = freqs
            y_data[ch] = magnitude

        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))
        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Frequency", "frequency", "Hz",
                              log_scale_default=False),
            y_axis=AxisConfig("Displacement", "displacement", "mm",
                              log_scale_default=False),
            metadata={"low_freq_cutoff": low_freq_cutoff,
                      "remove_mean": remove_mean, "fs": fs},
        )
