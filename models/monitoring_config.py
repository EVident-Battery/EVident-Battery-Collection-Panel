"""Configuration and state models for the Machine Monitoring tab."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional


class MonitoringPhase(Enum):
    """Current phase of the monitoring pipeline."""
    IDLE = auto()
    BASELINE = auto()
    TRAINING = auto()
    MONITORING = auto()
    STOPPED = auto()
    ERROR = auto()


class SaveMode(Enum):
    """How monitoring data is persisted."""
    SAVE_LOCATION = "save_location"
    MONITOR = "monitor"


class MonitorStopMode(Enum):
    """Stop mode for the monitoring phase."""
    CONTINUOUS = "continuous"
    AFTER_COUNT = "after_count"
    AT_TIME = "at_time"


@dataclass
class MonitoringStats:
    """Live statistics for the monitoring pipeline."""
    baseline_collected: int = 0
    baseline_total: int = 0
    monitor_collected: int = 0
    anomalies_detected: int = 0
    anomaly_limit: int = 30
    uploads_attempted: int = 0
    uploads_succeeded: int = 0

    @property
    def anomaly_limit_reached(self) -> bool:
        return self.anomalies_detected >= self.anomaly_limit


@dataclass
class MonitoringConfig:
    """Full configuration for a monitoring session."""
    # Sensor identity
    hostname: str = ""
    ip: str = ""

    # Collection settings
    duration: int = 20          # seconds
    sample_rate: float = 1666.0  # Hz (ODR value)

    # Baseline
    baseline_count: int = 10

    # Save mode
    save_mode: SaveMode = SaveMode.MONITOR
    save_folder: Optional[Path] = None

    # AWS
    license_key: str = ""

    # Spectral params
    nperseg: int = 4096
    p_fa: float = 0.01

    # Monitoring
    monitor_interval: int = 5  # seconds between monitor recordings

    # Baseline timing
    baseline_interval: int = 2  # seconds between baseline collections

    # Monitor stop mode
    monitor_stop_mode: MonitorStopMode = MonitorStopMode.CONTINUOUS
    monitor_stop_count: int = 10
    monitor_stop_time: object = None  # QTime, kept as object to avoid PyQt5 import

    # Skip baseline (for "Continue Last Program")
    skip_baseline: bool = False
