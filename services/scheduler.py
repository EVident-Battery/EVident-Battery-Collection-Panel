"""Periodic scheduler for automated data collection."""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class SchedulerState(Enum):
    """State of the scheduler."""
    STOPPED = auto()
    RUNNING = auto()
    WAITING = auto()  # Waiting for next cycle
    COLLECTING = auto()  # Collection in progress


class CollectionScheduler(QObject):
    """
    Manages periodic collection scheduling.
    
    Signals:
        trigger_collection: Emitted when it's time to start a new collection
        state_changed: Emitted when scheduler state changes
        countdown_tick: Emitted every second with seconds until next collection
    """
    
    trigger_collection = pyqtSignal()
    state_changed = pyqtSignal(SchedulerState)
    countdown_tick = pyqtSignal(int)  # seconds remaining
    
    # Preset intervals in seconds
    INTERVAL_PRESETS = {
        "30 seconds": 30,
        "1 minute": 60,
        "2 minutes": 120,
        "5 minutes": 300,
        "10 minutes": 600,
        "15 minutes": 900,
        "30 minutes": 1800,
        "1 hour": 3600,
        "2 hours": 7200,
    }
    
    def __init__(self) -> None:
        super().__init__()
        self._state = SchedulerState.STOPPED
        self._interval_seconds = 300  # Default 5 minutes
        self._next_run: Optional[datetime] = None
        
        # Main interval timer
        self._interval_timer = QTimer(self)
        self._interval_timer.timeout.connect(self._on_interval_timeout)
        
        # Countdown tick timer (1 second)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

    @property
    def state(self) -> SchedulerState:
        return self._state

    @property
    def interval_seconds(self) -> int:
        return self._interval_seconds

    @interval_seconds.setter
    def interval_seconds(self, value: int) -> None:
        self._interval_seconds = max(10, value)  # Minimum 10 seconds
        if self._state == SchedulerState.WAITING:
            # Restart with new interval
            self._restart_interval_timer()

    @property
    def next_run_time(self) -> Optional[datetime]:
        return self._next_run

    @property
    def seconds_until_next(self) -> int:
        if self._next_run is None:
            return 0
        delta = (self._next_run - datetime.now()).total_seconds()
        return max(0, int(delta))

    def start(self, run_immediately: bool = True) -> None:
        """
        Start the scheduler.
        
        Args:
            run_immediately: If True, trigger first collection immediately
        """
        if self._state != SchedulerState.STOPPED:
            return
        
        self._set_state(SchedulerState.RUNNING)
        
        if run_immediately:
            self._trigger()
        else:
            self._start_waiting()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._interval_timer.stop()
        self._tick_timer.stop()
        self._next_run = None
        self._set_state(SchedulerState.STOPPED)

    def pause(self) -> None:
        """Pause scheduling (keeps state but stops timers)."""
        self._interval_timer.stop()
        self._tick_timer.stop()

    def resume(self) -> None:
        """Resume from pause."""
        if self._state == SchedulerState.WAITING:
            self._restart_interval_timer()

    def notify_collection_started(self) -> None:
        """Call when collection begins."""
        self._set_state(SchedulerState.COLLECTING)

    def notify_collection_complete(self) -> None:
        """Call when collection ends - schedules next run."""
        if self._state == SchedulerState.STOPPED:
            return
        self._start_waiting()

    def skip_to_next(self) -> None:
        """Skip current wait and trigger immediately."""
        if self._state == SchedulerState.WAITING:
            self._interval_timer.stop()
            self._tick_timer.stop()
            self._trigger()

    def _set_state(self, state: SchedulerState) -> None:
        if self._state != state:
            self._state = state
            self.state_changed.emit(state)

    def _trigger(self) -> None:
        """Trigger a collection."""
        self._set_state(SchedulerState.COLLECTING)
        self.trigger_collection.emit()

    def _start_waiting(self) -> None:
        """Start waiting for next interval."""
        self._set_state(SchedulerState.WAITING)
        self._next_run = datetime.now() + timedelta(seconds=self._interval_seconds)
        self._restart_interval_timer()

    def _restart_interval_timer(self) -> None:
        """Restart the interval timer."""
        self._interval_timer.stop()
        self._tick_timer.stop()
        
        remaining = self.seconds_until_next
        if remaining > 0:
            self._interval_timer.setSingleShot(True)
            self._interval_timer.start(remaining * 1000)
            self._tick_timer.start()
            self.countdown_tick.emit(remaining)
        else:
            self._trigger()

    def _on_interval_timeout(self) -> None:
        """Handle interval timer expiration."""
        self._tick_timer.stop()
        if self._state == SchedulerState.WAITING:
            self._trigger()

    def _on_tick(self) -> None:
        """Handle countdown tick."""
        remaining = self.seconds_until_next
        self.countdown_tick.emit(remaining)
        if remaining <= 0:
            self._tick_timer.stop()

    @staticmethod
    def format_duration(seconds: int) -> str:
        """Format seconds as human-readable duration."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            mins = seconds // 60
            secs = seconds % 60
            if secs:
                return f"{mins}m {secs}s"
            return f"{mins}m"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            if mins:
                return f"{hours}h {mins}m"
            return f"{hours}h"

