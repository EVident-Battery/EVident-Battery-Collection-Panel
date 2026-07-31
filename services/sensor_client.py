"""Extended SensorClient with upload support and progress callbacks."""
from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional
from pathlib import Path
import requests


class SensorClient:
    """HTTP client for communicating with ESP32 sensor devices."""

    def __init__(self, ip: str) -> None:
        self.ip = ip
        self.base_url = f"http://{ip}"
        self.data_url = f"http://{ip}:8000"

    def get_status(self) -> Dict:
        """Get device status including battery, WiFi, version info."""
        url = f"{self.base_url}/status"
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def get_settings(self) -> Dict:
        """Get current sensor configuration settings."""
        url = f"{self.base_url}/settings"
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()
        data = r.json()
        keys = ["odr", "gravity_comp", "accel_range", "gyro_range", "duration", "accel", "gyro"]
        return {k: data.get(k) for k in keys}

    def get_file_info(self) -> Dict:
        """Get information about the last saved data collection."""
        url = f"{self.base_url}/file_info"
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def get_progress(self) -> Dict:
        """Get progress of current data collection or HTTP transfer."""
        url = f"{self.base_url}/progress"
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def blink(self) -> None:
        """Trigger the device's identification blink."""
        url = f"{self.base_url}/blink"
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()

    def set_duration(self, duration: float) -> Dict:
        """Set the data collection duration in seconds."""
        url = f"{self.base_url}/duration?value={duration}"
        r = requests.post(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def set_odr(self, odr: float) -> Dict:
        """Set the Output Data Rate (sample rate) in Hz."""
        url = f"{self.base_url}/odr?value={odr}"
        r = requests.post(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def set_accel_range(self, accel_range: int) -> Dict:
        """Set the accelerometer range in g (2, 4, 8, or 16)."""
        url = f"{self.base_url}/accel_range?value={accel_range}"
        r = requests.post(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def set_gyro_range(self, gyro_range: int) -> Dict:
        """Set the gyroscope range in dps (125-4000). EVB-01 only."""
        url = f"{self.base_url}/gyro_range?value={gyro_range}"
        r = requests.post(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def set_gravity_comp(self, enabled: bool) -> Dict:
        """Enable/disable the on-sensor gravity compensation high-pass filter."""
        value = "true" if enabled else "false"
        url = f"{self.base_url}/gravity_comp?value={value}"
        r = requests.post(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def set_collect(self, accel: bool = True, gyro: bool = False) -> Dict:
        """Select which channels the sensor records (accel is always on)."""
        accel_arg = "true" if accel else "false"
        gyro_arg = "true" if gyro else "false"
        url = f"{self.base_url}/collect?accel={accel_arg}&gyro={gyro_arg}"
        r = requests.post(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    @staticmethod
    def collection_read_timeout(duration: float) -> int:
        """Seconds to wait for a recording of `duration` before declaring a stall."""
        return max(45, int(duration * 1.05) + 30)

    def start_collection(
        self,
        duration: float,
        output_path: Path,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """
        Start data collection and download CSV to output_path.
        
        Args:
            duration: Collection duration in seconds
            output_path: Path to save the CSV file
            on_progress: Optional callback(bytes_downloaded, total_bytes)
            
        Returns:
            Path to the saved file
        """
        url = f"{self.data_url}/start?duration={duration}&format=csv"

        # The server sends nothing until the recording finishes, so the
        # read timeout must cover the full recording plus setup/flush
        # slack - but not much more, so a sensor that dies mid-recording
        # is detected quickly instead of hanging the cycle.
        timeout = (10, self.collection_read_timeout(duration))
        
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            
            # Try to get content length for progress
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            # Get filename from Content-Disposition if available
            content_disp = r.headers.get('Content-Disposition', '')
            if 'filename=' in content_disp:
                import re
                match = re.search(r'filename="?([^";\n]+)"?', content_disp)
                if match:
                    filename = match.group(1)
                    output_path = output_path / filename
            else:
                # Generate filename with timestamp
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                output_path = output_path / f"sensor_data_{timestamp}.csv"
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total_size)
        
        return output_path

    def upload_to_aws(self) -> Dict:
        """
        Trigger the sensor to upload collected data to AWS S3.
        
        Returns:
            Response dict with status or error
        """
        url = f"{self.data_url}/upload"
        # Give generous timeout for cloud upload
        r = requests.get(url, timeout=(10, 120))
        r.raise_for_status()
        return r.json()

    def stop(self) -> Dict:
        """Stop current data collection or transfer."""
        url = f"{self.base_url}/stop"
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

