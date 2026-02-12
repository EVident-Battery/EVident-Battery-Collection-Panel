"""Placeholder AWS upload service for monitoring anomaly data."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal


AWS_ENDPOINT = "https://smv4232qo6.execute-api.us-east-1.amazonaws.com/prod/uploads"


class AWSUploadWorker(QThread):
    """Uploads anomaly data to AWS via presigned URLs."""

    upload_complete = pyqtSignal(str)  # success message
    upload_failed = pyqtSignal(str)    # error message

    def __init__(
        self,
        license_key: str,
        sensor_id: str,
        baseline_json: dict,
        sensor_csv_path: str,
        detection_result: dict,
        thresholds: dict,
    ) -> None:
        super().__init__()
        self.license_key = license_key
        self.sensor_id = sensor_id
        self.baseline_json = baseline_json
        self.sensor_csv_path = sensor_csv_path
        self.detection_result = detection_result
        self.thresholds = thresholds

    def run(self) -> None:
        """
        Full upload flow (stubbed for now):
        1. POST to AWS_ENDPOINT with auth headers to get presigned URLs
        2. PUT baseline.json to presigned URL
        3. PUT sensor CSV data to presigned URL
        """
        try:
            # Step 1: Get presigned URLs
            # headers = {
            #     "auth-token": self.license_key,
            #     "evb-user-type": "customer",
            # }
            # payload = {
            #     "sensor_id": self.sensor_id,
            #     "detection_result": self.detection_result,
            #     "thresholds": self.thresholds,
            # }
            # response = requests.post(AWS_ENDPOINT, json=payload, headers=headers)
            # presigned = response.json()

            # Step 2: PUT baseline.json
            # requests.put(presigned["baseline_url"], json=self.baseline_json)

            # Step 3: PUT sensor CSV
            # with open(self.sensor_csv_path, "rb") as f:
            #     requests.put(presigned["data_url"], data=f)

            # For now: pass (stub)
            pass

            self.upload_complete.emit(f"Upload stub complete for {self.sensor_id}")
        except Exception as e:
            self.upload_failed.emit(str(e))


class AWSMonitorUploadService(QObject):
    """Manages AWS upload workers for monitoring data."""

    upload_complete = pyqtSignal(str)
    upload_failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._worker: Optional[AWSUploadWorker] = None

    def upload(
        self,
        license_key: str,
        sensor_id: str,
        baseline_json: dict,
        sensor_csv_path: str,
        detection_result: dict,
        thresholds: dict,
    ) -> None:
        """Start an upload in a background thread."""
        self._worker = AWSUploadWorker(
            license_key=license_key,
            sensor_id=sensor_id,
            baseline_json=baseline_json,
            sensor_csv_path=sensor_csv_path,
            detection_result=detection_result,
            thresholds=thresholds,
        )
        self._worker.upload_complete.connect(self._on_complete)
        self._worker.upload_failed.connect(self._on_failed)
        self._worker.start()

    def _on_complete(self, message: str) -> None:
        self.upload_complete.emit(message)

    def _on_failed(self, error: str) -> None:
        self.upload_failed.emit(error)
