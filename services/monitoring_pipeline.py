"""State machine orchestrator for the Machine Monitoring pipeline."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from models.monitoring_config import MonitoringConfig, MonitoringPhase, MonitoringStats, SaveMode
from services.collector import CollectorService, CollectionResult
from services.spectral_service import SpectralService
from services.aws_monitor_upload import AWSMonitorUploadService


class MonitoringPipeline(QObject):
    """
    Orchestrates the full monitoring workflow:
    IDLE -> BASELINE -> TRAINING -> MONITORING -> STOPPED

    Owns its own CollectorService to avoid conflicts with Tab 1.
    """

    phase_changed = pyqtSignal(object)       # MonitoringPhase
    log_message = pyqtSignal(str, str)        # message, level (info/success/warning/error)
    stats_updated = pyqtSignal(object)        # MonitoringStats
    pipeline_complete = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()

        # Own services (separate from Tab 1)
        self._collector = CollectorService()
        self._spectral = SpectralService()
        self._aws = AWSMonitorUploadService()

        # State
        self._phase = MonitoringPhase.IDLE
        self._config: Optional[MonitoringConfig] = None
        self._stats = MonitoringStats()

        # Temp directory management
        self._temp_dir: Optional[str] = None
        self._baseline_dir: Optional[str] = None
        self._monitor_dir: Optional[str] = None

        # Delay timer for scheduling next collection
        self._next_timer = QTimer(self)
        self._next_timer.setSingleShot(True)
        self._next_timer.timeout.connect(self._collect_next)

        # Connect internal signals
        self._collector.collection_complete.connect(self._on_collection_complete)
        self._collector.status_changed.connect(self._on_collection_status)
        self._spectral.training_complete.connect(self._on_training_complete)
        self._spectral.training_failed.connect(self._on_training_failed)
        self._spectral.check_complete.connect(self._on_check_complete)
        self._spectral.check_failed.connect(self._on_check_failed)
        self._aws.upload_complete.connect(self._on_upload_complete)
        self._aws.upload_failed.connect(self._on_upload_failed)

    @property
    def phase(self) -> MonitoringPhase:
        return self._phase

    @property
    def stats(self) -> MonitoringStats:
        return self._stats

    def start(self, config: MonitoringConfig) -> None:
        """Start the monitoring pipeline with the given config."""
        if self._phase not in (MonitoringPhase.IDLE, MonitoringPhase.STOPPED, MonitoringPhase.ERROR):
            self._log("Pipeline already running", "warning")
            return

        self._config = config
        self._stats = MonitoringStats(baseline_total=config.baseline_count)

        # Set up directories
        if config.save_mode == SaveMode.MONITOR:
            self._temp_dir = tempfile.mkdtemp(prefix="evbs_monitor_")
            self._baseline_dir = os.path.join(self._temp_dir, "baseline")
            self._monitor_dir = os.path.join(self._temp_dir, "monitor")
        else:
            base = str(config.save_folder) if config.save_folder else tempfile.mkdtemp(prefix="evbs_monitor_")
            if not config.save_folder:
                self._temp_dir = base
            self._baseline_dir = os.path.join(base, "baseline")
            self._monitor_dir = os.path.join(base, "monitor")

        os.makedirs(self._baseline_dir, exist_ok=True)
        os.makedirs(self._monitor_dir, exist_ok=True)

        self._log(f"Starting monitoring pipeline for {config.hostname}", "info")
        self._log(f"Baseline recordings: {config.baseline_count}, Save mode: {config.save_mode.value}", "info")

        self._set_phase(MonitoringPhase.BASELINE)
        self._collect_next()

    def stop(self) -> None:
        """Stop the pipeline at any phase."""
        if self._phase == MonitoringPhase.IDLE:
            return

        self._next_timer.stop()
        self._collector.cancel_all()

        self._log("Pipeline stopped by user", "warning")
        self._set_phase(MonitoringPhase.STOPPED)
        self._cleanup_temp()
        self.pipeline_complete.emit()

    def _set_phase(self, phase: MonitoringPhase) -> None:
        self._phase = phase
        self.phase_changed.emit(phase)

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)

    def _emit_stats(self) -> None:
        self.stats_updated.emit(self._stats)

    def _collect_next(self) -> None:
        """Start the next collection based on current phase."""
        if self._config is None:
            return

        if self._phase == MonitoringPhase.BASELINE:
            output_dir = Path(self._baseline_dir)
            remaining = self._stats.baseline_total - self._stats.baseline_collected
            self._log(
                f"Collecting baseline {self._stats.baseline_collected + 1}/{self._stats.baseline_total}",
                "info",
            )
        elif self._phase == MonitoringPhase.MONITORING:
            output_dir = Path(self._monitor_dir)
            self._log(
                f"Collecting monitor recording #{self._stats.monitor_collected + 1}",
                "info",
            )
        else:
            return

        success = self._collector.start_collection(
            hostname=self._config.hostname,
            ip=self._config.ip,
            duration=self._config.duration,
            output_folder=output_dir,
            upload_to_aws=False,  # We handle AWS ourselves
            sample_rate=self._config.sample_rate,
        )

        if not success:
            self._log(f"Sensor {self._config.hostname} is busy, retrying in 5s", "warning")
            self._next_timer.start(5000)

    def _on_collection_status(self, hostname: str, status, message: str) -> None:
        """Forward collection status to log."""
        # Only log our own hostname
        if self._config and hostname == self._config.hostname:
            self._log(message, "info")

    def _on_collection_complete(self, hostname: str, result: CollectionResult) -> None:
        """Handle completed collection based on current phase."""
        if self._config is None or hostname != self._config.hostname:
            return

        if not result.success:
            self._log(f"Collection failed: {result.error_message}", "error")
            self._set_phase(MonitoringPhase.ERROR)
            self.pipeline_complete.emit()
            return

        if self._phase == MonitoringPhase.BASELINE:
            self._stats.baseline_collected += 1
            self._emit_stats()

            if self._stats.baseline_collected >= self._stats.baseline_total:
                # All baseline recordings collected, start training
                self._log(
                    f"Baseline collection complete ({self._stats.baseline_collected} recordings)",
                    "success",
                )
                self._start_training()
            else:
                # Collect next baseline after short delay
                self._next_timer.start(2000)

        elif self._phase == MonitoringPhase.MONITORING:
            self._stats.monitor_collected += 1
            self._emit_stats()

            # Check the recording against the baseline
            if result.file_path and result.file_path.exists():
                self._spectral.check_recording(str(result.file_path))
            else:
                self._log("No file to check, scheduling next recording", "warning")
                self._schedule_next_monitor()

    def _start_training(self) -> None:
        """Transition to TRAINING phase and start spectral training."""
        self._set_phase(MonitoringPhase.TRAINING)
        self._log("Training spectral model from baseline recordings...", "info")

        self._spectral.start_training(
            folder=self._baseline_dir,
            fs=self._config.sample_rate,
            nperseg=self._config.nperseg,
            p_fa=self._config.p_fa,
        )

    def _on_training_complete(self, baseline) -> None:
        """Handle successful training."""
        # Save baseline.json
        baseline_json_path = os.path.join(
            self._baseline_dir, "..", "baseline.json"
        )
        try:
            baseline.save(baseline_json_path)
            self._log(f"Baseline model saved to {baseline_json_path}", "success")
        except Exception as e:
            self._log(f"Failed to save baseline.json: {e}", "warning")

        self._log("Training complete. Starting continuous monitoring...", "success")
        self._set_phase(MonitoringPhase.MONITORING)
        self._collect_next()

    def _on_training_failed(self, error: str) -> None:
        """Handle training failure."""
        self._log(f"Training failed: {error}", "error")
        self._set_phase(MonitoringPhase.ERROR)
        self.pipeline_complete.emit()

    def _on_check_complete(self, filename: str, result, any_triggered: bool) -> None:
        """Handle spectral check result."""
        short_name = Path(filename).name

        if any_triggered:
            self._stats.anomalies_detected += 1
            self._emit_stats()

            # Log details
            for axis, triggered in result.triggered.items():
                if triggered:
                    self._log(
                        f"ANOMALY in {short_name} [{axis}]: "
                        f"T={result.T[axis]:.1f}/{result.T_threshold[axis]:.1f} "
                        f"M={result.M[axis]:.1f}/{result.M_threshold[axis]:.1f}",
                        "warning",
                    )

            # Upload to AWS
            self._upload_anomaly(filename, result)

            # Check anomaly limit
            if self._stats.anomaly_limit_reached:
                self._log(
                    f"Anomaly limit reached ({self._stats.anomaly_limit}). Stopping pipeline.",
                    "warning",
                )
                self._set_phase(MonitoringPhase.STOPPED)
                self._cleanup_temp()
                self.pipeline_complete.emit()
                return
        else:
            self._log(f"Normal: {short_name}", "success")

        self._schedule_next_monitor()

    def _on_check_failed(self, filename: str, error: str) -> None:
        """Handle spectral check failure."""
        self._log(f"Check failed for {Path(filename).name}: {error}", "error")
        self._schedule_next_monitor()

    def _upload_anomaly(self, csv_path: str, result) -> None:
        """Upload anomaly data to AWS."""
        if not self._config or not self._config.license_key:
            return

        self._stats.uploads_attempted += 1
        self._emit_stats()

        # Build detection result dict for upload
        detection_dict = {
            axis: {
                "T": result.T[axis],
                "T_threshold": result.T_threshold[axis],
                "T_triggered": result.T_triggered[axis],
                "M": result.M[axis],
                "M_threshold": result.M_threshold[axis],
                "M_triggered": result.M_triggered[axis],
                "triggered": result.triggered[axis],
            }
            for axis in result.triggered
        }

        thresholds_dict = {
            axis: {
                "T_threshold": result.T_threshold[axis],
                "M_threshold": result.M_threshold[axis],
            }
            for axis in result.T_threshold
        }

        # Get baseline json data if available
        baseline_data = {}
        baseline_json_path = os.path.join(self._baseline_dir, "..", "baseline.json")
        if os.path.exists(baseline_json_path):
            try:
                import json
                with open(baseline_json_path) as f:
                    baseline_data = json.load(f)
            except Exception:
                pass

        self._aws.upload(
            license_key=self._config.license_key,
            sensor_id=self._config.hostname,
            baseline_json=baseline_data,
            sensor_csv_path=csv_path,
            detection_result=detection_dict,
            thresholds=thresholds_dict,
        )

    def _on_upload_complete(self, message: str) -> None:
        self._stats.uploads_succeeded += 1
        self._emit_stats()
        self._log(message, "success")

    def _on_upload_failed(self, error: str) -> None:
        self._log(f"AWS upload failed: {error}", "error")

    def _schedule_next_monitor(self) -> None:
        """Schedule the next monitoring recording after the configured interval."""
        if self._phase != MonitoringPhase.MONITORING or self._config is None:
            return

        interval_ms = self._config.monitor_interval * 1000
        self._next_timer.start(interval_ms)

    def _cleanup_temp(self) -> None:
        """Remove temp directory if in Monitor save mode."""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir)
                self._log(f"Cleaned up temp directory: {self._temp_dir}", "info")
            except Exception as e:
                self._log(f"Failed to clean up temp: {e}", "warning")
            self._temp_dir = None
