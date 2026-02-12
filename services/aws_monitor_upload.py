"""AWS upload service for monitoring anomaly data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests
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
        detection_results_json: dict = None,
    ) -> None:
        super().__init__()
        self.license_key = license_key
        self.sensor_id = sensor_id
        self.baseline_json = baseline_json
        self.sensor_csv_path = sensor_csv_path
        self.detection_result = detection_result
        self.thresholds = thresholds
        self.detection_results_json = detection_results_json

    def run(self) -> None:
        """
        Upload flow:
        1. POST to AWS_ENDPOINT with auth headers to get presigned URLs
        2. PUT baseline.json to presigned URL
        3. PUT sensor CSV data to presigned URL
        4. PUT detection_results.json to presigned URL (if available)
        """
        try:
            csv_filename = Path(self.sensor_csv_path).name

            # Step 1: Get presigned URLs
            headers = {
                "auth-token": self.license_key,
                "evb-user-type": "customer",
            }
            filenames = ["baseline.json", csv_filename]
            if self.detection_results_json:
                filenames.append("detection_results.json")

            payload = {
                "sensor_id": self.sensor_id,
                "filenames": filenames,
                "detection_result": self.detection_result,
                "thresholds": self.thresholds,
            }
            resp = requests.post(AWS_ENDPOINT, json=payload, headers=headers, timeout=15)
            if resp.status_code != 200:
                self.upload_failed.emit(
                    f"Presign request failed ({resp.status_code}): {resp.text[:200]}"
                )
                return

            resp_json = resp.json()

            # Parse presigned URLs from response: {"files": [{"key": "...", "url": "..."}]}
            files_list = resp_json.get("files", [])
            urls = {item["key"]: item["url"] for item in files_list}

            baseline_url = None
            data_url = None
            detection_results_url = None
            for key, url in urls.items():
                if key.endswith("baseline.json"):
                    baseline_url = url
                elif key.endswith("detection_results.json"):
                    detection_results_url = url
                elif key.endswith(csv_filename):
                    data_url = url

            if not baseline_url or not data_url:
                self.upload_failed.emit(
                    f"Missing presigned URLs. Got keys: {list(urls.keys())}"
                )
                return

            # Step 2: PUT baseline.json (no Content-Type — signature mismatch otherwise)
            baseline_body = json.dumps(self.baseline_json)
            put_resp = requests.put(baseline_url, data=baseline_body, timeout=30)
            if put_resp.status_code not in (200, 204):
                self.upload_failed.emit(
                    f"Baseline upload failed ({put_resp.status_code}): {put_resp.text[:200]}"
                )
                return

            # Step 3: PUT sensor CSV (no Content-Type)
            with open(self.sensor_csv_path, "rb") as f:
                put_resp = requests.put(data_url, data=f, timeout=30)
            if put_resp.status_code not in (200, 204):
                self.upload_failed.emit(
                    f"CSV upload failed ({put_resp.status_code}): {put_resp.text[:200]}"
                )
                return

            # Step 4: PUT detection_results.json (skip if no URL returned)
            if detection_results_url and self.detection_results_json:
                det_body = json.dumps(self.detection_results_json)
                put_resp = requests.put(detection_results_url, data=det_body, timeout=30)
                if put_resp.status_code not in (200, 204):
                    self.upload_failed.emit(
                        f"Detection results upload failed ({put_resp.status_code}): {put_resp.text[:200]}"
                    )
                    return

            self.upload_complete.emit(
                f"Uploaded anomaly data for {self.sensor_id} ({csv_filename})"
            )
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
        detection_results_json: dict = None,
    ) -> None:
        """Start an upload in a background thread."""
        self._worker = AWSUploadWorker(
            license_key=license_key,
            sensor_id=sensor_id,
            baseline_json=baseline_json,
            sensor_csv_path=sensor_csv_path,
            detection_result=detection_result,
            thresholds=thresholds,
            detection_results_json=detection_results_json,
        )
        self._worker.upload_complete.connect(self._on_complete)
        self._worker.upload_failed.connect(self._on_failed)
        self._worker.start()

    def _on_complete(self, message: str) -> None:
        self.upload_complete.emit(message)

    def _on_failed(self, error: str) -> None:
        self.upload_failed.emit(error)
