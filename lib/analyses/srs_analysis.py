"""Shock Response Spectrum — maxi-max via ramp-invariant recursive filter."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
from scipy.signal import lfilter

from lib.analysis_registry import (
    AnalysisRegistry, AnalysisParameter, AxisConfig, AnalysisResult,
    BaseAnalysis, infer_quantity,
)
from lib.analyses._transforms import apply_transform


@AnalysisRegistry.register
class SRSAnalysis(BaseAnalysis):
    name = "Shock Response Spectrum"
    category = "Frequency Domain"
    description = "Maxi-max SRS via ramp-invariant digital filter"

    def get_parameters(self) -> list:
        return [
            AnalysisParameter(
                "q_factor", "Q Factor", "float",
                default=10.0, min_val=1.0, max_val=100.0, step=1.0,
            ),
            AnalysisParameter(
                "n_freqs", "Frequency Points", "int",
                default=200, min_val=10, max_val=2000, step=10,
            ),
            AnalysisParameter(
                "f_min", "Min Freq (Hz)", "float",
                default=1.0, min_val=0.1, max_val=100.0, step=0.5,
            ),
        ]

    def compute(self, fs: float, signals: Dict[str, np.ndarray],
                channels: List[str], **params) -> AnalysisResult:
        Q = float(params.get("q_factor", 10.0))
        n_freqs = int(params.get("n_freqs", 200))
        f_min = float(params.get("f_min", 1.0))
        f_max = fs / 2.56

        if f_min >= f_max:
            f_min = 1.0
        fn_array = np.geomspace(f_min, f_max, num=n_freqs)

        x_data: Dict[str, np.ndarray] = {}
        y_data: Dict[str, np.ndarray] = {}
        for ch in channels:
            srs = _compute_srs(signals[ch], fs, fn_array, Q)
            x_data[ch] = fn_array
            y_data[ch] = srs

        y_data = apply_transform(y_data, params.get("transform", "None"),
                                 int(params.get("smooth_window", 51)))
        y_quantity, y_unit = infer_quantity(channels)

        return AnalysisResult(
            x_data=x_data,
            y_data=y_data,
            x_axis=AxisConfig("Natural Frequency", "frequency", "Hz",
                              log_scale_default=True),
            y_axis=AxisConfig("Peak Response", y_quantity, y_unit,
                              log_scale_default=True),
            metadata={"Q": Q, "n_freqs": n_freqs, "fs": fs},
        )


def _compute_srs(signal: np.ndarray, fs: float,
                 fn_array: np.ndarray, Q: float) -> np.ndarray:
    """Ramp-invariant recursive filter SRS (Smallwood, 1981)."""
    dt = 1.0 / fs
    zeta = 1.0 / (2.0 * Q)
    srs = np.zeros(len(fn_array))

    for i, fn in enumerate(fn_array):
        wn = 2.0 * np.pi * fn
        wd = wn * np.sqrt(1.0 - zeta ** 2)
        E = np.exp(-zeta * wn * dt)
        K = wd * dt
        C = E * np.cos(K)
        S = E * np.sin(K)

        b0 = 1.0 - S / K
        b1 = 2.0 * (S / K - C)
        b2 = E ** 2 - S / K
        a1 = -2.0 * C
        a2 = E ** 2

        b = np.array([b0, b1, b2])
        a = np.array([1.0, a1, a2])
        resp = lfilter(b, a, signal)
        srs[i] = np.max(np.abs(resp))

    return srs
