"""Persistent per-sensor settings store (JSON, cross-platform)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QStandardPaths, QTime

from models.sensor_config import (
    SensorConfig, IntervalUnit, SampleRate, AccelRange, StartMode, StopMode,
)


class SensorSettingsStore:
    """
    Saves and restores per-sensor settings across app restarts.

    Settings are keyed by sensor hostname in a JSON file inside the
    OS-appropriate per-user config directory (QStandardPaths.AppConfigLocation):
    %LOCALAPPDATA% on Windows, ~/Library/Preferences on macOS, ~/.config on
    Linux. Persistence is best-effort - a missing or corrupt file must never
    block discovery or collection.
    """

    def __init__(self) -> None:
        base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        self._path = Path(base) / "sensors.json"
        self._data: Dict[str, dict] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        try:
            if self._path.exists():
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
        except Exception:
            self._data = {}

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def apply(self, config: SensorConfig) -> None:
        """Restore saved settings onto a freshly created config."""
        entry = self._data.get(config.hostname)
        if not isinstance(entry, dict):
            return
        try:
            config.label = str(entry.get("label", ""))
            config.duration = int(entry.get("duration", config.duration))
            config.interval_value = int(entry.get("interval_value", config.interval_value))
            config.interval_unit = IntervalUnit(entry.get("interval_unit", config.interval_unit.value))
            config.sample_rate = SampleRate.from_value(entry.get("sample_rate", config.sample_rate.value))
            config.accel_range = AccelRange(entry.get("accel_range", config.accel_range.value))
            folder = entry.get("output_folder")
            if folder and Path(folder).is_dir():
                config.output_folder = Path(folder)
            config.upload_to_aws = bool(entry.get("upload_to_aws", config.upload_to_aws))
            config.start_mode = StartMode(entry.get("start_mode", config.start_mode.value))
            config.start_at_time = self._parse_time(entry.get("start_at_time"))
            config.stop_mode = StopMode(entry.get("stop_mode", config.stop_mode.value))
            config.repetition_count = int(entry.get("repetition_count", config.repetition_count))
            config.stop_at_time = self._parse_time(entry.get("stop_at_time"))
            config.repeat_daily = bool(entry.get("repeat_daily", False))
            config.should_be_running = bool(entry.get("should_be_running", False))
        except Exception:
            # A corrupt entry falls back to whatever was applied before it
            pass

    def save(self, config: SensorConfig) -> None:
        """Persist one sensor's current settings."""
        self._data[config.hostname] = {
            "label": config.label,
            "duration": config.duration,
            "interval_value": config.interval_value,
            "interval_unit": config.interval_unit.value,
            "sample_rate": config.sample_rate.value,
            "accel_range": config.accel_range.value,
            "output_folder": str(config.output_folder) if config.output_folder else None,
            "upload_to_aws": config.upload_to_aws,
            "start_mode": config.start_mode.value,
            "start_at_time": self._format_time(config.start_at_time),
            "stop_mode": config.stop_mode.value,
            "repetition_count": config.repetition_count,
            "stop_at_time": self._format_time(config.stop_at_time),
            "repeat_daily": config.repeat_daily,
            "should_be_running": config.should_be_running,
        }
        self._write()

    @staticmethod
    def _parse_time(value) -> Optional[QTime]:
        if not value:
            return None
        t = QTime.fromString(str(value), "HH:mm")
        return t if t.isValid() else None

    @staticmethod
    def _format_time(t: Optional[QTime]) -> Optional[str]:
        return t.toString("HH:mm") if t is not None else None
