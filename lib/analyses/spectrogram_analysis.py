"""Spectrogram — STFT time-frequency representation."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
from scipy.signal import spectrogram as scipy_spectrogram

from lib.analysis_registry import (
    AnalysisRegistry, AnalysisParameter, AxisConfig, AnalysisResult,
    BaseAnalysis, infer_quantity,
)


@AnalysisRegistry.register
class SpectrogramAnalysis(BaseAnalysis):
    name = "Spectrogram"
    category = "Time-Frequency"
    description = "STFT time-frequency spectrogram"

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
        ]

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        nfft = int(params.get("nfft", 1024))
        hop_pct = float(params.get("hop_pct", 50.0))
        noverlap = int(nfft * (1.0 - hop_pct / 100.0))

        # Use only the first selected channel
        ch = channels[0]
        sig = signals[ch] - np.mean(signals[ch])
        actual_nfft = min(nfft, len(sig))
        actual_noverlap = min(noverlap, actual_nfft - 1)

        freqs, times, Sxx = scipy_spectrogram(
            sig, fs=fs, nperseg=actual_nfft,
            noverlap=actual_noverlap, scaling="density",
        )
        # Sxx shape: (n_freqs, n_times)

        y_quantity, _ = infer_quantity(channels)
        psd_quantity = f"psd_{y_quantity}"

        return AnalysisResult(
            x_data={ch: times},
            y_data={},
            x_axis=AxisConfig("Time", "time", "s"),
            y_axis=AxisConfig("Frequency", "frequency", "Hz"),
            metadata={"nfft": nfft, "hop_pct": hop_pct, "fs": fs,
                      "channel": ch},
            is_2d=True,
            z_data={ch: Sxx},
            z_axis=AxisConfig("PSD", psd_quantity, "(m/s\u00b2)\u00b2/Hz"),
            y_data_2d={ch: freqs},
        )
