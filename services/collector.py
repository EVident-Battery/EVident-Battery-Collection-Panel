"""Collection orchestration service with status callbacks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, Optional
import traceback

import requests

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from services.sensor_client import SensorClient


class CollectionStatus(Enum):
    """Status stages for a collection cycle."""
    IDLE = auto()
    CONNECTING = auto()
    COLLECTING = auto()
    DOWNLOADING = auto()
    UPLOADING = auto()
    COMPLETE = auto()
    ERROR = auto()
    AWS_ERROR = auto()


@dataclass
class CollectionResult:
    """Result of a collection cycle."""
    hostname: str = ""
    success: bool = False
    file_path: Optional[Path] = None
    file_size: int = 0
    aws_status: Optional[str] = None
    error_message: Optional[str] = None
    duration: float = 0.0


class CollectorWorker(QThread):
    """Background worker that performs collection, download, and upload."""
    
    # Signals for status updates - include hostname
    status_changed = pyqtSignal(str, CollectionStatus, str)  # hostname, status, message
    progress_updated = pyqtSignal(str, int, int)  # hostname, downloaded, total
    collection_complete = pyqtSignal(str, CollectionResult)  # hostname, result
    
    def __init__(
        self,
        hostname: str,
        ip: str,
        duration: float,
        output_folder: Path,
        upload_to_aws: bool = True,
        sample_rate: float = 104,
        accel_range: int = 4,
    ) -> None:
        super().__init__()
        self.hostname = hostname
        self.ip = ip
        self.duration = duration
        self.output_folder = output_folder
        self.upload_to_aws = upload_to_aws
        self.sample_rate = sample_rate
        self.accel_range = accel_range
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation of the current operation."""
        self._cancelled = True

    def _diagnose_stall(self, client: SensorClient) -> str:
        """
        A collection ran past its window without delivering data.

        Distinguish "sensor died mid-recording" from "sensor alive but
        stuck/overrunning": probe /status, then /progress. If the sensor is
        alive, send /stop so its collection state is clean for the next
        cycle. Returns the error message for this failed cycle.
        """
        waited = SensorClient.collection_read_timeout(self.duration)
        try:
            client.get_status()
        except Exception:
            return (
                f"No data after {waited}s and sensor is unreachable"
                " - it likely lost power or Wi-Fi mid-recording"
            )

        # Alive - what does it think it's doing?
        try:
            progress = client.get_progress().get("progress")
        except Exception:
            progress = "unknown"

        try:
            client.stop()
            reset_note = "sensor reset for next cycle"
        except Exception:
            reset_note = "sensor reset failed"

        return (
            f"No data after {waited}s but sensor is reachable"
            f" (progress: {progress}) - {reset_note}"
        )

    def run(self) -> None:
        """Execute the collection cycle."""
        start_time = datetime.now()
        result = CollectionResult(hostname=self.hostname, success=False)
        
        try:
            # Connect to sensor
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.CONNECTING,
                f"[{self.hostname}] Connecting..."
            )
            
            client = SensorClient(self.ip)
            
            # Verify connection by getting status
            status = client.get_status()
            battery = status.get("Battery SOC", 0)
            
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.CONNECTING,
                f"[{self.hostname}] Connected (Battery: {battery:.1f}%)"
            )
            
            if self._cancelled:
                return
            
            # Set sample rate (ODR)
            try:
                client.set_odr(self.sample_rate)
            except Exception as e:
                # Log but continue - sensor may already be at this rate
                pass

            # Set accelerometer range
            try:
                client.set_accel_range(self.accel_range)
            except Exception as e:
                # Log but continue - sensor may already be at this range
                pass
            
            # Start data collection
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.COLLECTING,
                f"[{self.hostname}] Collecting for {self.duration:.0f}s @ {self.sample_rate}Hz..."
            )
            
            # Callback for download progress - emit DOWNLOADING status on first progress
            download_started = False
            
            def on_progress(downloaded: int, total: int):
                nonlocal download_started
                if not download_started:
                    download_started = True
                    self.status_changed.emit(
                        self.hostname,
                        CollectionStatus.DOWNLOADING,
                        f"[{self.hostname}] Downloading..."
                    )
                self.progress_updated.emit(self.hostname, downloaded, total)
            
            # Perform collection and download. If the sensor doesn't deliver
            # within the recording duration plus slack, diagnose instead of
            # hanging: ask /progress whether it is still working, reset it if
            # so, and fail the cycle either way so the scheduler retries.
            try:
                file_path = client.start_collection(
                    duration=self.duration,
                    output_path=self.output_folder,
                    on_progress=on_progress,
                )
            except requests.exceptions.ReadTimeout:
                raise Exception(self._diagnose_stall(client))
            
            result.file_path = file_path
            result.file_size = file_path.stat().st_size if file_path.exists() else 0
            
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.DOWNLOADING,
                f"[{self.hostname}] Downloaded {result.file_size / 1024:.1f} KB"
            )
            
            if self._cancelled:
                return
            
            # Upload to AWS if enabled
            if self.upload_to_aws:
                self.status_changed.emit(
                    self.hostname,
                    CollectionStatus.UPLOADING,
                    f"[{self.hostname}] Uploading to AWS..."
                )
                
                try:
                    upload_result = client.upload_to_aws()
                    result.aws_status = upload_result.get("status", "Unknown")
                    
                    self.status_changed.emit(
                        self.hostname,
                        CollectionStatus.UPLOADING,
                        f"[{self.hostname}] AWS: {result.aws_status}"
                    )
                except Exception as e:
                    result.aws_status = f"Failed: {str(e)}"
                    self.status_changed.emit(
                        self.hostname,
                        CollectionStatus.AWS_ERROR,
                        f"[{self.hostname}] AWS upload failed: {str(e)}"
                    )
            
            # Complete
            elapsed = (datetime.now() - start_time).total_seconds()
            result.duration = elapsed
            result.success = True
            
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.COMPLETE,
                f"[{self.hostname}] Complete in {elapsed:.1f}s"
            )
            
        except Exception as e:
            result.success = False
            result.error_message = str(e)
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.ERROR,
                f"[{self.hostname}] Error: {str(e)}"
            )
            traceback.print_exc()
        
        finally:
            result.duration = (datetime.now() - start_time).total_seconds()
            self.collection_complete.emit(self.hostname, result)


class CollectorService(QObject):
    """Service that manages multiple concurrent collection workers."""
    
    # Signals include hostname for routing
    status_changed = pyqtSignal(str, CollectionStatus, str)  # hostname, status, message
    progress_updated = pyqtSignal(str, int, int)  # hostname, downloaded, total
    collection_complete = pyqtSignal(str, CollectionResult)  # hostname, result
    
    def __init__(self) -> None:
        super().__init__()
        self._workers: Dict[str, CollectorWorker] = {}
        self._last_status: Dict[str, CollectionStatus] = {}

    def is_busy(self, hostname: str) -> bool:
        """Check if a specific sensor is busy collecting."""
        worker = self._workers.get(hostname)
        return worker is not None and worker.isRunning()

    def last_status(self, hostname: str) -> Optional[CollectionStatus]:
        """Phase last reported by this sensor's in-flight worker, if any."""
        return self._last_status.get(hostname)

    def start_collection(
        self,
        hostname: str,
        ip: str,
        duration: float,
        output_folder: Path,
        upload_to_aws: bool = True,
        sample_rate: float = 104,
        accel_range: int = 4,
    ) -> bool:
        """
        Start a collection cycle for a sensor.

        Returns False if that sensor is already busy.
        """
        if self.is_busy(hostname):
            return False

        worker = CollectorWorker(hostname, ip, duration, output_folder, upload_to_aws, sample_rate, accel_range)
        worker.status_changed.connect(self._on_status)
        worker.progress_updated.connect(self._on_progress)
        worker.collection_complete.connect(self._on_complete)
        worker.finished.connect(
            lambda hn=hostname, w=worker: self._cleanup_worker(hn, w)
        )

        self._workers[hostname] = worker
        worker.start()
        return True

    def cancel(self, hostname: str) -> None:
        """Cancel collection for a specific sensor."""
        worker = self._workers.get(hostname)
        if worker:
            worker.cancel()

    def cancel_all(self) -> None:
        """Cancel all running collections."""
        for worker in self._workers.values():
            worker.cancel()

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Cancel all workers and block until their threads exit.

        Must be called before the application quits; otherwise interpreter
        teardown can destroy still-running QThreads and abort the process.
        """
        self.cancel_all()
        for worker in list(self._workers.values()):
            worker.wait(timeout_ms)
        self._workers.clear()

    def _on_status(self, hostname: str, status: CollectionStatus, message: str) -> None:
        """Forward status from worker."""
        self._last_status[hostname] = status
        self.status_changed.emit(hostname, status, message)

    def _on_progress(self, hostname: str, downloaded: int, total: int) -> None:
        """Forward progress from worker."""
        self.progress_updated.emit(hostname, downloaded, total)

    def _on_complete(self, hostname: str, result: CollectionResult) -> None:
        """Handle worker completion."""
        self.collection_complete.emit(hostname, result)

    def _cleanup_worker(self, hostname: str, worker: CollectorWorker) -> None:
        """Release a worker only after its thread has fully finished.

        Dropping the last reference while run() is still unwinding destroys
        a running QThread, which aborts the whole process
        ("QThread: Destroyed while thread is still running").
        """
        if self._workers.get(hostname) is worker:
            del self._workers[hostname]
            self._last_status.pop(hostname, None)
