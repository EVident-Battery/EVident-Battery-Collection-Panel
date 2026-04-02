"""Cepstrum analyses — power cepstrum and cepstrogram."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from lib.analysis_registry import (
    AnalysisRegistry, AnalysisParameter, AxisConfig, AnalysisResult,
    BaseAnalysis,
)
from lib.analyses._transforms import apply_transform


@AnalysisRegistry.register
class PowerCepstrumAnalysis(BaseAnalysis):
    name = "Power Cepstrum"
    category = "Frequency Domain"
    description = "Detect beat frequencies and harmonic families via cepstral analysis"

    def get_parameters(self) -> list:
        return [
            AnalysisParameter(
                "max_quefrency", "Max Quefrency (s)", "float",
                default=0.05, min_val=0.001, max_val=10.0, step=0.005,
                tooltip="Upper quefrency limit in seconds",
            ),
        ]

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        max_q = float(params.get("max_quefrency", 0.05))

        x_data: Dict[str, np.ndarray] = {}
        y_data: Dict[str, np.ndarray] = {}

        for ch in channels:
            sig = signals[ch] - np.mean(signals[ch])
            n = len(sig)
            spectrum = np.fft.rfft(sig)
            log_power = np.log(np.maximum(np.abs(spectrum) ** 2, 1e-30))
            cepstrum = np.abs(np.fft.irfft(log_power, n=n))

            quefrency = np.arange(n) / fs
            # Skip DC bin and crop to max quefrency
            mask = (quefrency > 0) & (quefrency <= max_q)
            x_data[ch] = quefrency[mask]
            y_data[ch] = cepstrum[mask]

        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Quefrency", "time", "s"),
            y_axis=AxisConfig("Cepstral Magnitude", "dimensionless", ""),
            metadata={"max_quefrency": max_q, "fs": fs},
        )


@AnalysisRegistry.register
class CepstrogramAnalysis(BaseAnalysis):
    name = "Cepstrogram"
    category = "Time-Frequency"
    description = "Sliding-window cepstrum for time-varying beat/harmonic detection"

    def get_parameters(self) -> list:
        return [
            AnalysisParameter(
                "nfft", "NFFT", "int",
                default=1024, min_val=64, max_val=65536, step=256,
                tooltip="Number of FFT points per window",
            ),
            AnalysisParameter(
                "hop_pct", "Hop %", "float",
                default=50.0, min_val=5.0, max_val=95.0, step=5.0,
                tooltip="Hop size as percentage of NFFT",
            ),
            AnalysisParameter(
                "max_quefrency", "Max Quefrency (s)", "float",
                default=0.05, min_val=0.001, max_val=10.0, step=0.005,
                tooltip="Upper quefrency limit in seconds",
            ),
        ]

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        nfft = int(params.get("nfft", 1024))
        hop_pct = float(params.get("hop_pct", 50.0))
        max_q = float(params.get("max_quefrency", 0.05))

        ch = channels[0]
        sig = signals[ch] - np.mean(signals[ch])
        actual_nfft = min(nfft, len(sig))
        hop_size = max(1, int(actual_nfft * hop_pct / 100.0))

        if len(sig) < actual_nfft:
            raise ValueError("Signal too short for the chosen NFFT")

        window = np.hanning(actual_nfft)

        # Build quefrency axis and crop mask
        quefrency_full = np.arange(actual_nfft) / fs
        mask = (quefrency_full > 0) & (quefrency_full <= max_q)
        quefrency = quefrency_full[mask]

        n_frames = (len(sig) - actual_nfft) // hop_size + 1
        if n_frames < 1:
            raise ValueError("Signal too short for the chosen NFFT and hop size")

        cepstrogram = np.zeros((len(quefrency), n_frames))
        times = np.zeros(n_frames)

        for i in range(n_frames):
            start = i * hop_size
            segment = sig[start:start + actual_nfft] * window
            spectrum = np.fft.rfft(segment)
            log_power = np.log(np.maximum(np.abs(spectrum) ** 2, 1e-30))
            cepstrum = np.abs(np.fft.irfft(log_power, n=actual_nfft))
            cepstrogram[:, i] = cepstrum[mask]
            times[i] = (start + actual_nfft / 2) / fs

        return AnalysisResult(
            x_data={ch: times},
            y_data={},
            x_axis=AxisConfig("Time", "time", "s"),
            y_axis=AxisConfig("Quefrency", "time", "s"),
            metadata={"nfft": nfft, "hop_pct": hop_pct,
                      "max_quefrency": max_q, "fs": fs, "channel": ch},
            is_2d=True,
            z_data={ch: cepstrogram},
            z_axis=AxisConfig("Cepstral Magnitude", "dimensionless", ""),
            y_data_2d={ch: quefrency},
        )
