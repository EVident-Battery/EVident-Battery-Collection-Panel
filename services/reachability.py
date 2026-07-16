"""Reachability probing for sensors whose mDNS record has expired."""
from __future__ import annotations

from typing import Dict

import requests
from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal


# Backoff schedule in seconds; the last entry repeats forever.
PROBE_DELAYS = [15, 30, 60, 120, 300]


class ProbeWorker(QThread):
    """One HTTP /status probe against a sensor, off the UI thread."""

    probe_finished = pyqtSignal(str, bool)  # hostname, reachable

    def __init__(self, hostname: str, ip: str) -> None:
        super().__init__()
        self.hostname = hostname
        self.ip = ip

    def run(self) -> None:
        reachable = False
        try:
            r = requests.get(f"http://{self.ip}/status", timeout=(3, 5))
            reachable = r.status_code == 200
        except Exception:
            reachable = False
        self.probe_finished.emit(self.hostname, reachable)


class ReachabilityMonitor(QObject):
    """
    Probes unreachable sensors at their last-known IP with exponential backoff.

    Engaged only for sensors whose mDNS record expired AND whose collections
    then failed consecutively. A successful probe means the sensor is alive
    at the IP that was verified earlier this session, even though mDNS is
    silent - the caller can safely resume its schedule.
    """

    sensor_reachable = pyqtSignal(str)  # hostname
    probe_failed = pyqtSignal(str, int)  # hostname, seconds until next probe

    def __init__(self) -> None:
        super().__init__()
        self._timers: Dict[str, QTimer] = {}
        self._attempts: Dict[str, int] = {}
        self._ips: Dict[str, str] = {}
        self._workers: Dict[str, ProbeWorker] = {}

    def is_probing(self, hostname: str) -> bool:
        return hostname in self._timers

    def start_probing(self, hostname: str, ip: str) -> None:
        """Begin the backoff probe loop for a sensor."""
        if hostname in self._timers:
            return
        self._ips[hostname] = ip
        self._attempts[hostname] = 0
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda hn=hostname: self._launch_probe(hn))
        self._timers[hostname] = timer
        timer.start(int(PROBE_DELAYS[0] * 1000))

    def stop_probing(self, hostname: str) -> None:
        """Cancel probing for a sensor (rediscovered, paused, or removed)."""
        timer = self._timers.pop(hostname, None)
        if timer:
            timer.stop()
            timer.deleteLater()
        self._attempts.pop(hostname, None)
        self._ips.pop(hostname, None)
        # An in-flight worker keeps its reference until finished; its result
        # is ignored because the hostname is no longer tracked.

    def _launch_probe(self, hostname: str) -> None:
        if hostname not in self._timers or hostname in self._workers:
            return
        worker = ProbeWorker(hostname, self._ips[hostname])
        worker.probe_finished.connect(self._on_probe_finished)
        worker.finished.connect(
            lambda hn=hostname, w=worker: self._cleanup_worker(hn, w)
        )
        self._workers[hostname] = worker
        worker.start()

    def _cleanup_worker(self, hostname: str, worker: ProbeWorker) -> None:
        """Release a worker only after its thread has fully finished."""
        if self._workers.get(hostname) is worker:
            del self._workers[hostname]

    def _on_probe_finished(self, hostname: str, reachable: bool) -> None:
        if hostname not in self._timers:
            return  # probing was cancelled while the worker ran
        if reachable:
            self.stop_probing(hostname)
            self.sensor_reachable.emit(hostname)
            return
        self._attempts[hostname] += 1
        delay = PROBE_DELAYS[min(self._attempts[hostname], len(PROBE_DELAYS) - 1)]
        self.probe_failed.emit(hostname, delay)
        self._timers[hostname].start(int(delay * 1000))

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Stop all probing and wait for in-flight probe threads to exit."""
        for hostname in list(self._timers.keys()):
            self.stop_probing(hostname)
        for worker in list(self._workers.values()):
            worker.wait(timeout_ms)
        self._workers.clear()
