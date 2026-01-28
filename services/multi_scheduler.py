"""Multi-sensor scheduler for independent collection timing."""
from __future__ import annotations

from typing import Dict, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from models.sensor_config import SensorConfig, SensorStatus


class MultiSensorScheduler(QObject):
    """
    Manages independent countdown timers for multiple sensors.
    
    Each sensor can be started/stopped independently and has its own
    countdown that triggers collection when it reaches zero.
    
    Signals:
        trigger_collection(hostname): Emitted when a sensor's countdown reaches zero
        countdown_tick(hostname, seconds): Emitted every second for running sensors
        sensor_started(hostname): Emitted when a sensor starts its schedule
        sensor_stopped(hostname): Emitted when a sensor stops its schedule
    """
    
    trigger_collection = pyqtSignal(str)  # hostname
    countdown_tick = pyqtSignal(str, int)  # hostname, seconds remaining
    sensor_started = pyqtSignal(str)
    sensor_stopped = pyqtSignal(str)
    
    def __init__(self) -> None:
        super().__init__()
        self._sensors: Dict[str, SensorConfig] = {}
        self._collecting: Dict[str, bool] = {}  # hostname -> is currently collecting
        
        # Single timer that ticks every second for all sensors
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
    
    def register_sensor(self, config: SensorConfig) -> None:
        """Register a sensor configuration."""
        self._sensors[config.hostname] = config
        self._collecting[config.hostname] = False
    
    def unregister_sensor(self, hostname: str) -> None:
        """Unregister a sensor."""
        if hostname in self._sensors:
            self.stop_sensor(hostname)
            del self._sensors[hostname]
            del self._collecting[hostname]
    
    def get_sensor(self, hostname: str) -> Optional[SensorConfig]:
        """Get sensor config by hostname."""
        return self._sensors.get(hostname)
    
    def start_sensor(self, hostname: str, run_immediately: bool = True) -> bool:
        """
        Start scheduling for a sensor.
        
        Args:
            hostname: Sensor to start
            run_immediately: If True, trigger collection immediately
            
        Returns:
            True if started successfully
        """
        config = self._sensors.get(hostname)
        if not config or not config.is_configured:
            return False

        config.is_running = True
        config.status = SensorStatus.WAITING
        config.reset_repetitions()
        
        if run_immediately:
            # Trigger immediately, countdown starts after collection
            self._trigger_sensor(hostname)
        else:
            config.reset_countdown()
        
        self._ensure_timer_running()
        self.sensor_started.emit(hostname)
        return True
    
    def stop_sensor(self, hostname: str) -> None:
        """Stop scheduling for a sensor."""
        config = self._sensors.get(hostname)
        if config:
            config.is_running = False
            config.status = SensorStatus.IDLE
            config.countdown_seconds = 0
            self._collecting[hostname] = False
            self.sensor_stopped.emit(hostname)
        
        # Stop timer if no sensors are running
        if not self._any_running():
            self._tick_timer.stop()
    
    def start_all(self, run_immediately: bool = True) -> int:
        """
        Start all configured sensors.
        
        Returns number of sensors started.
        """
        count = 0
        for hostname, config in self._sensors.items():
            if config.is_configured and not config.is_running:
                if self.start_sensor(hostname, run_immediately):
                    count += 1
        return count
    
    def stop_all(self) -> None:
        """Stop all sensors."""
        for hostname in list(self._sensors.keys()):
            self.stop_sensor(hostname)
    
    def notify_collection_started(self, hostname: str) -> None:
        """Notify that collection has started for a sensor."""
        self._collecting[hostname] = True
        config = self._sensors.get(hostname)
        if config:
            config.status = SensorStatus.COLLECTING
    
    def notify_collection_complete(self, hostname: str) -> None:
        """Notify that collection completed - reset countdown."""
        self._collecting[hostname] = False
        config = self._sensors.get(hostname)
        if config and config.is_running:
            # Check if we should stop based on stop mode
            if config.should_stop_after_collection():
                self.stop_sensor(hostname)
                return

            config.status = SensorStatus.WAITING
            config.reset_countdown()
    
    def update_sensor_status(self, hostname: str, status: SensorStatus) -> None:
        """Update sensor status."""
        config = self._sensors.get(hostname)
        if config:
            config.status = status
    
    def _trigger_sensor(self, hostname: str) -> None:
        """Trigger collection for a sensor."""
        if not self._collecting.get(hostname, False):
            self.trigger_collection.emit(hostname)
    
    def _ensure_timer_running(self) -> None:
        """Ensure tick timer is running if any sensor is active."""
        if self._any_running() and not self._tick_timer.isActive():
            self._tick_timer.start()
    
    def _any_running(self) -> bool:
        """Check if any sensor is running."""
        return any(c.is_running for c in self._sensors.values())
    
    def _on_tick(self) -> None:
        """Handle 1-second tick for all running sensors."""
        for hostname, config in self._sensors.items():
            if not config.is_running:
                continue
            
            # Skip if currently collecting
            if self._collecting.get(hostname, False):
                continue
            
            # Only count down if waiting
            if config.status == SensorStatus.WAITING:
                reached_zero = config.tick_countdown()
                self.countdown_tick.emit(hostname, config.countdown_seconds)
                
                if reached_zero:
                    self._trigger_sensor(hostname)

