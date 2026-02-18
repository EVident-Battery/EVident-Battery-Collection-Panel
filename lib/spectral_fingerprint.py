"""
Spectral Fingerprint Toolkit
=============================

Physics-grounded spectral anomaly detection for accelerometer data.

Statistical foundation:
    A Welch periodogram at frequency bin f satisfies:

        ν · Ŝ(f) / S(f)  ~  χ²(ν)

    where S(f) is the true PSD, Ŝ(f) is the estimate, and ν = 2K is the
    degrees of freedom (K = number of averaged Welch segments).

    The log-spectral ratio between two independent estimates has
    analytically known mean and variance:

        E[ln(Ŝ₁/Ŝ₂)]  = [ψ₀(ν₁/2) - ln(ν₁/2)] - [ψ₀(ν₂/2) - ln(ν₂/2)]
        Var[ln(Ŝ₁/Ŝ₂)] = ψ₁(ν₁/2) + ψ₁(ν₂/2)

    This gives exact per-bin z-scores with no empirical scale estimation.

Three-tier detection:
    z(f) = z_floor + z_shape(f) + z_feature(f)

    Tier 1 (Floor):   broadband level change — sensor coupling, excitation
    Tier 2 (Shape):   prominence-weighted spectral change — structural
    Tier 3 (Feature): peak-scale anomalies — specific defects

Folder structure:
    project_dir/
        baseline/       Known-good recordings (CSVs, any length)
        monitor/        New recordings to check against baseline
        config.json     Created by `init`, stores analyzer settings
        baseline.json   Created by `train`, stores learned fingerprint
        results/        Created by `check`, comparison plots

Workflow:
    1. python spectral_fingerprint.py init   project_dir --fs 1844.3
    2. (sensor drops CSVs into project_dir/baseline/)
    3. python spectral_fingerprint.py train  project_dir
    4. (sensor drops CSVs into project_dir/monitor/)
    5. python spectral_fingerprint.py check  project_dir

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
from scipy.special import polygamma, digamma
from scipy.stats import chi2, norm


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SpectralFrame:
    """One PSD snapshot per axis (for standalone plotting)."""
    freqs: np.ndarray
    psd_db: dict[str, np.ndarray]
    noise_floor_db: dict[str, np.ndarray]
    prominence_db: dict[str, np.ndarray]
    peaks: dict[str, np.ndarray]
    valleys: dict[str, np.ndarray]


@dataclass
class DetectionResult:
    """Result of comparing a recording against a learned baseline."""
    freqs: np.ndarray

    # Per-bin log-spectral z-scores
    z_scores: dict[str, np.ndarray]

    # New recording's PSD and prominence (for plotting)
    psd_new_db: dict[str, np.ndarray]
    prominence_new_db: dict[str, np.ndarray]
    dof_new: dict[str, int]

    # Tier 1: Floor change (overall level shift)
    floor_z: dict[str, float]
    floor_p: dict[str, float]
    floor_shift_db: dict[str, float]

    # Tier 2: Shape change (prominence-weighted)
    shape_stat: dict[str, float]
    shape_p: dict[str, float]
    shape_nu_eff: dict[str, float]

    # Tier 3: Feature change (peak-specific)
    feature_stat: dict[str, float]
    feature_p: dict[str, float]
    feature_freqs: dict[str, list]

    # Overall
    triggered: dict[str, bool]
    tier_triggered: dict[str, list]

    # ── Convenience aliases for backward compatibility ──

    @property
    def T(self) -> dict[str, float]:
        return self.shape_stat

    @property
    def M(self) -> dict[str, float]:
        return self.feature_stat

    @property
    def prominence_z(self) -> dict[str, np.ndarray]:
        """Feature-scale z-scores (z - smooth trend)."""
        pz = {}
        for name, z in self.z_scores.items():
            z_smooth = median_filter(z, size=51)
            pz[name] = z - z_smooth
        return pz


# ---------------------------------------------------------------------------
# Core analysis (unchanged — used for standalone plotting)
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
# Baseline learning and detection (F-test model)
# ---------------------------------------------------------------------------

class SpectralBaseline:
    """
    Physics-grounded spectral anomaly detection using F-test statistics.

    Baseline is a pooled high-DOF PSD estimate.  Detection uses
    log-spectral ratios with analytically known variance — no
    empirical scale estimation needed.

    Parameters
    ----------
    analyzer : SpectralAnalyzer
        Welch parameters (fs, nperseg, etc.).
    p_fa : float
        False alarm probability budget.  Split equally across 3 tiers.
    prominence_floor_db : float
        Bins with baseline prominence below this (in dB) are considered
        noise floor.  Bins above carry structural information.
    """

    def __init__(self, analyzer: SpectralAnalyzer, p_fa: float = 0.01,
                 prominence_floor_db: float = 3.0):
        self.analyzer = analyzer
        self.p_fa = p_fa
        self.prominence_floor_db = prominence_floor_db

        # Hann window with 50% overlap produces lag-1 autocorrelation ≈ 0.47
        # in log-spectral z-scores.  This reduces the effective number of
        # independent frequency bins by a factor of (1 + 2·r₁) ≈ 1.94.
        self._bin_correlation_factor = 1.94

        # Accumulation (pre-freeze)
        self._psd_weighted_sum: dict[str, np.ndarray] = {}
        self._dof_total: dict[str, int] = {}
        self._per_recording_log_psd: dict[str, list] = {}  # for process variance
        self._per_recording_dof: dict[str, list] = {}
        self._n_recordings: int = 0
        self.freqs: Optional[np.ndarray] = None

        # Frozen baseline
        self.psd_baseline: dict[str, np.ndarray] = {}       # linear
        self.psd_baseline_db: dict[str, np.ndarray] = {}    # dB
        self.dof_baseline: dict[str, int] = {}
        self.noise_floor: dict[str, np.ndarray] = {}        # linear
        self.noise_floor_db: dict[str, np.ndarray] = {}
        self.prominence: dict[str, np.ndarray] = {}          # linear ratio
        self.prominence_db: dict[str, np.ndarray] = {}
        self.structural_mask: dict[str, np.ndarray] = {}
        self.floor_mask: dict[str, np.ndarray] = {}

        # Process variance (measured from baseline recordings)
        self.process_var: dict[str, np.ndarray] = {}   # per-bin excess variance
        self.floor_process_std: dict[str, float] = {}  # broadband level jitter

        self._frozen = False

        # Backward-compat aliases
        self.center: dict[str, np.ndarray] = self.psd_baseline_db
        self.scale: dict[str, np.ndarray] = {}  # populated on freeze

    @property
    def is_trained(self) -> bool:
        return self._frozen

    @property
    def is_calibrated(self) -> bool:
        return self._frozen

    @property
    def n_bins(self) -> int:
        return len(self.freqs) if self.freqs is not None else 0

    # --- Welch helper ---

    def _compute_welch(self, signal: np.ndarray):
        """Compute Welch PSD in linear and dB, and return DOF."""
        signal = signal - np.mean(signal)
        nperseg = min(self.analyzer.nperseg, len(signal))
        noverlap = min(self.analyzer.noverlap, nperseg - 1)
        freqs, psd = welch(
            signal, fs=self.analyzer.fs,
            nperseg=nperseg,
            noverlap=noverlap,
            scaling='density',
        )
        step = nperseg - noverlap
        K = max(1, (len(signal) - nperseg) // step + 1)
        dof = 2 * K
        return freqs, psd, 10.0 * np.log10(psd + 1e-30), dof

    def _compute_noise_floor(self, psd_db: np.ndarray):
        """Noise floor via median filter."""
        nf_db = median_filter(psd_db, size=self.analyzer.median_window)
        nf_linear = 10.0 ** (nf_db / 10.0)
        return nf_linear, nf_db

    def _compute_prominence(self, psd_linear, noise_floor_linear):
        """Prominence = PSD / noise_floor (linear ratio)."""
        prom = psd_linear / (noise_floor_linear + 1e-30)
        prom_db = 10.0 * np.log10(prom + 1e-30)
        return prom, prom_db

    # --- Baseline accumulation ---

    def accumulate(self, signals: dict[str, np.ndarray]):
        """
        Add one recording to the baseline pool.

        Stores both the DOF-weighted sum (for the pooled PSD) and the
        per-recording log-PSDs (for measuring process variance).
        """
        if self._frozen:
            raise RuntimeError("Baseline is frozen.")

        for name, signal in signals.items():
            freqs, psd_linear, psd_db, dof = self._compute_welch(signal)

            if self.freqs is None:
                self.freqs = freqs

            if name not in self._psd_weighted_sum:
                self._psd_weighted_sum[name] = np.zeros_like(psd_linear)
                self._dof_total[name] = 0
                self._per_recording_log_psd[name] = []
                self._per_recording_dof[name] = []

            self._psd_weighted_sum[name] += dof * psd_linear
            self._dof_total[name] += dof

            # Store per-recording data for process variance estimation
            self._per_recording_log_psd[name].append(np.log(psd_linear + 1e-30))
            self._per_recording_dof[name].append(dof)

        self._n_recordings += 1

    def freeze(self):
        """
        Finalize the baseline.

        Computes:
        1. Pooled PSD (DOF-weighted mean)
        2. Noise floor and prominence (median filter)
        3. Process variance — the excess per-bin variance beyond what
           chi-squared estimation noise predicts.  This captures real
           environmental jitter (coupling, temperature, excitation).

        The total variance used in detection is:
            Var_total(f) = Var_chi2(f) + Var_process(f)
        """
        if self._n_recordings < 1:
            raise ValueError("Need at least 1 recording to freeze baseline.")

        for name in self._psd_weighted_sum:
            # Pooled PSD
            self.psd_baseline[name] = (
                self._psd_weighted_sum[name] / self._dof_total[name]
            )
            self.psd_baseline_db[name] = 10.0 * np.log10(
                self.psd_baseline[name] + 1e-30
            )
            self.dof_baseline[name] = self._dof_total[name]

            # Noise floor and prominence
            self.noise_floor[name], self.noise_floor_db[name] = \
                self._compute_noise_floor(self.psd_baseline_db[name])
            self.prominence[name], self.prominence_db[name] = \
                self._compute_prominence(
                    self.psd_baseline[name], self.noise_floor[name]
                )

            self.structural_mask[name] = (
                self.prominence_db[name] >= self.prominence_floor_db
            )
            self.floor_mask[name] = ~self.structural_mask[name]

            # ── Process variance estimation ──
            #
            # For each baseline recording i, compute:
            #   r_i(f) = ln(Ŝ_i(f)) - ln(Ŝ_pooled(f))
            #
            # The variance of r_i has two components:
            #   Var[r_i(f)] = ψ₁(ν_i/2) + Var_process(f)
            #
            # (The ψ₁(ν_bl/2) term is negligible since ν_bl >> ν_i.)
            #
            # So: Var_process(f) = Var_empirical[r_i(f)] - mean(ψ₁(ν_i/2))
            #
            # With only 1 recording, process_var = 0 (fallback to pure F-test).

            log_pooled = np.log(self.psd_baseline[name] + 1e-30)
            n_rec = len(self._per_recording_log_psd[name])

            if n_rec >= 3:
                # Per-recording log-ratios relative to pooled mean
                log_ratios = np.array([
                    lp - log_pooled
                    for lp in self._per_recording_log_psd[name]
                ])
                # Empirical variance per bin
                var_empirical = np.var(log_ratios, axis=0, ddof=1)

                # Expected chi-squared variance per recording
                chi2_vars = np.array([
                    polygamma(1, d / 2.0)
                    for d in self._per_recording_dof[name]
                ])
                mean_chi2_var = np.mean(chi2_vars)

                # Process variance = excess over chi-squared prediction
                # Floor at 0.  With few recordings the per-bin estimate
                # is noisy, but unbiased.  Don't smooth — structural
                # peaks genuinely have higher process variance than the
                # noise floor, and smoothing would erase that.
                self.process_var[name] = np.maximum(
                    var_empirical - mean_chi2_var, 0.0
                )

                # Floor-level process std (broadband mean jitter)
                mean_log_ratios = np.mean(log_ratios, axis=1)  # per-recording means
                floor_emp_var = np.var(mean_log_ratios, ddof=1)
                floor_chi2_var = np.mean(chi2_vars) * self._bin_correlation_factor / len(self.freqs)
                self.floor_process_std[name] = float(np.sqrt(
                    max(0, floor_emp_var - floor_chi2_var)
                ))
            else:
                # Too few recordings to measure process variance
                self.process_var[name] = np.zeros(len(self.freqs))
                self.floor_process_std[name] = 0.0

            # Backward-compat scale (in dB)
            nu_typical = 32
            total_var = (polygamma(1, nu_typical / 2.0) +
                        polygamma(1, self.dof_baseline[name] / 2.0) +
                        self.process_var[name])
            self.scale[name] = np.sqrt(total_var) * 10.0 / np.log(10)

        self._frozen = True
        self._psd_weighted_sum = {}
        self._per_recording_log_psd = {}
        self._per_recording_dof = {}

    # --- Detection ---

    def detect(self, signals: dict[str, np.ndarray]) -> DetectionResult:
        """
        Compare a new recording against the frozen baseline.

        Per-bin variance has two components:
            Var_total(f) = Var_chi2(f) + Var_process(f)

        Chi-squared variance is known from DOF (estimation noise).
        Process variance is measured from baseline recordings (real
        environmental jitter — coupling, temperature, excitation).

        Decomposes z(f) into three physically distinct scales:
          z_floor        = mean(z)              — uniform level shift
          z_shape(f)     = smooth(z) - z_floor  — spectral tilt/curvature
          z_feature(f)   = z - smooth(z)        — peak-scale changes
        """
        if not self._frozen:
            raise RuntimeError("Must freeze() first.")

        p_tier = self.p_fa / 3.0
        median_window = self.analyzer.median_window

        z_all, psd_new_db_all, prom_new_db_all, dof_new_all = {}, {}, {}, {}
        floor_z, floor_p, floor_shift_db = {}, {}, {}
        shape_stat, shape_p, shape_nu_eff = {}, {}, {}
        feature_stat, feature_p, feature_freqs = {}, {}, {}
        triggered, tier_triggered = {}, {}

        for name, signal in signals.items():
            if name not in self.psd_baseline:
                continue

            if len(signal) < self.analyzer.nperseg:
                raise ValueError(
                    f"{name}: signal length {len(signal)} < nperseg "
                    f"{self.analyzer.nperseg}. File too short for this baseline."
                )

            freqs, psd_linear, psd_db, dof_new = self._compute_welch(signal)

            # ── Per-bin log-spectral ratio z-scores ──
            nu_n = dof_new
            nu_b = self.dof_baseline[name]

            log_ratio = np.log(psd_linear / (self.psd_baseline[name] + 1e-30))
            bias = ((digamma(nu_n / 2.0) - np.log(nu_n / 2.0)) -
                    (digamma(nu_b / 2.0) - np.log(nu_b / 2.0)))

            # Two-component variance: chi-squared + process
            var_chi2 = (polygamma(1, nu_n / 2.0) +
                        polygamma(1, nu_b / 2.0))
            var_total = var_chi2 + self.process_var.get(name,
                                                        np.zeros(len(freqs)))
            sigma_per_bin = np.sqrt(var_total)

            z = (log_ratio - bias) / sigma_per_bin

            # Decompose: z = floor + shape + feature
            z_smooth = median_filter(z, size=median_window)
            z_floor_val = float(np.mean(z))
            z_shape_component = z_smooth - z_floor_val
            z_feature_component = z - z_smooth

            # New recording's prominence
            nf_new, nf_new_db = self._compute_noise_floor(psd_db)
            _, prom_new_db = self._compute_prominence(psd_linear, nf_new)

            z_all[name] = z
            psd_new_db_all[name] = psd_db
            prom_new_db_all[name] = prom_new_db
            dof_new_all[name] = dof_new

            # Number of effectively independent bins
            n_eff_raw = len(z) / self._bin_correlation_factor
            n_eff_feature = max(1, int(n_eff_raw / 2))

            # ── Tier 1: Floor (broadband level shift) ──
            #
            # The floor shift has two noise sources:
            # 1. Chi-squared averaging: var ≈ bin_corr / n_bins
            # 2. Process jitter: measured from baseline recordings
            var_floor_chi2 = self._bin_correlation_factor / len(z)
            var_floor_process = self.floor_process_std.get(name, 0.0) ** 2
            var_floor_total = var_floor_chi2 + var_floor_process

            floor_z[name] = z_floor_val / np.sqrt(var_floor_total)
            floor_p[name] = float(2.0 * norm.sf(abs(floor_z[name])))
            floor_shift_db[name] = float(
                10.0 * np.mean(log_ratio) / np.log(10)
            )

            # ── Tier 2: Shape (prominence-weighted spectral change) ──
            w = np.maximum(self.prominence_db[name], 0.0)
            w_sum = w.sum()
            if w_sum < 1e-10:
                w = np.ones(len(z))
                w_sum = w.sum()
            w_norm = w / w_sum

            shape_bin_var = self._bin_correlation_factor / median_window
            T_shape = float(np.sum(w_norm * z_shape_component ** 2))
            T_shape_norm = T_shape / shape_bin_var

            c_shape = float(np.sum(w_norm ** 2))
            nu_eff_shape = max(1.0, 1.0 / (c_shape + 1e-30) /
                               self._bin_correlation_factor)
            shape_stat[name] = T_shape_norm
            shape_p[name] = float(1.0 - chi2.cdf(T_shape_norm, nu_eff_shape))
            shape_nu_eff[name] = nu_eff_shape

            # ── Tier 3: Feature (peak-scale anomalies) ──
            #
            # The median filter removes the broadband process drift, so
            # z_feature is driven primarily by chi-squared noise and any
            # real peak-scale changes.  Process variance is smooth, so
            # it gets absorbed into z_smooth and doesn't inflate z_feature.
            max_zf = float(np.max(np.abs(z_feature_component)))
            feature_stat[name] = max_zf

            p_single = 2.0 * norm.sf(max_zf)
            feature_p[name] = float(min(1.0,
                1.0 - (1.0 - p_single) ** n_eff_feature))

            top_idx = np.argsort(np.abs(z_feature_component))[::-1][:10]
            feature_freqs[name] = [
                {'freq_hz': float(freqs[i]),
                 'z_feature': float(z_feature_component[i]),
                 'psd_new_db': float(psd_db[i]),
                 'psd_baseline_db': float(self.psd_baseline_db[name][i]),
                 'prominence_new_db': float(prom_new_db[i]),
                 'prominence_baseline_db': float(self.prominence_db[name][i])}
                for i in top_idx if abs(z_feature_component[i]) > 2.0
            ]

            # ── Combined decision ──
            tiers = []
            if floor_p[name] < p_tier:
                tiers.append('floor')
            if shape_p[name] < p_tier:
                tiers.append('shape')
            if feature_p[name] < p_tier:
                tiers.append('feature')

            triggered[name] = len(tiers) > 0
            tier_triggered[name] = tiers

        return DetectionResult(
            freqs=self.freqs,
            z_scores=z_all,
            psd_new_db=psd_new_db_all,
            prominence_new_db=prom_new_db_all,
            dof_new=dof_new_all,
            floor_z=floor_z,
            floor_p=floor_p,
            floor_shift_db=floor_shift_db,
            shape_stat=shape_stat,
            shape_p=shape_p,
            shape_nu_eff=shape_nu_eff,
            feature_stat=feature_stat,
            feature_p=feature_p,
            feature_freqs=feature_freqs,
            triggered=triggered,
            tier_triggered=tier_triggered,
        )

    def detection_thresholds(self, name: str) -> dict:
        """Compute approximate detection thresholds for an axis.

        Returns dict with 'floor_threshold_db' and 'feature_threshold'.
        """
        from scipy.stats import norm
        from scipy.special import polygamma

        p_tier = self.p_fa / 3.0
        n_bins = len(self.freqs)

        # Feature threshold (exact)
        n_eff = max(1, int(n_bins / self._bin_correlation_factor / 2))
        p_single = 1 - (1 - p_tier) ** (1.0 / n_eff)
        feature_thresh = float(norm.isf(p_single / 2))

        # Floor threshold in dB (approximate, assumes new DOF ≈ baseline DOF)
        z_crit = float(norm.ppf(1 - p_tier / 2))
        var_chi2 = self._bin_correlation_factor / n_bins
        var_proc = self.floor_process_std.get(name, 0.0) ** 2
        z_floor_thresh = z_crit * np.sqrt(var_chi2 + var_proc)

        nu_b = self.dof_baseline[name]
        pv = self.process_var.get(name, np.zeros(n_bins))
        sigma_avg = float(np.sqrt(2.0 * polygamma(1, nu_b / 2.0) + np.mean(pv)))
        floor_thresh_db = float(10.0 / np.log(10) * z_floor_thresh * sigma_avg)

        return {'floor_threshold_db': floor_thresh_db, 'feature_threshold': feature_thresh}

    # --- Serialization ---

    def save(self, path: str):
        data = {
            'type': 'SpectralFTest',
            'analyzer': self.analyzer.to_dict(),
            'p_fa': self.p_fa,
            'prominence_floor_db': self.prominence_floor_db,
            'n_recordings': self._n_recordings,
            'frozen': self._frozen,
            'freqs': self.freqs.tolist() if self.freqs is not None else None,
            'axes': {},
        }
        for name in self.psd_baseline:
            thresholds = self.detection_thresholds(name)
            data['axes'][name] = {
                'psd_baseline': self.psd_baseline[name].tolist(),
                'dof_baseline': int(self.dof_baseline[name]),
                'noise_floor': self.noise_floor[name].tolist(),
                'prominence': self.prominence[name].tolist(),
                'process_var': self.process_var[name].tolist(),
                'floor_process_std': float(self.floor_process_std[name]),
                'floor_threshold_db': thresholds['floor_threshold_db'],
                'feature_threshold': thresholds['feature_threshold'],
            }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> 'SpectralBaseline':
        with open(path) as f:
            data = json.load(f)

        # Handle legacy baselines (old MAD-based format)
        if 'type' not in data or data['type'] != 'SpectralFTest':
            return cls._load_legacy(data)

        analyzer = SpectralAnalyzer.from_dict(data['analyzer'])
        bl = cls(analyzer=analyzer, p_fa=data['p_fa'],
                 prominence_floor_db=data.get('prominence_floor_db', 3.0))
        bl._n_recordings = data['n_recordings']
        bl._frozen = data['frozen']
        bl.freqs = np.array(data['freqs']) if data['freqs'] else None

        for name, entry in data['axes'].items():
            psd = np.array(entry['psd_baseline'])
            bl.psd_baseline[name] = psd
            bl.psd_baseline_db[name] = 10.0 * np.log10(psd + 1e-30)
            bl.dof_baseline[name] = entry['dof_baseline']
            bl.noise_floor[name] = np.array(entry['noise_floor'])
            bl.noise_floor_db[name] = 10.0 * np.log10(
                bl.noise_floor[name] + 1e-30)
            bl.prominence[name] = np.array(entry['prominence'])
            bl.prominence_db[name] = 10.0 * np.log10(
                bl.prominence[name] + 1e-30)
            bl.structural_mask[name] = (
                bl.prominence_db[name] >= bl.prominence_floor_db
            )
            bl.floor_mask[name] = ~bl.structural_mask[name]

            # Process variance
            if 'process_var' in entry:
                bl.process_var[name] = np.array(entry['process_var'])
                bl.floor_process_std[name] = entry['floor_process_std']
            else:
                bl.process_var[name] = np.zeros(len(psd))
                bl.floor_process_std[name] = 0.0

            # Backward-compat scale (includes process variance)
            nu_typical = 32
            total_var = (polygamma(1, nu_typical / 2.0) +
                        polygamma(1, bl.dof_baseline[name] / 2.0) +
                        bl.process_var[name])
            bl.scale[name] = np.sqrt(total_var) * 10.0 / np.log(10)

        return bl

    @classmethod
    def _load_legacy(cls, data: dict) -> 'SpectralBaseline':
        """Load old MAD-based baseline.json and convert to F-test format.

        Uses the stored center (median PSD) as the baseline PSD and
        estimates DOF from the scale (MAD) values.
        """
        analyzer = SpectralAnalyzer.from_dict(data['analyzer'])
        bl = cls(analyzer=analyzer, p_fa=data['p_fa'])
        bl._n_recordings = data.get('n_phase1_frames', 1)
        bl._frozen = True
        bl.freqs = np.array(data['freqs']) if data['freqs'] else None

        for name, entry in data['axes'].items():
            center_db = np.array(entry['center'])
            psd_linear = 10.0 ** (center_db / 10.0)
            bl.psd_baseline[name] = psd_linear
            bl.psd_baseline_db[name] = center_db

            # Estimate DOF from scale: σ_dB ≈ 10·log₁₀(e)·√(2/ν)
            # → ν ≈ 2·(10·log₁₀(e))² / σ_dB²
            scale_db = np.array(entry['scale'])
            median_scale = np.median(scale_db)
            estimated_dof = int(2.0 * (10.0 * np.log10(np.e))**2 /
                                (median_scale**2 + 1e-10))
            estimated_dof = max(estimated_dof, 2)
            bl.dof_baseline[name] = estimated_dof

            nf_linear, nf_db = bl._compute_noise_floor(center_db)
            bl.noise_floor[name] = nf_linear
            bl.noise_floor_db[name] = nf_db
            prom, prom_db = bl._compute_prominence(psd_linear, nf_linear)
            bl.prominence[name] = prom
            bl.prominence_db[name] = prom_db
            bl.structural_mask[name] = (prom_db >= bl.prominence_floor_db)
            bl.floor_mask[name] = ~bl.structural_mask[name]
            bl.scale[name] = scale_db
            bl.process_var[name] = np.zeros(len(psd_linear))
            bl.floor_process_std[name] = 0.0

        print(f"  Note: loaded legacy MAD-based baseline, "
              f"estimated DOF from scale. Re-train recommended.")
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
    """
    Plot new data vs baseline with F-test detection results.

    5 rows per axis:
      0: PSD overlay (new vs baseline ± theoretical F-interval)
      1: Log-spectral z-scores with floor/structural classification
      2: Feature z-scores (z - smooth trend) with top anomalies marked
      3: Prominence comparison (baseline vs new)
      4: Summary text
    """
    import matplotlib.pyplot as plt

    axes_names = list(result.z_scores.keys())
    n_axes = len(axes_names)
    colors = ['#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12', '#1abc9c']

    fig, axs = plt.subplots(5, n_axes, figsize=(8 * n_axes, 26))
    if n_axes == 1:
        axs = axs[:, np.newaxis]
    if title:
        fig.suptitle(title, fontsize=16, y=0.995)

    freqs = result.freqs
    mask = freqs > 0.5
    median_window = baseline.analyzer.median_window

    for i, name in enumerate(axes_names):
        color = colors[i % len(colors)]
        z = result.z_scores[name]
        psd_new = result.psd_new_db[name]
        psd_bl = baseline.psd_baseline_db[name]
        nu_n = result.dof_new[name]
        nu_b = baseline.dof_baseline[name]

        # Theoretical 95% F-interval
        from scipy.stats import f as f_dist
        f_lo = f_dist.ppf(0.025, nu_n, nu_b)
        f_hi = f_dist.ppf(0.975, nu_n, nu_b)
        band_lo = psd_bl + 10.0 * np.log10(f_lo + 1e-30)
        band_hi = psd_bl + 10.0 * np.log10(f_hi + 1e-30)

        # ─── Row 0: PSD overlay ───
        ax = axs[0, i]
        ax.semilogx(freqs[mask], psd_new[mask], color=color, alpha=0.8,
                     lw=0.8, label='New recording')
        ax.semilogx(freqs[mask], psd_bl[mask], 'k-', alpha=0.6, lw=1,
                     label='Baseline')
        ax.fill_between(freqs[mask], band_lo[mask], band_hi[mask],
                        alpha=0.15, color='gray',
                        label=f'95% F-interval (DOF {nu_n} vs {nu_b})')
        ax.set_title(f'{name} — PSD: New vs Baseline')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('PSD (dB)')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # ─── Row 1: Z-scores with classification ───
        ax = axs[1, i]
        sm = baseline.structural_mask[name] & mask
        fm = baseline.floor_mask[name] & mask
        ax.semilogx(freqs[fm], z[fm], '.', color='gray', ms=2, alpha=0.3,
                     label='Floor bins', rasterized=True)
        ax.semilogx(freqs[sm], z[sm], '.', color=color, ms=3, alpha=0.5,
                     label='Structural bins', rasterized=True)
        ax.axhline(0, color='k', alpha=0.3)
        ax.axhline(3, color='r', ls='--', alpha=0.3, label='±3σ')
        ax.axhline(-3, color='r', ls='--', alpha=0.3)
        shift = result.floor_shift_db[name]
        fp = result.floor_p[name]
        ax.set_title(f'{name} — Z-scores | Floor: {"+" if shift>=0 else ""}{shift:.1f} dB (p={fp:.3f})')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Z-score')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # ─── Row 2: Feature z-scores ───
        ax = axs[2, i]
        z_smooth = median_filter(z, size=median_window)
        z_feature = z - z_smooth
        ax.semilogx(freqs[mask], z_feature[mask], color=color, alpha=0.5, lw=0.5)
        ax.axhline(0, color='k', alpha=0.3)

        top_features = result.feature_freqs[name][:5]
        for feat in top_features:
            fidx = np.argmin(np.abs(freqs - feat['freq_hz']))
            mc = 'red' if feat['z_feature'] > 0 else 'blue'
            marker = 'v' if feat['z_feature'] > 0 else '^'
            ax.plot(freqs[fidx], z_feature[fidx], marker, color=mc, ms=8, zorder=5)
            ax.annotate(f'{feat["freq_hz"]:.1f} Hz\nz={feat["z_feature"]:+.1f}',
                       (freqs[fidx], z_feature[fidx]), fontsize=6,
                       textcoords='offset points',
                       xytext=(5, 5 if feat['z_feature'] > 0 else -12))

        fstat = result.feature_stat[name]
        fep = result.feature_p[name]
        ax.set_title(f'{name} — Feature Z | max={fstat:.1f} (p={fep:.3f})')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Feature Z-score')
        ax.grid(True, alpha=0.3, which='both')

        # ─── Row 3: Prominence comparison ───
        ax = axs[3, i]
        ax.semilogx(freqs[mask], baseline.prominence_db[name][mask], 'k-',
                     alpha=0.5, lw=1, label='Baseline prominence')
        ax.semilogx(freqs[mask], result.prominence_new_db[name][mask],
                     color=color, alpha=0.7, lw=0.8, label='New prominence')
        ax.axhline(baseline.prominence_floor_db, color='orange', ls=':',
                    alpha=0.5, label=f'Structural threshold ({baseline.prominence_floor_db} dB)')
        ax.fill_between(freqs[mask],
                        np.minimum(baseline.prominence_db[name][mask],
                                   result.prominence_new_db[name][mask]),
                        np.maximum(baseline.prominence_db[name][mask],
                                   result.prominence_new_db[name][mask]),
                        alpha=0.15, color=color)
        ax.set_title(f'{name} — Prominence')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Prominence (dB)')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # ─── Row 4: Summary ───
        ax = axs[4, i]
        ax.axis('off')
        tiers = result.tier_triggered[name]
        status = f"⚠  ANOMALY [{', '.join(tiers)}]" if tiers else "✓  Normal"
        sc = '#e74c3c' if tiers else '#27ae60'
        n_struct = baseline.structural_mask[name].sum()
        n_floor = baseline.floor_mask[name].sum()

        lines = [
            f"{'─' * 50}",
            f"  {name}: {status}",
            f"{'─' * 50}",
            f"  DOF: baseline={nu_b}  new={nu_n}",
            f"  Bins: {len(z)} total, {n_struct} structural, {n_floor} floor",
            "",
            f"  Tier 1 (Floor):   z={result.floor_z[name]:+.1f}  "
            f"shift={shift:+.1f} dB  p={fp:.4f}  "
            f"{'⚠ TRIGGERED' if 'floor' in tiers else '✓'}",
            f"  Tier 2 (Shape):   T={result.shape_stat[name]:.2f}  "
            f"ν_eff={result.shape_nu_eff[name]:.0f}  p={result.shape_p[name]:.4f}  "
            f"{'⚠ TRIGGERED' if 'shape' in tiers else '✓'}",
            f"  Tier 3 (Feature): max|z|={fstat:.1f}  p={fep:.4f}  "
            f"{'⚠ TRIGGERED' if 'feature' in tiers else '✓'}",
        ]
        if top_features:
            lines += ["", "  Top feature changes:"]
            for feat in top_features[:5]:
                direction = "NEW/UP" if feat['z_feature'] > 0 else "GONE/DOWN"
                lines.append(
                    f"    {feat['freq_hz']:8.1f} Hz  z={feat['z_feature']:+.1f}  "
                    f"prom: {feat['prominence_baseline_db']:.1f}→"
                    f"{feat['prominence_new_db']:.1f} dB  ({direction})"
                )
        ax.text(0.02, 0.95, '\n'.join(lines), transform=ax.transAxes,
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
    Visualize the learned baseline.

    3 rows per axis:
      Row 0: Pooled PSD with noise floor and structural classification
      Row 1: Prominence profile (structural vs noise-floor bins)
      Row 2: Detection sensitivity (z-score per 1 dB change, given DOF)
    """
    import matplotlib.pyplot as plt

    axes_names = list(baseline.psd_baseline.keys())
    n_axes = len(axes_names)
    colors = ['#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12', '#1abc9c']
    freqs = baseline.freqs
    mask = freqs > 0.5

    fig, axs = plt.subplots(3, n_axes, figsize=(7 * n_axes, 16))
    if n_axes == 1:
        axs = axs[:, np.newaxis]
    fig.suptitle(title, fontsize=16, y=0.99)

    for i, name in enumerate(axes_names):
        color = colors[i % len(colors)]
        psd_db = baseline.psd_baseline_db[name]
        nf_db = baseline.noise_floor_db[name]
        prom_db = baseline.prominence_db[name]
        dof = baseline.dof_baseline[name]

        # Row 0: PSD with floor
        ax = axs[0, i]
        ax.semilogx(freqs[mask], psd_db[mask], color=color, alpha=0.8, lw=0.8)
        ax.semilogx(freqs[mask], nf_db[mask], 'k--', alpha=0.5, lw=1,
                     label='Noise floor')
        sm = baseline.structural_mask[name] & mask
        if sm.any():
            ax.fill_between(freqs[mask], psd_db[mask], nf_db[mask],
                           where=sm[mask], alpha=0.15, color=color,
                           label='Structural content')
        n_struct = baseline.structural_mask[name].sum()
        ax.set_title(f'{name} — Baseline PSD (DOF={dof}, {n_struct} structural bins)')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('PSD (dB)')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # Row 1: Prominence
        ax = axs[1, i]
        ax.semilogx(freqs[mask], prom_db[mask], color=color, alpha=0.7, lw=0.8)
        ax.axhline(baseline.prominence_floor_db, color='orange', ls=':',
                    alpha=0.7,
                    label=f'Threshold ({baseline.prominence_floor_db} dB)')
        ax.fill_between(freqs[mask], 0, prom_db[mask],
                        where=prom_db[mask] >= baseline.prominence_floor_db,
                        alpha=0.15, color=color)
        ax.set_title(f'{name} — Prominence')
        ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Prominence (dB)')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

        # Row 2: Sensitivity (z per 1 dB change)
        ax = axs[2, i]
        nu_n_typical = 32
        sigma_bin = np.sqrt(
            polygamma(1, nu_n_typical / 2.0) +
            polygamma(1, dof / 2.0)
        )
        z_per_1db = (0.1 * np.log(10)) / sigma_bin
        ax.semilogx(freqs[mask], np.full(mask.sum(), z_per_1db),
                     'k-', lw=1, alpha=0.7,
                     label=f'Per-bin: z={z_per_1db:.2f} per 1dB (DOF {nu_n_typical} vs {dof})')
        ax.set_title(f'{name} — Detection sensitivity')
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Z-score per 1 dB change')
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3, which='both')

    plt.tight_layout()
    if save_path: plt.savefig(save_path, dpi=150, bbox_inches='tight')
    if show: plt.show()
    plt.close(fig)
    return fig


def plot_summary(results: list[tuple[str, DetectionResult]],
                 baseline: SpectralBaseline,
                 save_path: str = None, show: bool = False):
    """
    Summary dashboard of all monitored files.

    Top row:    Floor-shift vs Feature-stat scatter per axis
    Middle row: Per-file z-score heatmap per axis
    Bottom row: Per-file feature-z heatmap per axis
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    axes_names = list(baseline.psd_baseline.keys())
    n_axes = len(axes_names)
    colors = ['#e74c3c', '#2ecc71', '#3498db', '#9b59b6', '#f39c12', '#1abc9c']

    filenames = [Path(fn).stem for fn, _ in results]
    short_names = []
    for fn in filenames:
        parts = fn.split('_')
        if len(parts) >= 4:
            short_names.append('_'.join(parts[-2:]))
        else:
            short_names.append(fn[:20])

    freqs = baseline.freqs
    mask = freqs > 0.1
    freqs_masked = freqs[mask]
    n_files = len(results)

    fig, axs = plt.subplots(3, n_axes,
                            figsize=(7 * n_axes, 4 + n_files * 0.4 + 6),
                            gridspec_kw={'height_ratios': [
                                3, max(n_files * 0.3, 2),
                                max(n_files * 0.3, 2)]})
    if n_axes == 1:
        axs = axs[:, np.newaxis]

    fig.suptitle(f'Monitor Summary — {n_files} files', fontsize=16, y=0.99)

    for i, name in enumerate(axes_names):
        color = colors[i % len(colors)]

        any_trig = [r.triggered[name] for _, r in results]
        floor_shifts = [r.floor_shift_db[name] for _, r in results]
        feat_stats = [r.feature_stat[name] for _, r in results]
        floor_ps = [r.floor_p[name] for _, r in results]
        feat_ps = [r.feature_p[name] for _, r in results]

        # ─── Row 0: Floor shift vs Feature stat scatter ───
        ax = axs[0, i]
        for j in range(n_files):
            if any_trig[j]:
                ax.scatter(floor_shifts[j], feat_stats[j], c='#e74c3c',
                          s=80, marker='x', linewidths=2, zorder=3)
            else:
                ax.scatter(floor_shifts[j], feat_stats[j], c=color,
                          edgecolors='#27ae60', linewidths=1.5, s=60,
                          marker='o', zorder=3)
            ax.annotate(short_names[j], (floor_shifts[j], feat_stats[j]),
                       fontsize=5, alpha=0.7,
                       textcoords='offset points', xytext=(4, 4))

        ax.axvline(0, color='gray', ls='-', alpha=0.3)

        # Detection threshold lines
        thresholds = baseline.detection_thresholds(name)
        ft_db = thresholds['floor_threshold_db']
        feat_t = thresholds['feature_threshold']
        ax.axvline(-ft_db, color='red', ls='--', alpha=0.4, lw=1)
        ax.axvline(ft_db, color='red', ls='--', alpha=0.4, lw=1, label=f'Floor \u00b1{ft_db:.1f} dB')
        ax.axhline(feat_t, color='orange', ls='--', alpha=0.4, lw=1, label=f'Feature {feat_t:.1f}')
        ax.legend(fontsize=6, loc='upper left')

        ax.set_xlabel('Floor shift (dB)')
        ax.set_ylabel('Feature max |z|')
        ax.set_title(f'{name} — Detection Space')
        ax.grid(True, alpha=0.3)

        # ─── Row 1: Z-score heatmap ───
        ax = axs[1, i]
        z_matrix = np.array([r.z_scores[name][mask] for _, r in results])
        vmax = min(np.percentile(np.abs(z_matrix), 98), 20)
        norm_z = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

        im = ax.pcolormesh(freqs_masked, range(n_files), z_matrix,
                          norm=norm_z, cmap='RdBu_r', shading='auto')
        ax.set_xscale('log')
        ax.set_yticks(range(n_files))
        ax.set_yticklabels(short_names, fontsize=6)
        ax.set_xlabel('Frequency (Hz)')
        ax.set_title(f'{name} — Z-scores across files')
        plt.colorbar(im, ax=ax, label='z-score', shrink=0.8)

        for j in range(n_files):
            if any_trig[j]:
                ax.text(-0.01, j, '⚠', transform=ax.get_yaxis_transform(),
                       fontsize=8, ha='right', va='center', color='red')

        # ─── Row 2: Feature-z heatmap ───
        ax = axs[2, i]
        pz_matrix = np.array([
            (r.z_scores[name] - median_filter(r.z_scores[name],
             size=baseline.analyzer.median_window))[mask]
            for _, r in results])

        vmax_p = min(np.percentile(np.abs(pz_matrix), 98), 15)
        norm_p = TwoSlopeNorm(vmin=-vmax_p, vcenter=0, vmax=vmax_p)

        im2 = ax.pcolormesh(freqs_masked, range(n_files), pz_matrix,
                           norm=norm_p, cmap='RdBu_r', shading='auto')
        ax.set_xscale('log')
        ax.set_yticks(range(n_files))
        ax.set_yticklabels(short_names, fontsize=6)
        ax.set_xlabel('Frequency (Hz)')
        ax.set_title(f'{name} — Feature Z across files (new/gone peaks)')
        plt.colorbar(im2, ax=ax, label='feature z', shrink=0.8)

        for j in range(n_files):
            _, r_j = results[j]
            if r_j.feature_p.get(name, 1.0) < baseline.p_fa / 3:
                ax.text(-0.01, j, '⚠', transform=ax.get_yaxis_transform(),
                       fontsize=8, ha='right', va='center', color='red')

    plt.tight_layout()
    if save_path: plt.savefig(save_path, dpi=150, bbox_inches='tight')
    if show: plt.show()
    plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# Training and checking
# ---------------------------------------------------------------------------

def train_from_folder(baseline_folder: str, analyzer: SpectralAnalyzer,
                      p_fa: float = 0.01, train_fraction: float = 1.0,
                      prominence_floor_db: float = 3.0,
                      verbose: bool = True) -> SpectralBaseline:
    """
    Learn a baseline from all CSVs in a folder.

    Each CSV is one recording.  Its full-length Welch PSD is pooled
    into the baseline, weighted by DOF.  More data = more DOF =
    tighter detection — correctly.

    Note: train_fraction is accepted for CLI compatibility but no longer
    used (the F-test model doesn't need a separate calibration phase).
    """
    files = load_folder(baseline_folder)
    if verbose:
        print(f"Found {len(files)} CSV files in {baseline_folder}")

    baseline = SpectralBaseline(analyzer=analyzer, p_fa=p_fa,
                                prominence_floor_db=prominence_floor_db)

    n_loaded = 0
    for filename, fs, signals in files:
        n = len(next(iter(signals.values())))
        if n < analyzer.nperseg:
            if verbose:
                print(f"  {filename}: {n/fs:.1f}s — skipped (shorter than nperseg)")
            continue
        if verbose:
            print(f"  {filename}: {n/fs:.1f}s")
        baseline.accumulate(signals)
        n_loaded += 1

    if n_loaded < 1:
        raise ValueError(
            f"No recordings loaded (need at least 1 that's >= nperseg samples). "
            f"Add more baseline files or use shorter nperseg.")

    baseline.freeze()

    if verbose:
        print(f"\nBaseline frozen. {baseline.n_bins} frequency bins.")
        print(f"Recordings pooled: {n_loaded}")
        for name in baseline.psd_baseline:
            dof = baseline.dof_baseline[name]
            n_struct = baseline.structural_mask[name].sum()
            n_floor = baseline.floor_mask[name].sum()
            print(f"\n  {name}:")
            print(f"    DOF: {dof}")
            print(f"    Structural bins: {n_struct}")
            print(f"    Floor bins: {n_floor}")
            print(f"    Peak prominence: {baseline.prominence_db[name].max():.1f} dB")

    return baseline


def check_folder(monitor_folder: str, baseline: SpectralBaseline,
                 output_dir: str = None, verbose: bool = True
                 ) -> list[tuple[str, DetectionResult]]:
    """
    Check all CSVs in a folder against a learned baseline.
    Saves per-file comparison plots and a summary dashboard to output_dir.
    """
    files = load_folder(monitor_folder)

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
                tiers = result.tier_triggered[name]
                ax_s = f"ANOMALY [{', '.join(tiers)}]" if tiers else "normal"
                print(f"  {name}: {ax_s}")
                print(f"    Floor:   shift={result.floor_shift_db[name]:+.1f} dB  "
                      f"p={result.floor_p[name]:.4f}  "
                      f"{'⚠' if 'floor' in tiers else '✓'}")
                print(f"    Shape:   T={result.shape_stat[name]:.2f}  "
                      f"p={result.shape_p[name]:.4f}  "
                      f"{'⚠' if 'shape' in tiers else '✓'}")
                print(f"    Feature: max|z|={result.feature_stat[name]:.1f}  "
                      f"p={result.feature_p[name]:.4f}  "
                      f"{'⚠' if 'feature' in tiers else '✓'}")
                for feat in result.feature_freqs.get(name, [])[:3]:
                    print(f"    → {feat['freq_hz']:8.1f} Hz  "
                          f"z={feat['z_feature']:+.1f}")

        save = str(Path(output_dir) / f"{Path(filename).stem}_comparison.png")
        plot_comparison(baseline, result, frame,
                       title=f'{filename} vs Baseline', save_path=save)
        if verbose:
            print(f"  Plot: {save}")

        results.append((filename, result))

    if verbose:
        n_anom = sum(1 for _, r in results if any(r.triggered.values()))
        print(f"\n{'='*60}")
        print(f"Summary: {n_anom} / {len(results)} files flagged")

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
    """
    import matplotlib.pyplot as plt

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    axes_names = list(baseline.psd_baseline.keys())

    vectors = []
    labels = []
    sources = []
    floor_shifts = {name: [] for name in axes_names}
    feat_stats = {name: [] for name in axes_names}
    any_triggered = []

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

            z_parts = []
            pz_parts = []
            for name in axes_names:
                z_parts.append(result.z_scores[name])
                z_sm = median_filter(result.z_scores[name],
                                     size=baseline.analyzer.median_window)
                pz_parts.append(result.z_scores[name] - z_sm)

            feature = np.concatenate(z_parts + pz_parts)
            vectors.append(feature)
            labels.append(Path(filename).stem)
            sources.append(source_label)

            for name in axes_names:
                floor_shifts[name].append(result.floor_shift_db[name])
                feat_stats[name].append(result.feature_stat[name])

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

    X = np.array(vectors)
    n_features = X.shape[1]

    if verbose:
        print(f"\n{n_files} files, {n_features} features per file")
        n_bl = sources.count('baseline')
        n_mon = sources.count('monitor')
        print(f"  Baseline: {n_bl} files")
        print(f"  Monitor: {n_mon} files")

    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    from sklearn.preprocessing import StandardScaler
    X_scaled = StandardScaler().fit_transform(X)

    if method == 'umap':
        try:
            import umap
            reducer = umap.UMAP(n_components=2,
                               n_neighbors=min(15, n_files - 1),
                               min_dist=0.1, metric='euclidean',
                               random_state=42)
            embedding = reducer.fit_transform(X_scaled)
            method_label = 'UMAP'
        except ImportError:
            print("  umap-learn not installed, falling back to t-SNE")
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

    source_arr = np.array(sources)
    trig_arr = np.array(any_triggered)

    # ── Plot 1: Main map ──
    fig, axs = plt.subplots(1, 3, figsize=(24, 8))
    fig.suptitle(f'Spectral Map — {method_label}', fontsize=16, y=1.02)

    ax = axs[0]
    bl_mask = source_arr == 'baseline'
    mon_mask = source_arr == 'monitor'

    if bl_mask.any():
        ax.scatter(embedding[bl_mask, 0], embedding[bl_mask, 1],
                  c='#95a5a6', s=40, alpha=0.6, label='Baseline', zorder=2)
    if mon_mask.any():
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

    for j in range(n_files):
        ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.7,
                   textcoords='offset points', xytext=(4, 4))

    ax.set_title('By Source')
    ax.legend(fontsize=8); ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1'); ax.set_ylabel('Component 2')

    # Colored by floor shift
    ax = axs[1]
    mean_floor = np.mean([floor_shifts[name] for name in axes_names], axis=0)
    vmax_f = max(abs(np.percentile(mean_floor, 5)),
                 abs(np.percentile(mean_floor, 95)), 1.0)
    sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                   c=mean_floor, cmap='RdBu_r', s=60, alpha=0.8,
                   edgecolors='white', linewidths=0.5,
                   vmin=-vmax_f, vmax=vmax_f)
    plt.colorbar(sc, ax=ax, label='Floor shift (dB)', shrink=0.8)
    for j in range(n_files):
        ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.7,
                   textcoords='offset points', xytext=(4, 4))
    ax.set_title('By Floor Shift (dB)')
    ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1'); ax.set_ylabel('Component 2')

    # Colored by feature stat
    ax = axs[2]
    mean_feat = np.mean([feat_stats[name] for name in axes_names], axis=0)
    sc = ax.scatter(embedding[:, 0], embedding[:, 1],
                   c=mean_feat, cmap='RdYlGn_r', s=60, alpha=0.8,
                   edgecolors='white', linewidths=0.5,
                   vmin=0, vmax=max(5, np.percentile(mean_feat, 95)))
    plt.colorbar(sc, ax=ax, label='Feature max |z|', shrink=0.8)
    for j in range(n_files):
        ax.annotate(labels[j], embedding[j], fontsize=4, alpha=0.7,
                   textcoords='offset points', xytext=(4, 4))
    ax.set_title('By Feature Stat (max |z|)')
    ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1'); ax.set_ylabel('Component 2')

    plt.tight_layout()
    main_path = str(Path(output_dir) / f'{method}_spectral_map.png')
    plt.savefig(main_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    if verbose:
        print(f"\nSaved: {main_path}")

    # ── Plot 2: Annotated clusters ──
    fig3, ax3 = plt.subplots(1, 1, figsize=(10, 8))
    fig3.suptitle(f'Spectral Map — Annotated', fontsize=14)

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

    freqs = baseline.freqs
    n_bins = len(freqs)
    for j in range(n_files):
        if not any_triggered[j]:
            ax3.annotate(labels[j], embedding[j], fontsize=5, alpha=0.5,
                        textcoords='offset points', xytext=(4, 2))
            continue

        z_all = vectors[j][:n_bins * len(axes_names)]
        z_matrix = z_all.reshape(len(axes_names), n_bins)
        max_z_per_bin = np.max(np.abs(z_matrix), axis=0)
        top_bins = np.argsort(max_z_per_bin)[::-1][:3]

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

    ax3.legend(fontsize=8); ax3.grid(True, alpha=0.2)
    ax3.set_xlabel('Component 1'); ax3.set_ylabel('Component 2')

    plt.tight_layout()
    ann_path = str(Path(output_dir) / f'{method}_spectral_map_annotated.png')
    plt.savefig(ann_path, dpi=150, bbox_inches='tight')
    plt.close(fig3)

    if verbose:
        print(f"Saved: {ann_path}")

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
    """
    import matplotlib.pyplot as plt
    from sklearn.cluster import HDBSCAN
    from scipy.spatial import ConvexHull

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        embedding, labels, sources, vectors, any_triggered = spectral_map(
            baseline, baseline_folder, monitor_folder,
            output_dir=tmp, method=method, verbose=verbose
        )

    source_arr = np.array(sources)
    trig_arr = np.array(any_triggered)
    n_files = len(labels)

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

    baseline_cluster_ids = set()
    for c in range(n_clusters):
        members = np.where(cluster_labels == c)[0]
        n_bl = np.sum(source_arr[members] == 'baseline')
        if n_bl > len(members) * 0.3:
            baseline_cluster_ids.add(c)

    if verbose:
        print(f"\n  Baseline clusters: {baseline_cluster_ids or 'none identified'}")

    structurally_anomalous = np.zeros(n_files, dtype=bool)
    for j in range(n_files):
        if source_arr[j] == 'baseline':
            continue
        if cluster_labels[j] == -1:
            structurally_anomalous[j] = True
        elif cluster_labels[j] not in baseline_cluster_ids:
            structurally_anomalous[j] = True

    if verbose:
        n_mon = np.sum(source_arr == 'monitor')
        n_struct_anom = np.sum(structurally_anomalous)
        print(f"  Structurally anomalous: {n_struct_anom} / {n_mon} monitor files")

    # ── Plot ──
    fig, axs = plt.subplots(1, 2, figsize=(20, 9))
    fig.suptitle(f'Spectral Clustering — HDBSCAN ({n_clusters} clusters)',
                 fontsize=16, y=1.02)

    ax = axs[0]
    cluster_cmap = plt.cm.Set2 if n_clusters <= 8 else plt.cm.tab20
    cluster_colors = cluster_cmap(np.linspace(0, 0.9, max(n_clusters, 1)))

    noise_mask = cluster_labels == -1
    if noise_mask.any():
        ax.scatter(embedding[noise_mask, 0], embedding[noise_mask, 1],
                  c='#d5d8dc', s=20, alpha=0.4, marker='.', label='Noise',
                  zorder=1)

    for c in range(n_clusters):
        members = np.where(cluster_labels == c)[0]
        color = cluster_colors[c]
        is_bl = c in baseline_cluster_ids
        label = f'Cluster {c} {"(baseline)" if is_bl else ""}'
        ax.scatter(embedding[members, 0], embedding[members, 1],
                  c=[color], s=50, alpha=0.8, label=label,
                  edgecolors='white', linewidths=0.5, zorder=3)
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
    ax.legend(fontsize=7, loc='best'); ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1'); ax.set_ylabel('Component 2')

    # Panel 2: boundary
    ax = axs[1]
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

    bl_mask = source_arr == 'baseline'
    if bl_mask.any():
        ax.scatter(embedding[bl_mask, 0], embedding[bl_mask, 1],
                  c='#95a5a6', s=30, alpha=0.5, label='Baseline', zorder=2)

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

    freqs = baseline.freqs
    axes_names = list(baseline.psd_baseline.keys())
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
            details.append(
                f"{freqs[b]:.0f}Hz ({axes_names[best_ax_idx]} z={z_val:+.0f})")

        annotation = f"{labels[j]}\n" + "\n".join(details)
        ax.annotate(annotation, embedding[j], fontsize=5,
                   textcoords='offset points', xytext=(8, 8),
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow',
                            alpha=0.8, edgecolor='gray'),
                   arrowprops=dict(arrowstyle='->', color='gray', lw=0.5))

    ax.set_title('Baseline Boundary — Inside vs Outside')
    ax.legend(fontsize=8); ax.grid(True, alpha=0.2)
    ax.set_xlabel('Component 1'); ax.set_ylabel('Component 2')

    plt.tight_layout()
    cluster_path = str(Path(output_dir) / f'{method}_spectral_clusters.png')
    plt.savefig(cluster_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    if verbose:
        print(f"\nSaved: {cluster_path}")

    if verbose:
        print(f"\n{'='*60}")
        print(f"Classification:")
        print(f"{'='*60}")
        for j in range(n_files):
            if source_arr[j] == 'baseline':
                continue
            cluster_id = cluster_labels[j]
            if structurally_anomalous[j]:
                cluster_str = (f"cluster {cluster_id}"
                              if cluster_id >= 0 else "noise")
                print(f"  ⚠ {labels[j]:40s}  OUTSIDE  ({cluster_str})")
            else:
                print(f"  ✓ {labels[j]:40s}  inside baseline "
                      f"(cluster {cluster_id})")

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
        description='Spectral Fingerprint Toolkit (F-test model)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. %(prog)s init   my_project --fs 1844.3
  2. (put known-good CSVs in my_project/baseline/)
  3. %(prog)s train  my_project
  4. (put new CSVs in my_project/monitor/)
  5. %(prog)s check  my_project

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
    p.add_argument('--prominence-floor', type=float, default=3.0,
                   help='Prominence threshold for structural bins (dB)')

    # train
    p = sub.add_parser('train', help='Learn baseline from project/baseline/')
    p.add_argument('project', help='Project directory')
    p.add_argument('--train-fraction', type=float, default=1.0,
                   help='(legacy, ignored — all data is pooled)')

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
    p.add_argument('--method',
                   choices=['umap', 'tsne', 'pca', 'all'], default='umap',
                   help='Dimensionality reduction method')

    # cluster
    p = sub.add_parser('cluster',
                       help='HDBSCAN clustering — find baseline boundary')
    p.add_argument('project', help='Project directory')
    p.add_argument('--method', choices=['umap', 'tsne', 'pca'], default='tsne')
    p.add_argument('--min-cluster-size', type=int, default=5)

    # plot
    p = sub.add_parser('plot',
                       help='Plot spectral analysis of a single CSV')
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

        config = {
            'fs': args.fs, 'nperseg': args.nperseg,
            'median_window': args.median_window, 'p_fa': args.p_fa,
            'prominence_floor_db': args.prominence_floor,
        }
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
            print(f"Error: {cfg_path} not found. Run `init` first.")
            sys.exit(1)
        with open(cfg_path) as f:
            cfg = json.load(f)

        analyzer = SpectralAnalyzer(
            fs=cfg['fs'], nperseg=cfg['nperseg'],
            median_window=cfg['median_window'])
        baseline = train_from_folder(
            str(proj / 'baseline'), analyzer,
            p_fa=cfg['p_fa'],
            prominence_floor_db=cfg.get('prominence_floor_db', 3.0))

        bl_path = proj / 'baseline.json'
        baseline.save(str(bl_path))
        print(f"\nSaved: {bl_path}")
        print(f"Next: python {sys.argv[0]} check {args.project}")

    elif args.command == 'check':
        proj = Path(args.project)
        bl_path = proj / 'baseline.json'
        if not bl_path.exists():
            print(f"Error: {bl_path} not found. Run `train` first.")
            sys.exit(1)

        baseline = SpectralBaseline.load(str(bl_path))
        out = str(proj / 'results')
        check_folder(str(proj / 'monitor'), baseline, output_dir=out)

    elif args.command == 'show':
        proj = Path(args.project)
        bl_path = proj / 'baseline.json'
        if not bl_path.exists():
            print(f"Error: {bl_path} not found. Run `train` first.")
            sys.exit(1)

        baseline = SpectralBaseline.load(str(bl_path))
        output = args.output or str(proj / 'baseline_fingerprint.png')

        print(f"Baseline: {bl_path}")
        print(f"  Bins: {baseline.n_bins}")
        print(f"  Recordings pooled: {baseline._n_recordings}")
        print(f"  p_fa: {baseline.p_fa}")
        for name in baseline.psd_baseline:
            dof = baseline.dof_baseline[name]
            n_struct = baseline.structural_mask[name].sum()
            print(f"\n  {name}:")
            print(f"    DOF: {dof}")
            print(f"    Structural bins: {n_struct}")
            print(f"    Peak prominence: {baseline.prominence_db[name].max():.1f} dB")

        plot_baseline(baseline,
                     title=f'Learned Baseline — {proj.name}',
                     save_path=output, show=args.show)
        print(f"\nSaved: {output}")

    elif args.command == 'map':
        proj = Path(args.project)
        bl_path = proj / 'baseline.json'
        if not bl_path.exists():
            print(f"Error: {bl_path} not found. Run `train` first.")
            sys.exit(1)

        baseline = SpectralBaseline.load(str(bl_path))
        out_dir = str(proj / 'results' / 'map')

        methods = (['umap', 'tsne', 'pca'] if args.method == 'all'
                   else [args.method])
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
            print(f"Error: {bl_path} not found. Run `train` first.")
            sys.exit(1)

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
        print(f"Sample rate: {fs:.1f} Hz | Duration: {n/fs:.1f}s "
              f"| Axes: {list(signals.keys())}")

        analyzer = SpectralAnalyzer(fs=fs, nperseg=args.nperseg,
                                    median_window=args.median_window)
        frame = analyzer.analyze_frame(signals, peak_height=args.peak_height)

        for name in frame.psd_db:
            pks = frame.peaks[name]
            prom, freqs = frame.prominence_db[name], frame.freqs
            print(f"\n{name}: {len(pks)} peaks, "
                  f"{len(frame.valleys[name])} dips")
            if len(pks):
                for j, p in enumerate(
                        pks[np.argsort(prom[pks])[::-1]][:8]):
                    print(f"  {j+1}. {freqs[p]:8.2f} Hz  |  "
                          f"PSD: {frame.psd_db[name][p]:6.1f} dB  |  "
                          f"+{prom[p]:.1f} dB")

        output = args.output or (Path(args.csv).stem + '_spectrum.png')
        plot_spectral_frame(frame, title=Path(args.csv).stem,
                           save_path=output, show=args.show)
        print(f"\nSaved: {output}")


if __name__ == '__main__':
    main()