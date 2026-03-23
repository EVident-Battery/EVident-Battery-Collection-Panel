"""Shared signal-processing helpers: pre-analysis filters and post-analysis transforms."""
from __future__ import annotations

from typing import Dict

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, sosfiltfilt, hilbert


# ------------------------------------------------------------------
# Pre-analysis filtering
# ------------------------------------------------------------------

_BTYPE_MAP = {
    "High Pass": "highpass",
    "Low Pass": "lowpass",
    "Band Pass": "bandpass",
    "Band Stop": "bandstop",
}


def apply_filter(signals: Dict[str, np.ndarray], fs: float,
                 filter_type: str, freq: float, freq2: float,
                 order: int) -> Dict[str, np.ndarray]:
    """Apply a Butterworth filter to all channels. Returns a new dict."""
    if filter_type == "None" or filter_type not in _BTYPE_MAP:
        return signals

    btype = _BTYPE_MAP[filter_type]
    nyq = fs / 2.0

    # Build critical frequency argument
    if btype in ("bandpass", "bandstop"):
        lo, hi = sorted((freq, freq2))
        lo = max(lo, 0.1)
        hi = min(hi, nyq * 0.95)
        if lo >= hi:
            return signals
        Wn = [lo, hi]
    else:
        f = max(freq, 0.1)
        f = min(f, nyq * 0.95)
        Wn = f

    sos = butter(order, Wn, btype=btype, fs=fs, output="sos")
    return {ch: sosfiltfilt(sos, sig) for ch, sig in signals.items()}


# ------------------------------------------------------------------
# Post-analysis transforms
# ------------------------------------------------------------------

def apply_transform(y_data: Dict[str, np.ndarray],
                     transform: str,
                     smooth_window: int = 51) -> Dict[str, np.ndarray]:
    """Apply the selected transform to each channel's y_data."""
    if transform == "None" or not transform:
        return y_data
    if transform == "Hilbert Envelope":
        result = {}
        for ch, y in y_data.items():
            # Remove DC before Hilbert so the envelope tracks oscillation
            envelope = np.abs(hilbert(y - np.mean(y)))
            if smooth_window > 1:
                envelope = uniform_filter1d(envelope, size=smooth_window)
            result[ch] = envelope
        return result
    return y_data
