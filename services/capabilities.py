"""Background detection of sensor hardware capabilities via /settings."""
from __future__ import annotations

from typing import Dict

import requests
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from models.sensor_config import SensorModel


class _SettingsProbeWorker(QThread):
    """One HTTP /settings fetch against a sensor, off the UI thread."""

    settings_received = pyqtSignal(str, object)  # hostname, dict or None

    def __init__(self, hostname: str, ip: str) -> None:
        super().__init__()
        self.hostname = hostname
        self.ip = ip

    def run(self) -> None:
        payload = None
        try:
            r = requests.get(f"http://{self.ip}/settings", timeout=(3, 5))
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                payload = data
        except Exception:
            payload = None
        self.settings_received.emit(self.hostname, payload)


class CapabilityDetector(QObject):
    """
    Identifies each sensor's hardware model from its /settings response.

    EVB-Lite has no gyroscope and reports gyro_range as null; EVB-01
    reports a numeric range. The detected model gates which options the
    settings panel offers (gyro controls, ODR above 1666 Hz, accel range).

    Probes run on every discovery/rediscovery so the answer self-heals; a
    failed probe leaves the model unchanged (UNKNOWN sensors keep the full
    option set until first contact).
    """

    model_detected = pyqtSignal(str, object)  # hostname, SensorModel

    def __init__(self) -> None:
        super().__init__()
        self._workers: Dict[str, _SettingsProbeWorker] = {}

    def probe(self, hostname: str, ip: str) -> None:
        """Fetch /settings in the background; skip if one is already running."""
        if hostname in self._workers:
            return
        worker = _SettingsProbeWorker(hostname, ip)
        worker.settings_received.connect(self._on_settings)
        worker.finished.connect(
            lambda hn=hostname, w=worker: self._cleanup_worker(hn, w)
        )
        self._workers[hostname] = worker
        worker.start()

    def _on_settings(self, hostname: str, payload) -> None:
        if payload is None:
            return  # unreachable or malformed; model stays as it was
        if "gyro_range" not in payload:
            # Firmware that doesn't report the field at all can't be
            # classified - never lock features away on a guess
            return
        model = (
            SensorModel.EVB_LITE
            if payload["gyro_range"] is None
            else SensorModel.EVB_01
        )
        self.model_detected.emit(hostname, model)

    def _cleanup_worker(self, hostname: str, worker: _SettingsProbeWorker) -> None:
        """Release a worker only after its thread has fully finished."""
        if self._workers.get(hostname) is worker:
            del self._workers[hostname]

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Wait for in-flight probe threads to exit before app teardown."""
        for worker in list(self._workers.values()):
            worker.wait(timeout_ms)
        self._workers.clear()
