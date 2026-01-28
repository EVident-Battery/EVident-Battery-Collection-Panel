"""Manual sensor resolver for IP addresses and hostnames."""
import re
import socket
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

# Pattern for validating IP addresses
IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

# Pattern for validating EVBS hostnames
HOSTNAME_PATTERN = re.compile(r"^EVBS_[A-Za-z0-9]+$")


class ManualResolverWorker(QThread):
    """
    Background thread for resolving manual sensor entries.

    Accepts either:
    - IP address (e.g., "192.168.1.100")
    - Hostname (e.g., "EVBS_1234")

    For hostname: resolves {hostname}.local via DNS
    For IP: optionally probes /status endpoint to get device ID

    Signals:
        resolved(hostname, ip): Successfully resolved sensor
        failed(error): Resolution failed
    """

    resolved = pyqtSignal(str, str)  # hostname, ip
    failed = pyqtSignal(str)  # error message

    def __init__(self, entry: str, parent=None) -> None:
        super().__init__(parent)
        self._entry = entry.strip()

    def run(self) -> None:
        """Perform resolution in background thread."""
        entry = self._entry

        # Check if it's an IP address
        if IP_PATTERN.match(entry):
            self._resolve_ip(entry)
        # Check if it's a hostname
        elif HOSTNAME_PATTERN.match(entry):
            self._resolve_hostname(entry)
        else:
            self.failed.emit(
                f"Invalid input: '{entry}'. Enter an IP address (e.g., 192.168.1.100) "
                f"or hostname (e.g., EVBS_1234)"
            )

    def _resolve_ip(self, ip: str) -> None:
        """Resolve an IP address by probing the sensor."""
        # Validate IP octets
        try:
            octets = [int(o) for o in ip.split(".")]
            if not all(0 <= o <= 255 for o in octets):
                self.failed.emit(f"Invalid IP address: {ip}")
                return
        except ValueError:
            self.failed.emit(f"Invalid IP address: {ip}")
            return

        # Try to get device ID from /status endpoint
        hostname = self._probe_device(ip)
        if hostname:
            self.resolved.emit(hostname, ip)
        else:
            # Use IP as fallback hostname
            self.failed.emit(f"Could not reach sensor at {ip}")

    def _resolve_hostname(self, hostname: str) -> None:
        """Resolve a hostname via mDNS/DNS."""
        mdns_name = f"{hostname}.local"
        try:
            ip = socket.gethostbyname(mdns_name)
            self.resolved.emit(hostname, ip)
        except socket.gaierror:
            self.failed.emit(
                f"Could not resolve '{hostname}'. "
                f"Ensure the sensor is on the network and mDNS is working."
            )

    def _probe_device(self, ip: str) -> Optional[str]:
        """Probe device at IP to get its hostname from /status."""
        try:
            from services.sensor_client import SensorClient
            client = SensorClient(ip)
            status = client.get_status()
            # The Device ID field contains the hostname
            device_id = status.get("Device ID", "")
            if device_id and device_id.startswith("EVBS_"):
                return device_id
            # Fallback: use a generated name
            return f"EVBS_{ip.replace('.', '_')}"
        except Exception:
            return None
