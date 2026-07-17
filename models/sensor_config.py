"""Per-sensor configuration and state model."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QTime


class IntervalUnit(Enum):
    """Time units for collection interval."""
    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"
    
    def to_seconds(self, value: int) -> int:
        """Convert value in this unit to seconds."""
        multipliers = {
            IntervalUnit.SECONDS: 1,
            IntervalUnit.MINUTES: 60,
            IntervalUnit.HOURS: 3600,
            IntervalUnit.DAYS: 86400,
            IntervalUnit.WEEKS: 604800,
        }
        return value * multipliers[self]
    
    @staticmethod
    def all_units() -> list[str]:
        """Return list of all unit display names."""
        return [u.value for u in IntervalUnit]


class SampleRate(Enum):
    """Supported ODR (Output Data Rate) values in Hz."""
    HZ_12_5 = 12.5
    HZ_26 = 26
    HZ_52 = 52
    HZ_104 = 104
    HZ_208 = 208
    HZ_416 = 416
    HZ_833 = 833
    HZ_1666 = 1666
    HZ_3333 = 3333
    HZ_6666 = 6666
    
    @property
    def display_name(self) -> str:
        """Human-readable name."""
        if self.value == 12.5:
            return "12.5 Hz"
        return f"{int(self.value)} Hz"
    
    @staticmethod
    def all_rates() -> list["SampleRate"]:
        """Return list of all sample rates."""
        return list(SampleRate)
    
    @staticmethod
    def from_value(value: float) -> "SampleRate":
        """Get SampleRate from numeric value."""
        for rate in SampleRate:
            if rate.value == value:
                return rate
        return SampleRate.HZ_104  # Default


class AccelRange(Enum):
    """Supported accelerometer range values in g."""
    G_2 = 2
    G_4 = 4
    G_8 = 8
    G_16 = 16
    
    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return f"±{self.value}g"
    
    @staticmethod
    def all_ranges() -> list["AccelRange"]:
        """Return list of all accel ranges."""
        return list(AccelRange)


class StartMode(Enum):
    """Start mode options for collection scheduling."""
    IMMEDIATE = "immediate"
    AT_TIME = "at_time"


class StopMode(Enum):
    """Stop mode options for collection scheduling."""
    CONTINUOUS = "continuous"
    AFTER_COUNT = "after_count"
    AT_TIME = "at_time"


class DiscoverySource(Enum):
    """How the sensor was discovered."""
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class SensorStatus(Enum):
    """Current status of a sensor."""
    IDLE = auto()
    WAITING = auto()
    COLLECTING = auto()
    DOWNLOADING = auto()
    UPLOADING = auto()
    ERROR = auto()
    UNREACHABLE = auto()  # mDNS gone AND collections failing; schedule suspended
    STOPPING = auto()  # user stopped, but an in-flight collection is finishing


@dataclass
class SensorStats:
    """Statistics for a sensor's collection history."""
    collections: int = 0
    uploaded: int = 0
    errors: int = 0


@dataclass
class SensorConfig:
    """
    Configuration and state for a single sensor.
    
    Each discovered sensor gets its own independent config including
    duration, interval, output folder, and scheduling state.
    """
    # Identity
    hostname: str
    ip: str

    # User-assigned display label (e.g. "Hot Water Riser"); hostname stays
    # the internal key everywhere - the label is display-only
    label: str = ""

    # Discovery source
    discovery_source: DiscoverySource = DiscoverySource.AUTOMATIC

    # Battery (updated periodically)
    battery: float = -1.0
    
    # Collection settings
    duration: int = 10  # seconds
    interval_value: int = 5
    interval_unit: IntervalUnit = IntervalUnit.MINUTES
    sample_rate: SampleRate = SampleRate.HZ_1666
    accel_range: AccelRange = AccelRange.G_16
    output_folder: Optional[Path] = None
    upload_to_aws: bool = False

    # Start mode settings
    start_mode: StartMode = StartMode.IMMEDIATE
    start_at_time: Optional[QTime] = None  # Used when start_mode == AT_TIME

    # Stop mode settings
    stop_mode: StopMode = StopMode.CONTINUOUS
    repetition_count: int = 1        # Used when stop_mode == AFTER_COUNT
    stop_at_time: Optional[QTime] = None  # Used when stop_mode == AT_TIME
    remaining_repetitions: int = 0   # Runtime tracking for count mode

    # Repeat daily: when the stop time ends the collection window, re-arm
    # for the next occurrence of the start time instead of stopping for good
    repeat_daily: bool = False

    # Runtime anchor of the active window's start (start_at_time for
    # scheduled starts, the actual press-Start moment for immediate ones)
    window_anchor: Optional[QTime] = None

    # Runtime state
    status: SensorStatus = SensorStatus.IDLE
    is_running: bool = False
    countdown_seconds: int = 0

    # Persisted intent: True while the user has started this sensor and
    # nothing has legitimately stopped it (pause, Stop All, stop mode).
    # Survives mDNS drops and app restarts so automation can auto-resume.
    should_be_running: bool = False

    # Reachability probation (runtime only, not persisted).
    # mdns_lost: the mDNS record expired but the sensor stays in the roster;
    # collections keep running as the reachability check. Only when mDNS is
    # lost AND collections fail consecutively is the sensor truly unreachable.
    mdns_lost: bool = False
    consecutive_failures: int = 0
    
    # Statistics
    stats: SensorStats = field(default_factory=SensorStats)
    
    # Progress tracking (0-100)
    progress: int = 0
    
    @property
    def display_name(self) -> str:
        """Label if set, otherwise hostname."""
        return self.label if self.label else self.hostname

    @property
    def interval_seconds(self) -> int:
        """Get the interval in seconds."""
        total = self.interval_unit.to_seconds(self.interval_value)
        # Enforce minimum of 1 second
        return max(1, total)
    
    @property
    def is_configured(self) -> bool:
        """Check if sensor has required configuration to run."""
        return self.output_folder is not None
    
    @property
    def status_text(self) -> str:
        """Human-readable status."""
        status_map = {
            SensorStatus.IDLE: "Idle",
            SensorStatus.WAITING: "Waiting",
            SensorStatus.COLLECTING: "Collecting...",
            SensorStatus.DOWNLOADING: "Downloading...",
            SensorStatus.UPLOADING: "Uploading to AWS...",
            SensorStatus.ERROR: "Error",
            SensorStatus.UNREACHABLE: "Unreachable - retrying...",
            SensorStatus.STOPPING: "Finishing current collection...",
        }
        return status_map.get(self.status, "Unknown")
    
    def reset_countdown(self) -> None:
        """Reset countdown to the configured interval."""
        self.countdown_seconds = self.interval_seconds
    
    def tick_countdown(self) -> bool:
        """
        Decrement countdown by 1 second.
        
        Returns True if countdown reached zero.
        """
        if self.countdown_seconds > 0:
            self.countdown_seconds -= 1
        return self.countdown_seconds == 0
    
    def format_countdown(self) -> str:
        """Format countdown as MM:SS or HH:MM:SS."""
        total = self.countdown_seconds
        hours = total // 3600
        mins = (total % 3600) // 60
        secs = total % 60

        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def seconds_until_start(self) -> int:
        """Seconds from now until start_at_time, rolling to tomorrow if already past."""
        if self.start_at_time is None:
            return 0
        delta = QTime.currentTime().secsTo(self.start_at_time)
        if delta <= 0:
            delta += 86400
        return delta

    def reset_repetitions(self) -> None:
        """Reset remaining repetitions to the configured count."""
        self.remaining_repetitions = self.repetition_count

    @staticmethod
    def _within_window(now: QTime, start: QTime, stop: QTime) -> bool:
        """True if `now` is inside the [start, stop) window.

        Windows where start > stop wrap past midnight (e.g. 5 PM -> 9 AM).
        start == stop is deliberately "always inside" (a 24-hour window).
        """
        if start == stop:
            return True
        if start < stop:
            return start <= now < stop
        return now >= start or now < stop

    def is_within_window(self) -> bool:
        """True if now is inside the active collection window.

        Sensors with no time-bounded stop are always "inside".
        """
        if self.stop_mode != StopMode.AT_TIME or self.stop_at_time is None:
            return True
        anchor = self.window_anchor or self.start_at_time
        if anchor is None:
            return True
        return self._within_window(QTime.currentTime(), anchor, self.stop_at_time)

    @property
    def has_daily_window(self) -> bool:
        """True when repeat-daily windowing governs this sensor's schedule."""
        return (
            self.repeat_daily
            and self.stop_mode == StopMode.AT_TIME
            and self.start_at_time is not None
            and self.stop_at_time is not None
        )

    def should_stop_after_collection(self) -> bool:
        """Check if sensor should stop after current collection completes."""
        if self.stop_mode == StopMode.CONTINUOUS:
            return False
        elif self.stop_mode == StopMode.AFTER_COUNT:
            self.remaining_repetitions -= 1
            return self.remaining_repetitions <= 0
        elif self.stop_mode == StopMode.AT_TIME:
            # Window membership instead of a naive `now >= stop` compare,
            # which broke overnight windows (start 5 PM, stop 9 AM would
            # "stop" immediately at 5:01 PM)
            return not self.is_within_window()
        return False

    def calculate_memory_bytes(self) -> int:
        """Calculate estimated memory usage in bytes."""
        return int(self.sample_rate.value * self.duration * 7)

    def exceeds_memory_limit(self, limit_bytes: int = 16_777_216) -> bool:
        """Check if config exceeds memory limit (default 16MB)."""
        return self.calculate_memory_bytes() >= limit_bytes

    def format_memory_size(self) -> str:
        """Format calculated memory size for display."""
        bytes_val = self.calculate_memory_bytes()
        if bytes_val >= 1_048_576:
            return f"{bytes_val / 1_048_576:.2f} MB"
        return f"{bytes_val} bytes"

