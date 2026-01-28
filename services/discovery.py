"""Sensor discovery service using Zeroconf/mDNS."""
import re
from typing import Dict

from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from PyQt5.QtCore import QObject, pyqtSignal, QTimer


HOST_REGEX = re.compile(r"^(EVBS_[A-Za-z0-9]+)\._evbs\._tcp\.local\.$")

# Time before showing "no devices found" warning (milliseconds)
DISCOVERY_TIMEOUT_MS = 15000


class DiscoverySignals(QObject):
    """Qt signals for discovery events."""
    device_found = pyqtSignal(str, str)  # hostname, ip
    device_lost = pyqtSignal(str)  # hostname
    discovery_timeout = pyqtSignal()  # No devices found after timeout
    done = pyqtSignal()


class _Listener(ServiceListener):
    """Internal Zeroconf listener."""
    
    def __init__(self, signals: DiscoverySignals) -> None:
        self._signals = signals

    def add_service(self, zeroconf, service_type, name):
        info = zeroconf.get_service_info(service_type, name)
        match = HOST_REGEX.match(name)
        if not match or not info:
            return
        hostname = match.group(1)
        addresses = info.parsed_addresses()
        if not addresses:
            return
        ip = addresses[0]
        self._signals.device_found.emit(hostname, ip)

    def remove_service(self, zeroconf, service_type, name):
        match = HOST_REGEX.match(name)
        if match:
            self._signals.device_lost.emit(match.group(1))

    def update_service(self, zeroconf, service_type, name):
        # Treat updates as re-discoveries
        self.add_service(zeroconf, service_type, name)


class DiscoveryController(QObject):
    """Controller for discovering sensors on the network."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = DiscoverySignals()
        self._zeroconf: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._has_found_device = False

        # Timeout timer for warning when no devices discovered
        self._timeout_timer = QTimer()
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_discovery_timeout)

    def start(self) -> None:
        """Start scanning for sensors."""
        if self._zeroconf is not None:
            return
        self._has_found_device = False
        self._zeroconf = Zeroconf()
        self._browser = ServiceBrowser(
            self._zeroconf, "_evbs._tcp.local.", _Listener(self.signals)
        )
        # Start timeout timer
        self._timeout_timer.start(DISCOVERY_TIMEOUT_MS)

    def notify_device_found(self) -> None:
        """Call when a device is found to cancel timeout."""
        self._has_found_device = True
        self._timeout_timer.stop()

    def _on_discovery_timeout(self) -> None:
        """Handle discovery timeout - emit signal if no devices found."""
        if not self._has_found_device:
            self.signals.discovery_timeout.emit()

    def stop(self) -> None:
        """Stop scanning."""
        self._timeout_timer.stop()
        if self._browser is not None:
            self._browser.cancel()
            self._browser = None
        if self._zeroconf is not None:
            try:
                self._zeroconf.close()
            finally:
                self._zeroconf = None
        self.signals.done.emit()

    @property
    def is_running(self) -> bool:
        return self._zeroconf is not None

