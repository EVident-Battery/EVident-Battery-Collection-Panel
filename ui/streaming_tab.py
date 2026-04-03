"""Live Streaming tab — real-time IMU data via WebSocket."""
from __future__ import annotations

from collections import deque
from enum import Enum, auto
from typing import Dict, List, Optional

import numpy as np

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from models.sensor_config import SensorConfig
from services.streaming_worker import StreamingWorker
from ui.log_widget import LogWidget


# -- Theme constants (match PlotWidget) --
BG_COLOR = "#0F172A"
AXES_BG = "#1E293B"
TEXT_COLOR = "#E2E8F0"
GRID_COLOR = "#334155"

ACCEL_COLORS = ["#3B82F6", "#EF4444", "#10B981"]   # blue, red, green
GYRO_COLORS = ["#F59E0B", "#A78BFA", "#F97316"]     # amber, purple, orange

BUFFER_SIZE = 250  # 5 seconds at 50 Hz


class _State(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    STREAMING = auto()


class StreamingTabWidget(QWidget):
    """Tab for live WebSocket streaming of IMU sensor data."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._sensors: Dict[str, SensorConfig] = {}
        self._worker: Optional[StreamingWorker] = None
        self._state = _State.DISCONNECTED

        # Data buffers
        self._time_buf: deque = deque(maxlen=BUFFER_SIZE)
        self._accel_bufs = {k: deque(maxlen=BUFFER_SIZE) for k in ("ax", "ay", "az")}
        self._gyro_bufs = {k: deque(maxlen=BUFFER_SIZE) for k in ("gx", "gy", "gz")}
        self._t0: Optional[float] = None
        self._sample_count = 0
        self._last_temp = 0.0
        self._data_dirty = False

        self._setup_ui()
        self._connect_signals()
        self._apply_state()

    # -- public API (called by MainWindow) --

    def update_sensors(self, sensors: Dict[str, SensorConfig]) -> None:
        current_text = self._sensor_combo.currentText()
        self._sensors = sensors
        self._sensor_combo.blockSignals(True)
        self._sensor_combo.clear()
        for hostname, cfg in sensors.items():
            self._sensor_combo.addItem(f"{hostname} ({cfg.ip})", cfg.ip)
        # Restore selection if still present
        idx = self._sensor_combo.findText(current_text)
        if idx >= 0:
            self._sensor_combo.setCurrentIndex(idx)
        self._sensor_combo.blockSignals(False)
        self._connect_btn.setEnabled(
            self._state == _State.DISCONNECTED and self._sensor_combo.count() > 0
        )

    def cleanup(self) -> None:
        self._plot_timer.stop()
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.request_disconnect()
            self._worker.wait(3000)
            self._worker = None

    # -- UI setup --

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        # Top controls bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)
        top_bar.addWidget(self._create_connection_group())
        top_bar.addWidget(self._create_controls_group())
        top_bar.addWidget(self._create_status_group(), 1)
        layout.addLayout(top_bar)

        # Plot area
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        self._accel_fig, self._accel_canvas, self._accel_lines = self._create_plot(
            "Acceleration (g)", ("ax", "ay", "az"), ACCEL_COLORS,
        )
        splitter.addWidget(self._accel_canvas)

        self._gyro_fig, self._gyro_canvas, self._gyro_lines = self._create_plot(
            "Angular Rate (dps)", ("gx", "gy", "gz"), GYRO_COLORS,
        )
        splitter.addWidget(self._gyro_canvas)

        layout.addWidget(splitter, 1)

        # Log
        self._log = LogWidget()
        layout.addWidget(self._log)

        # Plot refresh timer (10 Hz)
        self._plot_timer = QTimer()
        self._plot_timer.setInterval(100)

    def _create_connection_group(self) -> QGroupBox:
        grp = QGroupBox("Connection")
        h = QHBoxLayout(grp)
        h.setContentsMargins(8, 4, 8, 4)

        self._sensor_combo = QComboBox()
        self._sensor_combo.setMinimumWidth(180)
        h.addWidget(self._sensor_combo)

        self._connect_btn = QPushButton("Connect")
        self._disconnect_btn = QPushButton("Disconnect")
        h.addWidget(self._connect_btn)
        h.addWidget(self._disconnect_btn)
        return grp

    def _create_controls_group(self) -> QGroupBox:
        grp = QGroupBox("Stream")
        h = QHBoxLayout(grp)
        h.setContentsMargins(8, 4, 8, 4)

        self._start_btn = QPushButton("Start")
        self._stop_btn = QPushButton("Stop")
        h.addWidget(self._start_btn)
        h.addWidget(self._stop_btn)
        return grp

    def _create_status_group(self) -> QGroupBox:
        grp = QGroupBox("Status")
        h = QHBoxLayout(grp)
        h.setContentsMargins(8, 4, 8, 4)

        self._status_label = QLabel("Disconnected")
        self._status_label.setStyleSheet(f"color: {TEXT_COLOR}; font-weight: bold;")
        h.addWidget(self._status_label)

        h.addStretch()

        self._stats_label = QLabel("Samples: 0")
        self._stats_label.setStyleSheet(f"color: {TEXT_COLOR};")
        h.addWidget(self._stats_label)

        self._temp_label = QLabel("")
        self._temp_label.setStyleSheet(f"color: {TEXT_COLOR};")
        h.addWidget(self._temp_label)
        return grp

    def _create_plot(
        self,
        ylabel: str,
        keys: tuple,
        colors: List[str],
    ) -> tuple:
        fig = Figure(facecolor=BG_COLOR, tight_layout=True)
        canvas = FigureCanvasQTAgg(fig)
        ax = fig.add_subplot(111)
        ax.set_facecolor(AXES_BG)
        ax.set_ylabel(ylabel, color=TEXT_COLOR)
        ax.set_xlabel("Time (s)", color=TEXT_COLOR)
        ax.tick_params(colors=TEXT_COLOR)
        ax.grid(True, color=GRID_COLOR, alpha=0.5)
        for spine in ax.spines.values():
            spine.set_color(GRID_COLOR)

        lines: Dict[str, Line2D] = {}
        for key, color in zip(keys, colors):
            (line,) = ax.plot([], [], color=color, linewidth=1.2, label=key)
            lines[key] = line
        ax.legend(loc="upper left", fontsize=8, facecolor=AXES_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)
        return fig, canvas, lines

    # -- signal wiring --

    def _connect_signals(self) -> None:
        self._connect_btn.clicked.connect(self._on_connect)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn.clicked.connect(self._on_stop)
        self._plot_timer.timeout.connect(self._on_plot_tick)

    # -- slots: button handlers --

    @pyqtSlot()
    def _on_connect(self) -> None:
        ip = self._sensor_combo.currentData()
        if not ip:
            return
        self._set_state(_State.CONNECTING)
        self._log.info(f"Connecting to {ip}:81 ...")

        self._worker = StreamingWorker(ip)
        self._worker.connected.connect(self._on_worker_connected)
        self._worker.disconnected.connect(self._on_worker_disconnected)
        self._worker.stream_status.connect(self._on_stream_status)
        self._worker.data_received.connect(self._on_data_received)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.request_disconnect()
        self._plot_timer.stop()

    @pyqtSlot()
    def _on_start(self) -> None:
        if self._worker is not None:
            self._clear_buffers()
            self._worker.request_start()
            self._log.info("Requesting stream start ...")

    @pyqtSlot()
    def _on_stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._log.info("Requesting stream stop ...")

    # -- slots: worker signals --

    @pyqtSlot()
    def _on_worker_connected(self) -> None:
        self._set_state(_State.CONNECTED)
        self._log.success("WebSocket connected")

    @pyqtSlot(str)
    def _on_worker_disconnected(self, reason: str) -> None:
        if self._state == _State.DISCONNECTED:
            return  # already handled
        self._plot_timer.stop()
        self._set_state(_State.DISCONNECTED)
        self._log.warning(f"Disconnected: {reason}")
        self._worker = None

    @pyqtSlot(bool)
    def _on_stream_status(self, is_on: bool) -> None:
        if is_on:
            self._set_state(_State.STREAMING)
            self._plot_timer.start()
            self._log.success("Streaming started")
        else:
            self._plot_timer.stop()
            self._set_state(_State.CONNECTED)
            self._log.info("Streaming stopped")

    @pyqtSlot(dict)
    def _on_data_received(self, frame: dict) -> None:
        t_us = frame.get("t", 0)
        if self._t0 is None:
            self._t0 = t_us
        t_sec = (t_us - self._t0) / 1_000_000.0

        self._time_buf.append(t_sec)
        for key in ("ax", "ay", "az"):
            self._accel_bufs[key].append(frame.get(key, 0.0))
        for key in ("gx", "gy", "gz"):
            self._gyro_bufs[key].append(frame.get(key, 0.0))

        self._sample_count += 1
        self._last_temp = frame.get("temp", self._last_temp)
        self._data_dirty = True

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        self._log.error(msg)

    # -- plot refresh --

    @pyqtSlot()
    def _on_plot_tick(self) -> None:
        if not self._data_dirty:
            return
        self._data_dirty = False

        t = np.array(self._time_buf)

        # Accelerometer
        accel_ax = self._accel_fig.axes[0]
        for key, line in self._accel_lines.items():
            line.set_xdata(t)
            line.set_ydata(np.array(self._accel_bufs[key]))
        accel_ax.relim()
        accel_ax.autoscale_view()
        self._accel_canvas.draw_idle()

        # Gyroscope
        gyro_ax = self._gyro_fig.axes[0]
        for key, line in self._gyro_lines.items():
            line.set_xdata(t)
            line.set_ydata(np.array(self._gyro_bufs[key]))
        gyro_ax.relim()
        gyro_ax.autoscale_view()
        self._gyro_canvas.draw_idle()

        # Stats
        self._stats_label.setText(f"Samples: {self._sample_count:,}")
        self._temp_label.setText(f"Temp: {self._last_temp:.1f} °C")

    # -- state management --

    def _set_state(self, state: _State) -> None:
        self._state = state
        self._apply_state()

    def _apply_state(self) -> None:
        s = self._state
        has_sensors = self._sensor_combo.count() > 0

        self._sensor_combo.setEnabled(s == _State.DISCONNECTED)
        self._connect_btn.setEnabled(s == _State.DISCONNECTED and has_sensors)
        self._disconnect_btn.setEnabled(s in (_State.CONNECTING, _State.CONNECTED, _State.STREAMING))
        self._start_btn.setEnabled(s == _State.CONNECTED)
        self._stop_btn.setEnabled(s == _State.STREAMING)

        labels = {
            _State.DISCONNECTED: ("Disconnected", "#94A3B8"),
            _State.CONNECTING: ("Connecting ...", "#FBBF24"),
            _State.CONNECTED: ("Connected", "#34D399"),
            _State.STREAMING: ("Streaming", "#34D399"),
        }
        text, color = labels[s]
        self._status_label.setText(f"● {text}")
        self._status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    # -- helpers --

    def _clear_buffers(self) -> None:
        self._time_buf.clear()
        for d in self._accel_bufs.values():
            d.clear()
        for d in self._gyro_bufs.values():
            d.clear()
        self._t0 = None
        self._sample_count = 0
        self._last_temp = 0.0
        self._data_dirty = False
