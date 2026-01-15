"""Collection orchestration service with status callbacks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, Optional
import traceback

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
    ) -> None:
        super().__init__()
        self.hostname = hostname
        self.ip = ip
        self.duration = duration
        self.output_folder = output_folder
        self.upload_to_aws = upload_to_aws
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation of the current operation."""
        self._cancelled = True

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
            
            # Start data collection
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.COLLECTING,
                f"[{self.hostname}] Collecting for {self.duration:.0f}s..."
            )
            
            # Callback for download progress
            def on_progress(downloaded: int, total: int):
                self.progress_updated.emit(self.hostname, downloaded, total)
            
            self.status_changed.emit(
                self.hostname,
                CollectionStatus.DOWNLOADING,
                f"[{self.hostname}] Downloading..."
            )
            
            # Perform collection and download
            file_path = client.start_collection(
                duration=self.duration,
                output_path=self.output_folder,
                on_progress=on_progress,
            )
            
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
                        CollectionStatus.UPLOADING,
                        f"[{self.hostname}] AWS upload failed"
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

    def is_busy(self, hostname: str) -> bool:
        """Check if a specific sensor is busy collecting."""
        worker = self._workers.get(hostname)
        return worker is not None and worker.isRunning()

    def start_collection(
        self,
        hostname: str,
        ip: str,
        duration: float,
        output_folder: Path,
        upload_to_aws: bool = True,
    ) -> bool:
        """
        Start a collection cycle for a sensor.
        
        Returns False if that sensor is already busy.
        """
        if self.is_busy(hostname):
            return False
        
        worker = CollectorWorker(hostname, ip, duration, output_folder, upload_to_aws)
        worker.status_changed.connect(self._on_status)
        worker.progress_updated.connect(self._on_progress)
        worker.collection_complete.connect(self._on_complete)
        
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

    def _on_status(self, hostname: str, status: CollectionStatus, message: str) -> None:
        """Forward status from worker."""
        self.status_changed.emit(hostname, status, message)

    def _on_progress(self, hostname: str, downloaded: int, total: int) -> None:
        """Forward progress from worker."""
        self.progress_updated.emit(hostname, downloaded, total)

    def _on_complete(self, hostname: str, result: CollectionResult) -> None:
        """Handle worker completion."""
        self.collection_complete.emit(hostname, result)
        # Clean up worker
        if hostname in self._workers:
            del self._workers[hostname]
