"""Sensor discovery service using Zeroconf/mDNS."""
import re
from typing import Dict

from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from PyQt5.QtCore import QObject, pyqtSignal


HOST_REGEX = re.compile(r"^(EVBS_[A-Za-z0-9]+)\._evbs\._tcp\.local\.$")


class DiscoverySignals(QObject):
    """Qt signals for discovery events."""
    device_found = pyqtSignal(str, str)  # hostname, ip
    device_lost = pyqtSignal(str)  # hostname
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

    def start(self) -> None:
        """Start scanning for sensors."""
        if self._zeroconf is not None:
            return
        self._zeroconf = Zeroconf()
        self._browser = ServiceBrowser(
            self._zeroconf, "_evbs._tcp.local.", _Listener(self.signals)
        )

    def stop(self) -> None:
        """Stop scanning."""
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

