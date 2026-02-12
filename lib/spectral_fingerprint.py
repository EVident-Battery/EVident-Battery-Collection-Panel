"""
Spectral Fingerprint Toolkit

Two-tier spectral anomaly detection for accelerometer data.

Folder structure:
    project_dir/
        baseline/       Known-good recordings (CSVs, any length)
        monitor/        New recordings to check against baseline
        config.json     Created by `init`, stores analyzer settings
        baseline.json   Created by `train`, stores learned fingerprint
        results/        Created by `check --plots`, comparison plots

Workflow:
    1. python spectral_fingerprint.py init   project_dir --fs 1844.3
    2. (sensor drops CSVs into project_dir/baseline/)
    3. python spectral_fingerprint.py train  project_dir
    4. (sensor drops CSVs into project_dir/monitor/)
    5. python spectral_fingerprint.py check  project_dir [--plots]

Standalone plotting:
    python spectral_fingerprint.py plot  file.csv [--fs 1844.3]

Library usage:
    from spectral_fingerprint import SpectralAnalyzer, SpectralBaseline
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from scipy.signal import welch, find_peaks
from scipy.ndimage import median_filter
from scipy.stats import chi2


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SpectralFrame:
    """One PSD snapshot per axis."""
    freqs: np.ndarray
    psd_db: dict[str, np.ndarray]
    noise_floor_db: dict[str, np.ndarray]
    prominence_db: dict[str, np.ndarray]
    peaks: dict[str, np.ndarray]
    valleys: dict[str, np.ndarray]


@dataclass
class DetectionResult:
    """Result of comparing a frame against a learned baseline."""
    T: dict[str, float]
    T_threshold: dict[str, float]
    T_triggered: dict[str, bool]

    M: dict[str, float]
    M_threshold: dict[str, float]
    M_triggered: dict[str, bool]

    z_scores: dict[str, np.ndarray]
    prominence_z: dict[str, np.ndarray]
    triggered: dict[str, bool]
    freqs: np.ndarray


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

class SpectralAnalyzer:
    """
    Computes PSD, noise floor, and prominence for multi-axis data.

    Parameters
    ----------
    fs : float
        Sample rate in Hz.
    nperseg : int
        FFT length. Bin width = fs / nperseg.
    noverlap : int or None
        Welch segment overlap. Default: nperseg // 2.
    median_window : int
        Width of median filter for noise floor estimation (in bins).
    """

    def __init__(self, fs: float, nperseg: int = 4096, noverlap: int = None,
                 median_window: int = 51):
        self.fs = fs
        self.nperseg = nperseg
        self.noverlap = noverlap or nperseg // 2
        self.median_window = median_window

    @property
    def bin_width(self) -> float:
        return self.fs / self.nperseg

    def compute_psd(self, signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Compute Welch PSD in dB for a single 1D signal."""
        signal = signal - np.mean(signal)
        actual_nperseg = min(self.nperseg, len(signal))
        actual_noverlap = min(self.noverlap, actual_nperseg - 1)
        freqs, psd = welch(
            signal, fs=self.fs,
            nperseg=actual_nperseg,
            noverlap=actual_noverlap,
            scaling='density'
        )
        psd_db = 10.0 * np.log10(psd + 1e-12)
        return freqs, psd_db

    def compute_prominence(self, psd_db: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Returns (noise_floor_db, prominence_db)."""
        noise_floor = median_filter(psd_db, size=self.median_window)
        prominence = psd_db - noise_floor
        return noise_floor, prominence

    def find_features(self, prominence_db: np.ndarray,
                      height: float = 3.0, distance: int = 5
                      ) -> tuple[np.ndarray, np.ndarray]:
        """Find peaks and valleys in the prominence curve."""
        peaks, _ = find_peaks(prominence_db, height=height, distance=distance)
        valleys, _ = find_peaks(-prominence_db, height=height, distance=distance)
        return peaks, valleys

    def analyze_frame(self, signals: dict[str, np.ndarray],
                      peak_height: float = 3.0,
                      peak_distance: int = 5) -> SpectralFrame:
        """Full spectral analysis of a multi-axis frame."""
        freqs = None
        psd_db, noise_floor_db, prominence_db = {}, {}, {}
        peaks, valleys = {}, {}

        for name, signal in signals.items():
            f, p = self.compute_psd(signal)
            if freqs is None:
                freqs = f
            nf, prom = self.compute_prominence(p)
            pk, vl = self.find_features(prom, height=peak_height, distance=peak_distance)

            psd_db[name] = p
            noise_floor_db[name] = nf
            prominence_db[name] = prom
            peaks[name] = pk
            valleys[name] = vl

        return SpectralFrame(
            freqs=freqs, psd_db=psd_db, noise_floor_db=noise_floor_db,
            prominence_db=prominence_db, peaks=peaks, valleys=valleys,
        )

    def to_dict(self) -> dict:
        return {
            'fs': self.fs, 'nperseg': self.nperseg,
            'noverlap': self.noverlap, 'median_window': self.median_window,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'SpectralAnalyzer':
        return cls(fs=d['fs'], nperseg=d['nperseg'],
                   noverlap=d['noverlap'], median_window=d['median_window'])


# ---------------------------------------------------------------------------
# Baseline learning and detection
# ---------------------------------------------------------------------------

class SpectralBaseline:
    """
    Learns a spectral fingerprint from known-good data and detects anomalies.

    Two-tier detection:
      T (global):  sum of squared z-scores — catches distributed changes
      M (max):     max prominence z-score — catches individual features
    """

    def __init__(self, analyzer: SpectralAnalyzer, p_fa: float = 0.01):
        self.analyzer = analyzer
        self.p_fa = p_fa

        # Phase 1 accumulators
        self._phase1_frames: dict[str, list[np.ndarray]] = {}
        self._n_phase1: int = 0

        # Learned baseline
        self.center: dict[str, np.ndarray] = {}
        self.scale: dict[str, np.ndarray] = {}
        self.freqs: Optional[np.ndarray] = None

        # Phase 2 accumulators
        self._T_values: dict[str, list[float]] = {}
        self._M_values: dict[str, list[float]] = {}
        self._n_phase2: int = 0

        # Thresholds
        self.T_threshold: dict[str, float] = {}
        self.M_threshold: dict[str, float] = {}
        self.T_nu_eff: dict[str, float] = {}
        self.T_c_eff: dict[str, float] = {}

        self._phase1_frozen = False
        self._calibrated = False

    @property
    def is_trained(self) -> bool:
        return self._phase1_frozen

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    @property
    def n_bins(self) -> int:
        return len(self.freqs) if self.freqs is not None else 0

    # --- Phase 1 ---

    def accumulate_phase1(self, signals: dict[str, np.ndarray]):
        """Feed one frame of known-good data for Phase 1."""
        if self._phase1_frozen:
            raise RuntimeError("Baseline frozen. Use accumulate_phase2().")
        for name, signal in signals.items():
            freqs, psd_db = self.analyzer.compute_psd(signal)
            if self.freqs is None:
                self.freqs = freqs
            if name not in self._phase1_frames:
                self._phase1_frames[name] = []
            self._phase1_frames[name].append(psd_db.copy())
        self._n_phase1 += 1

    def freeze_baseline(self):
        """Compute per-bin median and MAD from Phase 1 data."""
        if self._n_phase1 < 2:
            raise ValueError(f"Need >= 2 Phase 1 frames (have {self._n_phase1})")
        for name, frames in self._phase1_frames.items():
            X = np.array(frames)
            med = np.median(X, axis=0)
            mad = np.median(np.abs(X - med), axis=0)
            self.center[name] = med
            self.scale[name] = 1.4826 * (mad + 1e-6)
        self._phase1_frozen = True
        self._phase1_frames = {}

    # --- Phase 2 ---

    def _compute_z_scores(self, signals: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        z = {}
        for name, signal in signals.items():
            _, psd_db = self.analyzer.compute_psd(signal)
            z[name] = (psd_db - self.center[name]) / self.scale[name]
        return z

    def _compute_prominence_z(self, z_scores: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        pz = {}
        for name, z in z_scores.items():
            floor = median_filter(z, size=self.analyzer.median_window)
            pz[name] = z - floor
        return pz

    def accumulate_phase2(self, signals: dict[str, np.ndarray]):
        """Feed one frame of known-good data for Phase 2 (threshold calibration)."""
        if not self._phase1_frozen:
            raise RuntimeError("Must freeze_baseline() first.")
        z = self._compute_z_scores(signals)
        pz = self._compute_prominence_z(z)
        for name in z:
            if name not in self._T_values:
                self._T_values[name] = []
                self._M_values[name] = []
            self._T_values[name].append(float(np.sum(z[name] ** 2)))
            self._M_values[name].append(float(np.max(np.abs(pz[name]))))
        self._n_phase2 += 1

    def calibrate(self):
        """Set thresholds from Phase 2 data. Budget: p_fa/2 per tier."""
        q = 1.0 - self.p_fa / 2.0
        for name in self._T_values:
            Ts = np.array(self._T_values[name])
            Ms = np.array(self._M_values[name])
            if len(Ts) < 2:
                raise ValueError(f"Need >= 2 Phase 2 frames for {name}")
            self.T_threshold[name] = float(np.percentile(Ts, 100 * q))
            self.M_threshold[name] = float(np.percentile(Ms, 100 * q))
            mu, var = Ts.mean(), Ts.var(ddof=1)
            self.T_nu_eff[name] = float(2.0 * mu**2 / (var + 1e-30))
            self.T_c_eff[name] = float((var + 1e-30) / (2.0 * mu + 1e-30))
        self._calibrated = True
        self._T_values = {}
        self._M_values = {}

    # --- Detection ---

    def detect(self, signals: dict[str, np.ndarray]) -> DetectionResult:
        """Compare a new frame against the learned baseline."""
        if not self._calibrated:
            raise RuntimeError("Not calibrated yet.")
        # Validate signal length
        for name, sig in signals.items():
            if len(sig) < self.analyzer.nperseg:
                raise ValueError(
                    f"{name}: signal length {len(sig)} < nperseg {self.analyzer.nperseg}. "
                    f"File too short for this baseline."
                )
        z = self._compute_z_scores(signals)
        pz = self._compute_prominence_z(z)
        T, Tt, M, Mt, trig = {}, {}, {}, {}, {}
        for name in z:
            T[name] = float(np.sum(z[name] ** 2))
            M[name] = float(np.max(np.abs(pz[name])))
            Tt[name] = T[name] > self.T_threshold[name]
            Mt[name] = M[name] > self.M_threshold[name]
            trig[name] = Tt[name] or Mt[name]
        return DetectionResult(
            T=T, T_threshold=dict(self.T_threshold), T_triggered=Tt,
            M=M, M_threshold=dict(self.M_threshold), M_triggered=Mt,
            z_scores=z, prominence_z=pz, triggered=trig, freqs=self.freqs,
        )

    # --- Serialization ---

    def save(self, path: str):
        data = {
            'analyzer': self.analyzer.to_dict(),
            'p_fa': self.p_fa,
            'n_phase1_frames': self._n_phase1,
            'n_phase2_frames': self._n_phase2,
            'phase1_frozen': self._phase1_frozen,
            'calibrated': self._calibrated,
            'freqs': self.freqs.tolist() if self.freqs is not None else None,
            'axes': {},
        }
        for name in self.center:
            entry = {
                'center': self.center[name].tolist(),
                'scale': self.scale[name].tolist(),
            }
            if name in self.T_threshold:
                entry.update({
                    'T_threshold': self.T_threshold[name],
                    'M_threshold': self.M_threshold[name],
                    'T_nu_eff': self.T_nu_eff.get(name),
                    'T_c_eff': self.T_c_eff.get(name),
                })
            data['axes'][name] = entry
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> 'SpectralBaseline':
        with open(path) as f:
            data = json.load(f)
        analyzer = SpectralAnalyzer.from_dict(data['analyzer'])
        bl = cls(analyzer=analyzer, p_fa=data['p_fa'])
        bl._n_phase1 = data['n_phase1_frames']
        bl._n_phase2 = data.get('n_phase2_frames', 0)
        bl.freqs = np.array(data['freqs']) if data['freqs'] else None
        bl._phase1_frozen = data['phase1_frozen']
        bl._calibrated = data['calibrated']
        for name, entry in data['axes'].items():
            bl.center[name] = np.array(entry['center'])
            bl.scale[name] = np.array(entry['scale'])
            if 'T_threshold' in entry:
                bl.T_threshold[name] = entry['T_threshold']
                bl.M_threshold[name] = entry['M_threshold']
                bl.T_nu_eff[name] = entry.get('T_nu_eff')
                bl.T_c_eff[name] = entry.get('T_c_eff')
        return bl


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_csv(path: str, timestamp_col: str = None,
             axis_cols: list[str] = None) -> tuple[float, dict[str, np.ndarray]]:
    """Load accelerometer CSV and infer sample rate. Returns (fs, signals)."""
    import pandas as pd
    df = pd.read_csv(path)

    # Auto-detect timestamp column
    if timestamp_col is None:
        candidates = ['Timestamp', 'Time', 'timestamp', 'time', 'time_us', 'time_ms', 't']
        for c in candidates:
            if c in df.columns:
                timestamp_col = c
                break
        if timestamp_col is None:
            # Fall back to first column if it looks numeric
            if df.iloc[:, 0].dtype in [np.float64, np.int64, float, int]:
                timestamp_col = df.columns[0]
            else:
                raise ValueError(
                    f"No timestamp column found. Columns: {list(df.columns)}. "
                    f"Pass --timestamp-col explicitly."
                )

    if timestamp_col not in df.columns:
        raise ValueError(f"Column '{timestamp_col}' not found. Available: {list(df.columns)}")

    dt = np.median(np.diff(df[timestamp_col].values))
    fs = 1e6 / dt if dt > 100 else 1.0 / dt
    if axis_cols is None:
        axis_cols = [c for c in df.columns if c != timestamp_col]
    signals = {col: df[col].values.astype(np.float64) for col in axis_cols}
    return fs, signals


def load_folder(folder: str, timestamp_col: str = None,
                axis_cols: list[str] = None
                ) -> list[tuple[str, float, dict[str, np.ndarray]]]:
    """Load all CSVs in a folder. Returns list of (filename, fs, signals)."""
    folder = Path(folder)
    csvs = sorted(folder.glob('*.csv'))
    if not csvs:
        raise FileNotFoundError(f"No CSV files in {folder}")
    results = []
    for p in csvs:
        try:
            fs, signals = load_csv(str(p), timestamp_col, axis_cols)
            results.append((p.name, fs, signals))
        except Exception as e:
            print(f"  Warning: skipping {p.name}: {e}")
    return results


def extract_frames(signals: dict[str, np.ndarray], nperseg: int,
                   hop: int = None) -> list[dict[str, np.ndarray]]:
    """
    Extract overlapping frames from one recording.
    Each frame is nperseg samples long. Hop defaults to nperseg // 4.
    """
    first_key = next(iter(signals))
    total_len = len(signals[first_key])
    hop = hop or nperseg // 4
    frames = []
    start = 0
    while start + nperseg <= total_len:
        chunk = {name: sig[start:start + nperseg] for name, sig in signals.items()}
        frames.append(chunk)
        start += hop
    return frames


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_spectral_frame(frame: SpectralFrame, title: str = '',
                        save_path: str = None, show: bool = False):
    """Plot 3 rows: linear-x/dB, log-x/dB, prominence."""
    import matplotlib.pyplot as plt

    axes_names = list(frame.psd_db.keys())
    n_axes = len(axes_names)
    colors = ['#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12', '#1abc9c']

    fig, axs = plt.subplots(3, n_axes, figsize=(7 * n_axes, 14))
    if n_axes == 1:
        axs = axs[:, np.newaxis]
    if title:
        fig.suptitle(title, fontsize=16, y=0.98)

    for i, name in enumerate(axes_names):
        color = colors[i % len(colors)]
        freqs, psd = frame.freqs, frame.psd_db[name]
        floor, prom = frame.noise_floor_db[name], frame.prominence_db[name]
        pks, vls = frame.peaks[name], frame.valleys[name]
        mask = freqs > 0.1

        # Linear freq, dB
        ax = axs[0, i]
        ax.plot(freqs, psd, color=color, alpha=0.7, lw=0.5)
        ax.plot(freqs, floor, 'k--', alpha=0.4, lw=1, label='Noise floor')
        if len(pks): ax.plot(freqs[pks], psd[pks], 'rv', ms=5, label=f'{len(pks)} peaks')
        if len(vls): ax.plot(freqs[vls], psd[vls], 'b^', ms=5, label=f'{len(vls)} dips')
        ax.set_title(f'{name} — Linear freq, dB')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('PSD (dB)')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3)

        # Log freq, dB
        ax = axs[1, i]
        ax.semilogx(freqs[mask], psd[mask], color=color, alpha=0.7, lw=0.5)
        ax.semilogx(freqs[mask], floor[mask], 'k--', alpha=0.4, lw=1)
        if len(pks):
            pm = freqs[pks] > 0.1
            ax.semilogx(freqs[pks[pm]], psd[pks[pm]], 'rv', ms=5)
        if len(vls):
            vm = freqs[vls] > 0.1
            ax.semilogx(freqs[vls[vm]], psd[vls[vm]], 'b^', ms=5)
        ax.set_title(f'{name} — Log freq, dB')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('PSD (dB)')
        ax.grid(True, alpha=0.3, which='both')

        # Prominence
        ax = axs[2, i]
        ax.semilogx(freqs[mask], prom[mask], color=color, alpha=0.7, lw=0.5)
        ax.axhline(0, color='k', ls='-', alpha=0.2)
        if len(pks):
            pm = freqs[pks] > 0.1
            ax.semilogx(freqs[pks[pm]], prom[pks[pm]], 'rv', ms=6)
            top = pks[pm][np.argsort(prom[pks[pm]])[::-1][:5]]
            for p in top:
                ax.annotate(f'{freqs[p]:.1f} Hz\n+{prom[p]:.1f} dB',
                           (freqs[p], prom[p]), fontsize=6,
                           textcoords='offset points', xytext=(5, 5))
        if len(vls):
            vm = freqs[vls] > 0.1
            ax.semilogx(freqs[vls[vm]], prom[vls[vm]], 'b^', ms=5)
        ax.set_title(f'{name} — Prominence')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Prominence (dB)')
        ax.grid(True, alpha=0.3, which='both')

    plt.tight_layout()
    if save_path: plt.savefig(save_path, dpi=150, bbox_inches='tight')
    if show: plt.show()
    plt.close(fig)
    return fig


def plot_comparison(baseline: SpectralBaseline, result: DetectionResult,
                    frame: SpectralFrame, title: str = '',
                    save_path: str = None, show: bool = False):
    """Plot new data vs baseline: PSD overlay, z-scores, prominence z, summary."""
    import matplotlib.pyplot as plt

    axes_names = list(result.z_scores.keys())
    n_axes = len(axes_names)
    colors = ['#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12', '#1abc9c']

    fig, axs = plt.subplots(4, n_axes, figsize=(7 * n_axes, 18))
    if n_axes == 1:
        axs = axs[:, np.newaxis]
    if title:
        fig.suptitle(title, fontsize=16, y=0.99)

    freqs = result.freqs
    mask = freqs > 0.1

    for i, name in enumerate(axes_names):
        color = colors[i % len(colors)]
        z, pz, psd = result.z_scores[name], result.prominence_z[name], frame.psd_db[name]

        # PSD vs baseline
        ax = axs[0, i]
        ax.semilogx(freqs[mask], psd[mask], color=color, alpha=0.8, lw=1, label='New data')
        ax.semilogx(freqs[mask], baseline.center[name][mask], 'k-', alpha=0.5, lw=1, label='Baseline')
        ax.fill_between(freqs[mask],
            (baseline.center[name] - 2*baseline.scale[name])[mask],
            (baseline.center[name] + 2*baseline.scale[name])[mask],
            alpha=0.15, color='gray', label='±2σ')
        ax.set_title(f'{name} — New vs Baseline')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('PSD (dB)')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # Z-scores
        ax = axs[1, i]
        ax.semilogx(freqs[mask], z[mask], color=color, alpha=0.6, lw=0.5)
        ax.axhline(0, color='k', alpha=0.3)
        ax.axhline(3, color='r', ls='--', alpha=0.3, label='+3σ')
        ax.axhline(-3, color='b', ls='--', alpha=0.3, label='-3σ')
        ts = "⚠ TRIGGERED" if result.T_triggered[name] else ""
        ax.set_title(f'{name} — Z-scores  |  T={result.T[name]:.0f} (thresh={result.T_threshold[name]:.0f}) {ts}')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Z-score')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # Prominence z
        ax = axs[2, i]
        ax.semilogx(freqs[mask], pz[mask], color=color, alpha=0.6, lw=0.5)
        ax.axhline(0, color='k', alpha=0.3)
        mt = result.M_threshold[name]
        ax.axhline(mt, color='r', ls='--', alpha=0.5, label=f'M thresh ({mt:.1f})')
        ax.axhline(-mt, color='b', ls='--', alpha=0.5)
        max_idx = np.argmax(np.abs(pz))
        if freqs[max_idx] > 0.1:
            ax.annotate(f'{freqs[max_idx]:.1f} Hz\nM={np.abs(pz[max_idx]):.1f}',
                       (freqs[max_idx], pz[max_idx]), fontsize=7, color='red',
                       textcoords='offset points', xytext=(5, 5))
        ms = "⚠ TRIGGERED" if result.M_triggered[name] else ""
        ax.set_title(f'{name} — Prominence Z  |  M={result.M[name]:.1f} (thresh={mt:.1f}) {ms}')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Prominence Z-score')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # Summary
        ax = axs[3, i]
        ax.axis('off')
        status = "⚠  ANOMALY" if result.triggered[name] else "✓  Normal"
        sc = '#e74c3c' if result.triggered[name] else '#27ae60'
        lines = [
            f"{'─'*40}", f"  {name}: {status}", f"{'─'*40}",
            f"  Tier 1 (Global): T={result.T[name]:.1f} / {result.T_threshold[name]:.1f}  "
            f"{'TRIGGERED' if result.T_triggered[name] else 'ok'}",
            f"  Tier 2 (Peaks):  M={result.M[name]:.1f} / {result.M_threshold[name]:.1f}  "
            f"{'TRIGGERED' if result.M_triggered[name] else 'ok'}",
        ]
        if result.triggered[name]:
            top_z = np.argsort(np.abs(z))[::-1][:5]
            lines += ["", "  Top deviations:"]
            for idx in top_z:
                lines.append(f"    {freqs[idx]:8.1f} Hz  z={z[idx]:+.1f}")
        ax.text(0.05, 0.95, '\n'.join(lines), transform=ax.transAxes,
               fontfamily='monospace', fontsize=9, va='top', color=sc,
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))

    plt.tight_layout()
    if save_path: plt.savefig(save_path, dpi=150, bbox_inches='tight')
    if show: plt.show()
    plt.close(fig)
    return fig


def plot_baseline(baseline: SpectralBaseline, title: str = 'Learned Baseline',
                  save_path: str = None, show: bool = False):
    """
    Visualize what the baseline learned.

    3 rows per axis:
      Row 0: The learned spectral envelope (center ± 1σ, 2σ, 3σ)
      Row 1: The per-bin scale (how much each bin jitters — narrower = more confident)
      Row 2: The learned noise floor and what prominence the system expects
    """
    import matplotlib.pyplot as plt

    axes_names = list(baseline.center.keys())
    n_axes = len(axes_names)
    colors = ['#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12', '#1abc9c']
    freqs = baseline.freqs
    mask = freqs > 0.1

    fig, axs = plt.subplots(3, n_axes, figsize=(7 * n_axes, 16))
    if n_axes == 1:
        axs = axs[:, np.newaxis]
    fig.suptitle(title, fontsize=16, y=0.99)

    for i, name in enumerate(axes_names):
        color = colors[i % len(colors)]
        center = baseline.center[name]
        scale = baseline.scale[name]

        # Compute noise floor and prominence of the baseline itself
        nf = median_filter(center, size=baseline.analyzer.median_window)
        prom = center - nf

        # Row 0: The learned envelope (log-x)
        ax = axs[0, i]
        ax.semilogx(freqs[mask], center[mask], color=color, lw=1.5, label='Center (median)')
        for sigma, alpha in [(1, 0.25), (2, 0.15), (3, 0.08)]:
            ax.fill_between(freqs[mask],
                           (center - sigma * scale)[mask],
                           (center + sigma * scale)[mask],
                           alpha=alpha, color=color, label=f'±{sigma}σ')
        ax.set_title(f'{name} — Learned Envelope')
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('PSD (dB)')
        ax.legend(fontsize=7, loc='upper right')
        ax.grid(True, alpha=0.3, which='both')

        # Threshold annotation
        if name in baseline.T_threshold:
            nu = baseline.T_nu_eff.get(name, 0)
            ax.text(0.02, 0.02,
                   f'T thresh: {baseline.T_threshold[name]:.0f}  |  '
                   f'M thresh: {baseline.M_threshold[name]:.1f}  |  '
                   f'Eff DOF: {nu:.0f}/{baseline.n_bins}  |  '
                   f'p_fa: {baseline.p_fa}',
                   transform=ax.transAxes, fontsize=7, fontfamily='monospace',
                   bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        # Row 1: Per-bin scale (how confident we are at each frequency)
        ax = axs[1, i]
        ax.semilogx(freqs[mask], scale[mask], color=color, lw=0.8, alpha=0.8)

        # Highlight regions of high/low confidence
        median_scale = np.median(scale[mask])
        ax.axhline(median_scale, color='k', ls='--', alpha=0.3,
                   label=f'Median scale: {median_scale:.2f} dB')
        ax.fill_between(freqs[mask], 0, scale[mask],
                       where=scale[mask] < median_scale,
                       alpha=0.2, color='green', label='High confidence')
        ax.fill_between(freqs[mask], 0, scale[mask],
                       where=scale[mask] > median_scale * 2,
                       alpha=0.2, color='red', label='Low confidence')

        ax.set_title(f'{name} — Per-Bin Scale (jitter width)')
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Scale (dB)')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3, which='both')
        ax.set_ylim(bottom=0)

        # Row 2: Baseline prominence (what features the system learned as "normal")
        ax = axs[2, i]
        ax.semilogx(freqs[mask], prom[mask], color=color, lw=0.8, alpha=0.8)
        ax.axhline(0, color='k', ls='-', alpha=0.2)

        # Mark learned peaks
        peaks, _ = find_peaks(prom[mask], height=3, distance=5)
        if len(peaks):
            ax.semilogx(freqs[mask][peaks], prom[mask][peaks], 'rv', ms=6)
            top = peaks[np.argsort(prom[mask][peaks])[::-1][:5]]
            for p in top:
                ax.annotate(f'{freqs[mask][p]:.1f} Hz\n+{prom[mask][p]:.1f} dB',
                           (freqs[mask][p], prom[mask][p]), fontsize=6,
                           textcoords='offset points', xytext=(5, 5))

        valleys, _ = find_peaks(-prom[mask], height=3, distance=5)
        if len(valleys):
            ax.semilogx(freqs[mask][valleys], prom[mask][valleys], 'b^', ms=5)

        ax.set_title(f'{name} — Baseline Prominence (learned normal features)')
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Prominence (dB)')
        ax.grid(True, alpha=0.3, which='both')

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    if show:
        plt.show()
    plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# Training and checking (folder-level operations)
# ---------------------------------------------------------------------------

def train_from_folder(baseline_folder: str, analyzer: SpectralAnalyzer,
                      p_fa: float = 0.01, train_fraction: float = 0.5,
                      verbose: bool = True) -> SpectralBaseline:
    """
    Learn a baseline from all CSVs in a folder.

    Each CSV is split into overlapping frames (nperseg long, 75% overlap).
    All frames across all files are pooled — different lengths are fine.
    Frames are shuffled, then split into Phase 1 / Phase 2.
    """
    files = load_folder(baseline_folder)
    if verbose:
        print(f"Found {len(files)} CSV files in {baseline_folder}")

    all_frames = []
    for filename, fs, signals in files:
        frames = extract_frames(signals, nperseg=analyzer.nperseg)
        if verbose:
            n = len(next(iter(signals.values())))
            print(f"  {filename}: {n/fs:.1f}s → {len(frames)} frames")
        all_frames.extend(frames)

    if len(all_frames) < 4:
        raise ValueError(
            f"Only {len(all_frames)} frames total. Need more data or smaller nperseg.")

    # Shuffle to mix across files
    rng = np.random.default_rng(42)
    all_frames = [all_frames[i] for i in rng.permutation(len(all_frames))]

    split = max(int(len(all_frames) * train_fraction), 2)
    if verbose:
        print(f"\nTotal frames: {len(all_frames)}")
        print(f"Phase 1 (learn baseline): {split}")
        print(f"Phase 2 (calibrate thresholds): {len(all_frames) - split}")

    baseline = SpectralBaseline(analyzer=analyzer, p_fa=p_fa)

    for f in all_frames[:split]:
        baseline.accumulate_phase1(f)
    baseline.freeze_baseline()
    if verbose:
        print(f"Baseline frozen. {baseline.n_bins} frequency bins.")

    for f in all_frames[split:]:
        baseline.accumulate_phase2(f)
    baseline.calibrate()

    if verbose:
        for name in baseline.T_threshold:
            nu = baseline.T_nu_eff.get(name, 0)
            print(f"\n  {name}:")
            print(f"    T threshold: {baseline.T_threshold[name]:.1f}")
            print(f"    M threshold: {baseline.M_threshold[name]:.1f}")
            print(f"    Effective DOF: {nu:.0f} / {baseline.n_bins} bins")
            print(f"    Phase 1 frames: {baseline._n_phase1}")
            print(f"    Phase 2 frames: {baseline._n_phase2}")

    return baseline


def plot_summary(results: list[tuple[str, DetectionResult]],
                 baseline: SpectralBaseline,
                 save_path: str = None, show: bool = False):
    """
    Summary dashboard of all monitored files.

    Top row:    T and M scatter per axis (each dot is a file, threshold line shown)
    Middle row: Per-file z-score heatmap per axis (files × frequency bins)
    Bottom row: Per-file prominence-z heatmap per axis
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    axes_names = list(baseline.center.keys())
    n_axes = len(axes_names)
    colors = ['#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12', '#1abc9c']

    filenames = [Path(fn).stem for fn, _ in results]
    # Truncate long filenames for readability
    short_names = []
    for fn in filenames:
        # Try to extract a timestamp portion
        parts = fn.split('_')
        if len(parts) >= 4:
            short_names.append('_'.join(parts[-2:]))  # last two parts (time_battery)
        else:
            short_names.append(fn[:20])

    freqs = baseline.freqs
    mask = freqs > 0.1
    freqs_masked = freqs[mask]

    n_files = len(results)

    fig, axs = plt.subplots(3, n_axes, figsize=(7 * n_axes, 4 + n_files * 0.4 + 6),
                            gridspec_kw={'height_ratios': [3, max(n_files * 0.3, 2), max(n_files * 0.3, 2)]})
    if n_axes == 1:
        axs = axs[:, np.newaxis]

    fig.suptitle(f'Monitor Summary — {n_files} files', fontsize=16, y=0.99)

    for i, name in enumerate(axes_names):
        color = colors[i % len(colors)]

        # Gather per-file stats
        T_vals = [r.T[name] for _, r in results]
        M_vals = [r.M[name] for _, r in results]
        T_trig = [r.T_triggered[name] for _, r in results]
        M_trig = [r.M_triggered[name] for _, r in results]
        any_trig = [r.triggered[name] for _, r in results]

        T_thresh = baseline.T_threshold[name]
        M_thresh = baseline.M_threshold[name]

        # --- Row 0: T and M scatter ---
        ax = axs[0, i]

        # Normalize T and M to their thresholds so they're on the same scale
        T_norm = np.array(T_vals) / T_thresh
        M_norm = np.array(M_vals) / M_thresh

        for j in range(n_files):
            if any_trig[j]:
                ax.scatter(T_norm[j], M_norm[j], c='#e74c3c',
                          s=80, marker='x', linewidths=2, zorder=3)
            else:
                ax.scatter(T_norm[j], M_norm[j], c=color, edgecolors='#27ae60',
                          linewidths=1.5, s=60, marker='o', zorder=3)
            # Label the point
            ax.annotate(short_names[j], (T_norm[j], M_norm[j]),
                       fontsize=5, alpha=0.7,
                       textcoords='offset points', xytext=(4, 4))

        # Threshold lines at 1.0 (normalized)
        ax.axvline(1.0, color='red', ls='--', alpha=0.5, label='T threshold')
        ax.axhline(1.0, color='blue', ls='--', alpha=0.5, label='M threshold')

        # Shade the danger zone
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        ax.axvspan(1.0, max(xlim[1], 1.5), alpha=0.05, color='red')
        ax.axhspan(1.0, max(ylim[1], 1.5), alpha=0.05, color='blue')

        ax.set_xlabel('T / threshold (global shape)')
        ax.set_ylabel('M / threshold (peak change)')
        ax.set_title(f'{name} — Detection Space')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

        # --- Row 1: Z-score heatmap ---
        ax = axs[1, i]
        z_matrix = np.array([r.z_scores[name][mask] for _, r in results])

        vmax = min(np.percentile(np.abs(z_matrix), 98), 20)
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

        im = ax.pcolormesh(freqs_masked, range(n_files), z_matrix,
                          norm=norm, cmap='RdBu_r', shading='auto')
        ax.set_xscale('log')
        ax.set_yticks(range(n_files))
        ax.set_yticklabels(short_names, fontsize=6)
        ax.set_xlabel('Frequency (Hz)')
        ax.set_title(f'{name} — Z-scores across files')
        plt.colorbar(im, ax=ax, label='z-score', shrink=0.8)

        # Mark triggered files
        for j in range(n_files):
            if any_trig[j]:
                ax.text(-0.01, j, '⚠', transform=ax.get_yaxis_transform(),
                       fontsize=8, ha='right', va='center', color='red')

        # --- Row 2: Prominence-z heatmap ---
        ax = axs[2, i]
        pz_matrix = np.array([r.prominence_z[name][mask] for _, r in results])

        vmax_p = min(np.percentile(np.abs(pz_matrix), 98), 15)
        norm_p = TwoSlopeNorm(vmin=-vmax_p, vcenter=0, vmax=vmax_p)

        im2 = ax.pcolormesh(freqs_masked, range(n_files), pz_matrix,
                           norm=norm_p, cmap='RdBu_r', shading='auto')
        ax.set_xscale('log')
        ax.set_yticks(range(n_files))
        ax.set_yticklabels(short_names, fontsize=6)
        ax.set_xlabel('Frequency (Hz)')
        ax.set_title(f'{name} — Prominence Z across files (new/gone features)')
        plt.colorbar(im2, ax=ax, label='prominence z', shrink=0.8)

        for j in range(n_files):
            if M_trig[j]:
                ax.text(-0.01, j, '⚠', transform=ax.get_yaxis_transform(),
                       fontsize=8, ha='right', va='center', color='red')

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    if show:
        plt.show()
    plt.close(fig)
    return fig


def check_folder(monitor_folder: str, baseline: SpectralBaseline,
                 output_dir: str = None, verbose: bool = True
                 ) -> list[tuple[str, DetectionResult]]:
    """
    Check all CSVs in a folder against a learned baseline.
    Always saves per-file comparison plots and a summary dashboard to output_dir.
    """
    files = load_folder(monitor_folder)

    # Always create results directory
    if output_dir is None:
        output_dir = str(Path(monitor_folder).parent / 'results')
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    results = []
    for filename, fs, signals in files:
        try:
            result = baseline.detect(signals)
        except ValueError as e:
            if verbose:
                print(f"\n  Skipping {filename}: {e}")
            continue

        frame = baseline.analyzer.analyze_frame(signals)

        any_triggered = any(result.triggered.values())
        icon = "⚠ " if any_triggered else "✓ "

        if verbose:
            print(f"\n{'='*60}")
            print(f"{icon}{filename}")
            print(f"{'='*60}")
            for name in result.triggered:
                ax_s = "ANOMALY" if result.triggered[name] else "normal"
                print(f"  {name}: {ax_s}")
                print(f"    T = {result.T[name]:.1f} / {result.T_threshold[name]:.1f}  "
                      f"{'⚠' if result.T_triggered[name] else '✓'}")
                print(f"    M = {result.M[name]:.1f} / {result.M_threshold[name]:.1f}  "
                      f"{'⚠' if result.M_triggered[name] else '✓'}")
                if result.triggered[name]:
                    z = result.z_scores[name]
                    for idx in np.argsort(np.abs(z))[::-1][:3]:
                        print(f"    → {result.freqs[idx]:8.1f} Hz  z={z[idx]:+.1f}")

        # Always save per-file comparison plot
        save = str(Path(output_dir) / f"{Path(filename).stem}_comparison.png")
        plot_comparison(baseline, result, frame,
                       title=f'{filename} vs Baseline', save_path=save)
        if verbose:
            print(f"  Plot: {save}")

        results.append((filename, result))

    # Summary
    if verbose:
        n_anom = sum(1 for _, r in results if any(r.triggered.values()))
        print(f"\n{'='*60}")
        print(f"Summary: {n_anom} / {len(results)} files flagged")

    # Always save summary dashboard
    if len(results) >= 1:
        summary_path = str(Path(output_dir) / '_summary.png')
        plot_summary(results, baseline, save_path=summary_path)
        if verbose:
            print(f"Summary plot: {summary_path}")

    return results


# ---------------------------------------------------------------------------
# Spectral Map (dimensionality reduction visualization)
# ---------------------------------------------------------------------------

def spectral_map(baseline: SpectralBaseline,
                 baseline_folder: str,
                 monitor_folder: str,
                 output_dir: str,
                 method: str = 'umap',
                 verbose: bool = True):
    """
    Embed all files from baseline/ and monitor/ into 2D using their z-score
    vectors. Produces scatter plots showing how files cluster.

    Each file → detect() → z-score vector (n_bins × n_axes) → one point.
    Similar spectral patterns end up near each other.

    Parameters
    ----------
    method : str
        'umap' (default, best), 'tsne', or 'pca'.
    """
    import matplotlib.pyplot as plt

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    axes_names = list(baseline.center.keys())

    # --- Collect z-score vectors from all files ---
    vectors = []
    labels = []
    sources = []
    T_ratios = {}   # per-axis T/threshold
    M_ratios = {}
    any_triggered = []

    for ax_name in axes_names:
        T_ratios[ax_name] = []
        M_ratios[ax_name] = []

    def process_folder(folder, source_label):
        try:
            files = load_folder(folder)
        except FileNotFoundError:
            if verbose:
                print(f"  {folder}: not found, skipping")
            return
        for filename, fs, signals in files:
            try:
                result = baseline.detect(signals)
            except ValueError as e:
                if verbose:
                    print(f"  Skipping {filename}: {e}")
                continue

            # Build feature vector: z-scores + prominence-z, all axes
            z_parts = []
            pz_parts = []
            for name in axes_names:
                z_parts.append(result.z_scores[name])
                pz_parts.append(result.prominence_z[name])

            feature = np.concatenate(z_parts + pz_parts)
            vectors.append(feature)

            # Short label from filename
            stem = Path(filename).stem
            labels.append(stem)
            sources.append(source_label)

            for name in axes_names:
                T_ratios[name].append(result.T[name] / baseline.T_threshold[name])
                M_ratios[name].append(result.M[name] / baseline.M_threshold[name])

            any_triggered.append(any(result.triggered.values()))

            if verbose:
                trig = "⚠" if any(result.triggered.values()) else "✓"
                print(f"  {trig} {filename}")

    if verbose:
        print("Processing baseline files...")
    process_folder(baseline_folder, 'baseline')

    if verbose:
        print("Processing monitor files...")
    process_folder(monitor_folder, 'monitor')

    n_files = len(vectors)
    if n_files < 3:
        print(f"Error: need at least 3 files for mapping, have {n_files}")
        return

    X = np.array(vectors)  # (n_files, n_features)
    n_features = X.shape[1]

    if verbose:
        print(f"\n{n_files} files, {n_features} features per file")
        n_bl = sources.count('baseline')
        n_mon = sources.count('monitor')
        print(f"  Baseline: {n_bl} files")
        print(f"  Monitor: {n_mon} files")

    # --- Handle NaN/Inf ---
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # --- Normalize features ---
    from sklearn.preprocessing import StandardScaler
    X_scaled = StandardScaler().fit_transform(X)

    # --- Dimensionality reduction ---
    if method == 'umap':
        try:
            import umap
            reducer = umap.UMAP(n_components=2, n_neighbors=min(15, n_files - 1),
                               min_dist=0.1, metric='euclidean', random_state=42)
            embedding = reducer.fit_transform(X_scaled)
            method_label = 'UMAP'
        except ImportError:
            print("  umap-learn not installed, falling back to t-SNE")
            print("  Install with: pip install umap-learn")
            method = 'tsne'

    if method == 'tsne':
        from sklearn.manifold import TSNE
        perplexity = min(30, max(2, n_files // 3))
        reducer = TSNE(n_components=2, perplexity=perplexity,
                      random_state=42, init='pca')
        embedding = reducer.fit_transform(X_scaled)
        method_label = f't-SNE (perplexity={perplexity})'

    elif method == 'pca':
        from sklearn.decomposition import PCA
        reducer = PCA(n_components=2)
        embedding = reducer.fit_transform(X_scaled)
        var = reducer.explained_variance_ratio_
        method_label = f'PCA ({var[0]:.0%} + {var[1]:.0%} variance)'

    if verbose:
        print(f"  Method: {method_label}")

    # --- Build color/marker arrays ---
    source_arr = np.array(sources)
    trig_arr = np.array(any_triggered)

    # --- Plot 1: Main map colored by source ---
    fig, axs = plt.subplots(1, 3, figsize=(24, 8))
    fig.suptitle(f'Spectral Map — {method_label}', fontsize=16, y=1.02)

    # Panel 1: Colored by source (baseline vs monitor)
    ax = axs[0]
    bl_mask = source_arr == 'baseline'
    mon_mask = source_arr == 'monitor'

    if bl_mask.any():
        ax.scatter(embedding[bl_mask, 0], embedding[bl_mask, 1],
                  c='#95a5a6', s=40, alpha=0.6, label='Baseline', zorder=2)
    if mon_mask.any():
        # Monitor: green if normal, red if triggered
        mon_normal = mon_mask & ~trig_arr
        mon_trig = mon_mask & trig_arr
        if mon_normal.any():
            ax.scatter(embedding[mon_normal, 0], embedding[mon_normal, 1],
                      c='#27ae60', s=60, alpha=0.8, label='Monitor (normal)',
                      edgecolors='white', linewidths=0.5, zorder=3)
        if mon_trig.any():
            ax.scatter(embedding[mon_trig, 0], embedding[mon_trig, 1],
                      c='#e74c3c', s=80, alpha=0.9, label='Monitor (anomaly)',
                      edgecolors='white', linewidths=0.5, zorder=4)

    # Label all points
    for j in range(n_files):
        ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.7,
                   textcoords='offset points', xytext=(4, 4))

    ax.set_title('By Source')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1')
    ax.set_ylabel('Component 2')

    # Panel 2: Colored by T ratio (global shape deviation)
    ax = axs[1]
    # Use mean T ratio across axes
    mean_T = np.mean([T_ratios[name] for name in axes_names], axis=0)
    sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                   c=mean_T, cmap='RdYlGn_r', s=60, alpha=0.8,
                   edgecolors='white', linewidths=0.5,
                   vmin=0, vmax=max(2, np.percentile(mean_T, 95)))
    plt.colorbar(sc, ax=ax, label='T / threshold', shrink=0.8)
    ax.axhline(color='k', alpha=0.1)
    ax.axvline(color='k', alpha=0.1)

    for j in range(n_files):
        ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.7,
                   textcoords='offset points', xytext=(4, 4))

    ax.set_title('By Global Shape Deviation (T)')
    ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1')
    ax.set_ylabel('Component 2')

    # Panel 3: Colored by M ratio (peak change)
    ax = axs[2]
    mean_M = np.mean([M_ratios[name] for name in axes_names], axis=0)
    sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                   c=mean_M, cmap='RdYlGn_r', s=60, alpha=0.8,
                   edgecolors='white', linewidths=0.5,
                   vmin=0, vmax=max(2, np.percentile(mean_M, 95)))
    plt.colorbar(sc, ax=ax, label='M / threshold', shrink=0.8)

    for j in range(n_files):
        ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.7,
                   textcoords='offset points', xytext=(4, 4))

    ax.set_title('By Peak Change (M)')
    ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1')
    ax.set_ylabel('Component 2')

    plt.tight_layout()
    main_path = str(Path(output_dir) / f'{method}_spectral_map.png')
    plt.savefig(main_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    if verbose:
        print(f"\nSaved: {main_path}")

    # --- Plot 2: Per-axis maps ---
    fig2, axs2 = plt.subplots(2, len(axes_names),
                               figsize=(7 * len(axes_names), 12))
    if len(axes_names) == 1:
        axs2 = axs2[:, np.newaxis]

    fig2.suptitle(f'Spectral Map Per Axis — {method_label}', fontsize=16, y=1.01)

    for i, name in enumerate(axes_names):
        # Top row: T ratio
        ax = axs2[0, i]
        T_arr = np.array(T_ratios[name])
        sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                       c=T_arr, cmap='RdYlGn_r', s=50, alpha=0.8,
                       edgecolors='white', linewidths=0.5,
                       vmin=0, vmax=max(2, np.percentile(T_arr, 95)))
        plt.colorbar(sc, ax=ax, label='T / threshold', shrink=0.8)
        for j in range(n_files):
            ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.6,
                       textcoords='offset points', xytext=(4, 4))
        ax.set_title(f'{name} — T (global shape)')
        ax.grid(True, alpha=0.2)

        # Bottom row: M ratio
        ax = axs2[1, i]
        M_arr = np.array(M_ratios[name])
        sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                       c=M_arr, cmap='RdYlGn_r', s=50, alpha=0.8,
                       edgecolors='white', linewidths=0.5,
                       vmin=0, vmax=max(2, np.percentile(M_arr, 95)))
        plt.colorbar(sc, ax=ax, label='M / threshold', shrink=0.8)
        for j in range(n_files):
            ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.6,
                       textcoords='offset points', xytext=(4, 4))
        ax.set_title(f'{name} — M (peak change)')
        ax.grid(True, alpha=0.2)

    plt.tight_layout()
    per_axis_path = str(Path(output_dir) / f'{method}_spectral_map_per_axis.png')
    plt.savefig(per_axis_path, dpi=150, bbox_inches='tight')
    plt.close(fig2)

    if verbose:
        print(f"Saved: {per_axis_path}")

    # --- Plot 3: Nearest-neighbor analysis (what is each cluster?) ---
    # For each file, find the top 3 frequency bins driving its position
    fig3, ax3 = plt.subplots(1, 1, figsize=(10, 8))
    fig3.suptitle(f'Spectral Map — Annotated Clusters', fontsize=14)

    # Color by source
    if bl_mask.any():
        ax3.scatter(embedding[bl_mask, 0], embedding[bl_mask, 1],
                   c='#d5d8dc', s=30, alpha=0.5, label='Baseline', zorder=2)
    if mon_mask.any():
        mon_normal = mon_mask & ~trig_arr
        mon_trig = mon_mask & trig_arr
        if mon_normal.any():
            ax3.scatter(embedding[mon_normal, 0], embedding[mon_normal, 1],
                       c='#27ae60', s=50, alpha=0.8, label='Normal', zorder=3)
        if mon_trig.any():
            ax3.scatter(embedding[mon_trig, 0], embedding[mon_trig, 1],
                       c='#e74c3c', s=70, alpha=0.9, label='Anomaly', zorder=4)

    # Annotate anomalies with their top deviating frequencies
    freqs = baseline.freqs
    for j in range(n_files):
        if not any_triggered[j]:
            ax3.annotate(labels[j], embedding[j], fontsize=5, alpha=0.5,
                        textcoords='offset points', xytext=(4, 2))
            continue

        # Find top-contributing frequencies from the z-score portion of the vector
        n_bins = len(freqs)
        z_all = vectors[j][:n_bins * len(axes_names)]  # z-score portion only
        # Reshape to (n_axes, n_bins) and find overall top bins
        z_matrix = z_all.reshape(len(axes_names), n_bins)
        # Max absolute z across axes for each bin
        max_z_per_bin = np.max(np.abs(z_matrix), axis=0)
        top_bins = np.argsort(max_z_per_bin)[::-1][:3]

        # Build annotation
        details = []
        for b in top_bins:
            best_ax = axes_names[np.argmax(np.abs(z_matrix[:, b]))]
            z_val = z_matrix[np.argmax(np.abs(z_matrix[:, b])), b]
            details.append(f"{freqs[b]:.0f}Hz ({best_ax} z={z_val:+.0f})")

        annotation = f"{labels[j]}\n" + "\n".join(details)
        ax3.annotate(annotation, embedding[j], fontsize=5,
                    textcoords='offset points', xytext=(8, 8),
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow',
                             alpha=0.8, edgecolor='gray'),
                    arrowprops=dict(arrowstyle='->', color='gray', lw=0.5))

    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.2)
    ax3.set_xlabel('Component 1')
    ax3.set_ylabel('Component 2')

    plt.tight_layout()
    annotated_path = str(Path(output_dir) / f'{method}_spectral_map_annotated.png')
    plt.savefig(annotated_path, dpi=150, bbox_inches='tight')
    plt.close(fig3)

    if verbose:
        print(f"Saved: {annotated_path}")

    return embedding, labels, sources, vectors, any_triggered


# ---------------------------------------------------------------------------
# Spectral Clustering (HDBSCAN on embedding)
# ---------------------------------------------------------------------------

def spectral_cluster(baseline: SpectralBaseline,
                     baseline_folder: str,
                     monitor_folder: str,
                     output_dir: str,
                     method: str = 'umap',
                     min_cluster_size: int = 5,
                     verbose: bool = True):
    """
    Run spectral_map then HDBSCAN clustering on the embedding.
    Identifies baseline cluster(s), draws convex hull boundaries,
    and flags anything outside as structurally anomalous.

    This is exploratory — a visual tool for finding patterns,
    not a replacement for the calibrated T/M thresholds.
    """
    import matplotlib.pyplot as plt
    from sklearn.cluster import HDBSCAN
    from scipy.spatial import ConvexHull

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Run the map first (suppress its plots by redirecting to a temp dir)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        embedding, labels, sources, vectors, any_triggered = spectral_map(
            baseline, baseline_folder, monitor_folder,
            output_dir=tmp, method=method, verbose=verbose
        )

    source_arr = np.array(sources)
    trig_arr = np.array(any_triggered)
    n_files = len(labels)

    # --- HDBSCAN on the embedding ---
    clusterer = HDBSCAN(
        min_cluster_size=max(min_cluster_size, 3),
        min_samples=2,
    )
    cluster_labels = clusterer.fit_predict(embedding)
    n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)

    if verbose:
        print(f"\nHDBSCAN found {n_clusters} clusters")
        print(f"  Noise points (label=-1): {np.sum(cluster_labels == -1)}")
        for c in range(n_clusters):
            members = np.where(cluster_labels == c)[0]
            n_bl = np.sum(source_arr[members] == 'baseline')
            n_mon = np.sum(source_arr[members] == 'monitor')
            member_names = [labels[i] for i in members[:5]]
            extra = f"..." if len(members) > 5 else ""
            print(f"  Cluster {c}: {len(members)} files ({n_bl} baseline, {n_mon} monitor)")
            print(f"    e.g. {', '.join(member_names)}{extra}")

    # --- Identify baseline clusters ---
    # A cluster is "baseline" if majority of its members are from baseline/
    baseline_cluster_ids = set()
    for c in range(n_clusters):
        members = np.where(cluster_labels == c)[0]
        n_bl = np.sum(source_arr[members] == 'baseline')
        if n_bl > len(members) * 0.3:  # at least 30% baseline
            baseline_cluster_ids.add(c)

    if verbose:
        print(f"\n  Baseline clusters: {baseline_cluster_ids or 'none identified'}")

    # --- Classify: inside baseline cluster or not ---
    structurally_anomalous = np.zeros(n_files, dtype=bool)
    for j in range(n_files):
        if source_arr[j] == 'baseline':
            continue
        if cluster_labels[j] == -1:  # noise
            structurally_anomalous[j] = True
        elif cluster_labels[j] not in baseline_cluster_ids:
            structurally_anomalous[j] = True

    if verbose:
        n_mon = np.sum(source_arr == 'monitor')
        n_struct_anom = np.sum(structurally_anomalous)
        print(f"  Structurally anomalous: {n_struct_anom} / {n_mon} monitor files")

    # --- Plot: Two panels ---
    fig, axs = plt.subplots(1, 2, figsize=(20, 9))
    fig.suptitle(f'Spectral Clustering — HDBSCAN ({n_clusters} clusters)', fontsize=16, y=1.02)

    # ---- Panel 1: Colored by cluster with convex hulls ----
    ax = axs[0]
    cluster_cmap = plt.cm.Set2 if n_clusters <= 8 else plt.cm.tab20
    cluster_colors = cluster_cmap(np.linspace(0, 0.9, max(n_clusters, 1)))

    # Noise points (background)
    noise_mask = cluster_labels == -1
    if noise_mask.any():
        ax.scatter(embedding[noise_mask, 0], embedding[noise_mask, 1],
                  c='#d5d8dc', s=20, alpha=0.4, marker='.', label='Noise', zorder=1)

    # Each cluster with hull
    for c in range(n_clusters):
        members = np.where(cluster_labels == c)[0]
        color = cluster_colors[c]
        is_bl = c in baseline_cluster_ids
        label = f'Cluster {c} {"(baseline)" if is_bl else ""}'

        ax.scatter(embedding[members, 0], embedding[members, 1],
                  c=[color], s=50, alpha=0.8, label=label,
                  edgecolors='white', linewidths=0.5, zorder=3)

        # Convex hull
        if len(members) >= 3:
            try:
                hull = ConvexHull(embedding[members])
                hull_pts = embedding[members][hull.vertices]
                hull_pts = np.vstack([hull_pts, hull_pts[0]])

                fill_alpha = 0.15 if is_bl else 0.08
                edge_style = '-' if is_bl else '--'
                edge_width = 2.0 if is_bl else 1.0

                ax.fill(hull_pts[:, 0], hull_pts[:, 1],
                       color=color, alpha=fill_alpha)
                ax.plot(hull_pts[:, 0], hull_pts[:, 1],
                       color=color, ls=edge_style, lw=edge_width, alpha=0.7)
            except Exception:
                pass

    for j in range(n_files):
        ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.6,
                   textcoords='offset points', xytext=(4, 3))

    ax.set_title('HDBSCAN Clusters (solid hull = baseline)')
    ax.legend(fontsize=7, loc='best')
    ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1')
    ax.set_ylabel('Component 2')

    # ---- Panel 2: Baseline boundary with anomaly flagging ----
    ax = axs[1]

    # Draw baseline hulls as filled green regions
    for c in baseline_cluster_ids:
        members = np.where(cluster_labels == c)[0]
        if len(members) >= 3:
            try:
                hull = ConvexHull(embedding[members])
                hull_pts = embedding[members][hull.vertices]
                hull_pts = np.vstack([hull_pts, hull_pts[0]])
                ax.fill(hull_pts[:, 0], hull_pts[:, 1],
                       color='#27ae60', alpha=0.12, label='Baseline region')
                ax.plot(hull_pts[:, 0], hull_pts[:, 1],
                       color='#27ae60', ls='-', lw=2.5, alpha=0.6)
            except Exception:
                pass

    # Baseline points
    bl_mask = source_arr == 'baseline'
    if bl_mask.any():
        ax.scatter(embedding[bl_mask, 0], embedding[bl_mask, 1],
                  c='#95a5a6', s=30, alpha=0.5, label='Baseline', zorder=2)

    # Monitor points: inside vs outside
    mon_mask = source_arr == 'monitor'
    if mon_mask.any():
        inside = mon_mask & ~structurally_anomalous
        outside = mon_mask & structurally_anomalous

        if inside.any():
            ax.scatter(embedding[inside, 0], embedding[inside, 1],
                      c='#27ae60', s=60, alpha=0.8, label='Inside baseline',
                      edgecolors='white', linewidths=0.5, zorder=3)
        if outside.any():
            ax.scatter(embedding[outside, 0], embedding[outside, 1],
                      c='#e74c3c', s=80, alpha=0.9, label='Outside baseline',
                      edgecolors='white', linewidths=0.5, zorder=4)

    # Annotate outside-baseline points with top frequencies
    freqs = baseline.freqs
    axes_names = list(baseline.center.keys())
    n_bins = len(freqs)

    for j in range(n_files):
        if not structurally_anomalous[j]:
            ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.5,
                       textcoords='offset points', xytext=(4, 2))
            continue

        z_all = vectors[j][:n_bins * len(axes_names)]
        z_matrix = z_all.reshape(len(axes_names), n_bins)
        max_z_per_bin = np.max(np.abs(z_matrix), axis=0)
        top_bins = np.argsort(max_z_per_bin)[::-1][:3]

        details = []
        for b in top_bins:
            best_ax_idx = np.argmax(np.abs(z_matrix[:, b]))
            z_val = z_matrix[best_ax_idx, b]
            details.append(f"{freqs[b]:.0f}Hz ({axes_names[best_ax_idx]} z={z_val:+.0f})")

        annotation = f"{labels[j]}\n" + "\n".join(details)
        ax.annotate(annotation, embedding[j], fontsize=5,
                   textcoords='offset points', xytext=(8, 8),
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow',
                            alpha=0.8, edgecolor='gray'),
                   arrowprops=dict(arrowstyle='->', color='gray', lw=0.5))

    ax.set_title('Baseline Boundary — Inside vs Outside')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1')
    ax.set_ylabel('Component 2')

    plt.tight_layout()
    cluster_path = str(Path(output_dir) / f'{method}_spectral_clusters.png')
    plt.savefig(cluster_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    if verbose:
        print(f"\nSaved: {cluster_path}")

    # --- Print classification ---
    if verbose:
        print(f"\n{'='*60}")
        print(f"Classification:")
        print(f"{'='*60}")
        for j in range(n_files):
            if source_arr[j] == 'baseline':
                continue
            cluster_id = cluster_labels[j]
            if structurally_anomalous[j]:
                cluster_str = f"cluster {cluster_id}" if cluster_id >= 0 else "noise"
                print(f"  ⚠ {labels[j]:40s}  OUTSIDE  ({cluster_str})")
            else:
                print(f"  ✓ {labels[j]:40s}  inside baseline (cluster {cluster_id})")

    return {
        'embedding': embedding,
        'labels': labels,
        'sources': sources,
        'cluster_labels': cluster_labels,
        'structurally_anomalous': structurally_anomalous,
        'baseline_cluster_ids': baseline_cluster_ids,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Spectral Fingerprint Toolkit',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. %(prog)s init   my_project --fs 1844.3
  2. (put known-good CSVs in my_project/baseline/)
  3. %(prog)s train  my_project
  4. (put new CSVs in my_project/monitor/)
  5. %(prog)s check  my_project [--plots]

Standalone:
  %(prog)s plot  data.csv [--fs 1844.3]
        """)

    sub = parser.add_subparsers(dest='command', required=True)

    # init
    p = sub.add_parser('init', help='Initialize a project folder')
    p.add_argument('project', help='Project directory')
    p.add_argument('--fs', type=float, required=True, help='Sample rate (Hz)')
    p.add_argument('--nperseg', type=int, default=4096, help='FFT length')
    p.add_argument('--median-window', type=int, default=51)
    p.add_argument('--p-fa', type=float, default=0.01)

    # train
    p = sub.add_parser('train', help='Learn baseline from project/baseline/')
    p.add_argument('project', help='Project directory')
    p.add_argument('--train-fraction', type=float, default=0.5)

    # check
    p = sub.add_parser('check', help='Check project/monitor/ against baseline')
    p.add_argument('project', help='Project directory')

    # show
    p = sub.add_parser('show', help='Visualize the learned baseline')
    p.add_argument('project', help='Project directory')
    p.add_argument('--output', '-o', default=None, help='Output image path')
    p.add_argument('--show', action='store_true')

    # map
    p = sub.add_parser('map', help='2D spectral map of all files (clustering)')
    p.add_argument('project', help='Project directory')
    p.add_argument('--method', choices=['umap', 'tsne', 'pca', 'all'], default='umap',
                  help='Dimensionality reduction method (default: umap). Use "all" to run every method.')

    # cluster
    p = sub.add_parser('cluster', help='HDBSCAN clustering — find baseline boundary and flag outliers')
    p.add_argument('project', help='Project directory')
    p.add_argument('--method', choices=['umap', 'tsne', 'pca'], default='tsne',
                  help='Embedding method (default: tsne)')
    p.add_argument('--min-cluster-size', type=int, default=5,
                  help='Minimum points to form a cluster (default: 5)')

    # plot
    p = sub.add_parser('plot', help='Plot spectral analysis of a single CSV')
    p.add_argument('csv', help='CSV file path')
    p.add_argument('--fs', type=float, default=None)
    p.add_argument('--nperseg', type=int, default=4096)
    p.add_argument('--median-window', type=int, default=51)
    p.add_argument('--peak-height', type=float, default=3.0)
    p.add_argument('--output', '-o', default=None)
    p.add_argument('--show', action='store_true')

    args = parser.parse_args()

    if args.command == 'init':
        proj = Path(args.project)
        proj.mkdir(parents=True, exist_ok=True)
        (proj / 'baseline').mkdir(exist_ok=True)
        (proj / 'monitor').mkdir(exist_ok=True)

        config = {'fs': args.fs, 'nperseg': args.nperseg,
                  'median_window': args.median_window, 'p_fa': args.p_fa}
        with open(proj / 'config.json', 'w') as f:
            json.dump(config, f, indent=2)

        print(f"Initialized: {proj}")
        print(f"  baseline/  — drop known-good CSVs here")
        print(f"  monitor/   — drop new CSVs here to check")
        print(f"\nNext: python {sys.argv[0]} train {args.project}")

    elif args.command == 'train':
        proj = Path(args.project)
        cfg_path = proj / 'config.json'
        if not cfg_path.exists():
            print(f"Error: {cfg_path} not found. Run `init` first."); sys.exit(1)
        with open(cfg_path) as f:
            cfg = json.load(f)

        analyzer = SpectralAnalyzer(fs=cfg['fs'], nperseg=cfg['nperseg'],
                                    median_window=cfg['median_window'])
        baseline = train_from_folder(
            str(proj / 'baseline'), analyzer,
            p_fa=cfg['p_fa'], train_fraction=args.train_fraction)

        bl_path = proj / 'baseline.json'
        baseline.save(str(bl_path))
        print(f"\nSaved: {bl_path}")
        print(f"Next: python {sys.argv[0]} check {args.project}")

    elif args.command == 'check':
        proj = Path(args.project)
        bl_path = proj / 'baseline.json'
        if not bl_path.exists():
            print(f"Error: {bl_path} not found. Run `train` first."); sys.exit(1)

        baseline = SpectralBaseline.load(str(bl_path))
        out = str(proj / 'results')
        check_folder(str(proj / 'monitor'), baseline, output_dir=out)

    elif args.command == 'show':
        proj = Path(args.project)
        bl_path = proj / 'baseline.json'
        if not bl_path.exists():
            print(f"Error: {bl_path} not found. Run `train` first."); sys.exit(1)

        baseline = SpectralBaseline.load(str(bl_path))
        output = args.output or str(proj / 'baseline_fingerprint.png')

        print(f"Baseline: {bl_path}")
        print(f"  Bins: {baseline.n_bins}")
        print(f"  Phase 1 frames: {baseline._n_phase1}")
        print(f"  Phase 2 frames: {baseline._n_phase2}")
        print(f"  p_fa: {baseline.p_fa}")
        for name in baseline.T_threshold:
            nu = baseline.T_nu_eff.get(name, 0)
            print(f"\n  {name}:")
            print(f"    T threshold: {baseline.T_threshold[name]:.1f}")
            print(f"    M threshold: {baseline.M_threshold[name]:.1f}")
            print(f"    Effective DOF: {nu:.0f} / {baseline.n_bins}")

        plot_baseline(baseline, title=f'Learned Baseline — {proj.name}',
                     save_path=output, show=args.show)
        print(f"\nSaved: {output}")

    elif args.command == 'map':
        proj = Path(args.project)
        bl_path = proj / 'baseline.json'
        if not bl_path.exists():
            print(f"Error: {bl_path} not found. Run `train` first."); sys.exit(1)

        baseline = SpectralBaseline.load(str(bl_path))
        out_dir = str(proj / 'results' / 'map')

        methods = ['umap', 'tsne', 'pca'] if args.method == 'all' else [args.method]
        for m in methods:
            spectral_map(
                baseline=baseline,
                baseline_folder=str(proj / 'baseline'),
                monitor_folder=str(proj / 'monitor'),
                output_dir=out_dir,
                method=m,
            )

    elif args.command == 'cluster':
        proj = Path(args.project)
        bl_path = proj / 'baseline.json'
        if not bl_path.exists():
            print(f"Error: {bl_path} not found. Run `train` first."); sys.exit(1)

        baseline = SpectralBaseline.load(str(bl_path))
        out_dir = str(proj / 'results' / 'cluster')

        spectral_cluster(
            baseline=baseline,
            baseline_folder=str(proj / 'baseline'),
            monitor_folder=str(proj / 'monitor'),
            output_dir=out_dir,
            method=args.method,
            min_cluster_size=args.min_cluster_size,
        )

    elif args.command == 'plot':
        fs_auto, signals = load_csv(args.csv)
        fs = args.fs or fs_auto
        n = len(next(iter(signals.values())))
        print(f"Sample rate: {fs:.1f} Hz | Duration: {n/fs:.1f}s | Axes: {list(signals.keys())}")

        analyzer = SpectralAnalyzer(fs=fs, nperseg=args.nperseg,
                                    median_window=args.median_window)
        frame = analyzer.analyze_frame(signals, peak_height=args.peak_height)

        for name in frame.psd_db:
            pks, prom, freqs = frame.peaks[name], frame.prominence_db[name], frame.freqs
            print(f"\n{name}: {len(pks)} peaks, {len(frame.valleys[name])} dips")
            if len(pks):
                for j, p in enumerate(pks[np.argsort(prom[pks])[::-1]][:8]):
                    print(f"  {j+1}. {freqs[p]:8.2f} Hz  |  PSD: {frame.psd_db[name][p]:6.1f} dB  |  +{prom[p]:.1f} dB")

        output = args.output or (Path(args.csv).stem + '_spectrum.png')
        plot_spectral_frame(frame, title=Path(args.csv).stem, save_path=output, show=args.show)
        print(f"\nSaved: {output}")


if __name__ == '__main__':
    main()