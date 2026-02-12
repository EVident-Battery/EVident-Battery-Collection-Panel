"""Machine Monitoring tab UI widget."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QComboBox, QLineEdit, QFileDialog,
    QFrame, QProgressBar, QGroupBox, QGridLayout,
    QRadioButton, QSizePolicy, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont

from models.sensor_config import SensorConfig, SampleRate
from models.monitoring_config import MonitoringConfig, MonitoringPhase, MonitoringStats, SaveMode
from services.monitoring_pipeline import MonitoringPipeline
from ui.log_widget import LogWidget


# Phase display colors
PHASE_COLORS = {
    MonitoringPhase.IDLE: "#64748B",
    MonitoringPhase.BASELINE: "#3B82F6",
    MonitoringPhase.TRAINING: "#F59E0B",
    MonitoringPhase.MONITORING: "#059669",
    MonitoringPhase.STOPPED: "#DC2626",
    MonitoringPhase.ERROR: "#DC2626",
}

PHASE_LABELS = {
    MonitoringPhase.IDLE: "IDLE",
    MonitoringPhase.BASELINE: "BASELINE",
    MonitoringPhase.TRAINING: "TRAINING",
    MonitoringPhase.MONITORING: "MONITORING",
    MonitoringPhase.STOPPED: "STOPPED",
    MonitoringPhase.ERROR: "ERROR",
}


class MonitoringTabWidget(QWidget):
    """Full monitoring tab UI."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._sensors: Dict[str, SensorConfig] = {}
        self._pipeline = MonitoringPipeline()

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(10)

        # Top section: sensor selection + configuration
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)

        # Left: Sensor Selection
        sensor_group = self._create_sensor_selection()
        top_layout.addWidget(sensor_group, 1)

        # Right: Configuration
        config_group = self._create_config_panel()
        top_layout.addWidget(config_group, 1)

        layout.addWidget(top_widget)

        # Control buttons
        controls = self._create_controls()
        layout.addWidget(controls)

        # Phase indicator
        phase_widget = self._create_phase_indicator()
        layout.addWidget(phase_widget)

        # Stats row
        stats_widget = self._create_stats_row()
        layout.addWidget(stats_widget)

        # Log widget
        self._log_widget = LogWidget()
        layout.addWidget(self._log_widget, 1)

    def _create_sensor_selection(self) -> QWidget:
        group = QGroupBox("Sensor Selection")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        label = QLabel("Select a discovered sensor:")
        label.setStyleSheet("color: #CBD5E1;")
        layout.addWidget(label)

        self._sensor_combo = QComboBox()
        self._sensor_combo.setMinimumWidth(200)
        self._sensor_combo.setPlaceholderText("No sensors available")
        layout.addWidget(self._sensor_combo)

        # Sensor info label
        self._sensor_info = QLabel("")
        self._sensor_info.setStyleSheet("color: #64748B; font-size: 11px;")
        self._sensor_info.setWordWrap(True)
        layout.addWidget(self._sensor_info)

        layout.addStretch()

        return group

    def _create_config_panel(self) -> QWidget:
        group = QGroupBox("Configuration")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 120)

        row = 0

        # Duration
        grid.addWidget(QLabel("Duration:"), row, 0)
        dur_layout = QHBoxLayout()
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 200000)
        self._duration_spin.setValue(10)
        self._duration_spin.setSuffix(" seconds")
        self._duration_spin.setMinimumWidth(120)
        dur_layout.addWidget(self._duration_spin)
        dur_layout.addStretch()
        grid.addLayout(dur_layout, row, 1)

        row += 1

        # Sample Rate
        grid.addWidget(QLabel("Sample Rate:"), row, 0)
        odr_layout = QHBoxLayout()
        self._odr_combo = QComboBox()
        for rate in SampleRate.all_rates():
            self._odr_combo.addItem(rate.display_name, rate)
        self._odr_combo.setCurrentText("104 Hz")
        self._odr_combo.setMinimumWidth(120)
        odr_layout.addWidget(self._odr_combo)
        odr_layout.addStretch()
        grid.addLayout(odr_layout, row, 1)

        row += 1

        # Baseline Runs
        grid.addWidget(QLabel("Baseline Runs:"), row, 0)
        bl_layout = QHBoxLayout()
        self._baseline_spin = QSpinBox()
        self._baseline_spin.setRange(2, 1000)
        self._baseline_spin.setValue(10)
        self._baseline_spin.setMinimumWidth(80)
        bl_layout.addWidget(self._baseline_spin)
        bl_layout.addStretch()
        grid.addLayout(bl_layout, row, 1)

        row += 1

        # Monitor Interval
        grid.addWidget(QLabel("Monitor Interval:"), row, 0)
        mi_layout = QHBoxLayout()
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 3600)
        self._interval_spin.setValue(5)
        self._interval_spin.setSuffix(" seconds")
        self._interval_spin.setMinimumWidth(120)
        mi_layout.addWidget(self._interval_spin)
        mi_layout.addStretch()
        grid.addLayout(mi_layout, row, 1)

        row += 1

        # Save Location section
        grid.addWidget(QLabel("Save Mode:"), row, 0, Qt.AlignTop)
        save_layout = QVBoxLayout()
        save_layout.setSpacing(6)

        # Save Location radio + browse
        loc_row = QHBoxLayout()
        self._save_loc_radio = QRadioButton("Save Location")
        self._save_loc_radio.setStyleSheet("color: #CBD5E1;")
        self._save_loc_radio.toggled.connect(self._on_save_mode_changed)
        loc_row.addWidget(self._save_loc_radio)

        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Select folder...")
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setMinimumWidth(150)
        loc_row.addWidget(self._folder_edit, 1)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        loc_row.addWidget(self._browse_btn)
        save_layout.addLayout(loc_row)

        # Monitor radio
        self._monitor_radio = QRadioButton("Monitor (temporary)")
        self._monitor_radio.setStyleSheet("color: #CBD5E1;")
        self._monitor_radio.setChecked(True)
        save_layout.addWidget(self._monitor_radio)

        grid.addLayout(save_layout, row, 1)

        row += 1

        # License Key
        grid.addWidget(QLabel("License Key:"), row, 0)
        self._license_edit = QLineEdit()
        self._license_edit.setPlaceholderText("Enter license key for AWS uploads")
        self._license_edit.setEchoMode(QLineEdit.Password)
        grid.addWidget(self._license_edit, row, 1)

        layout.addLayout(grid)
        layout.addStretch()

        # Initialize save mode state
        self._on_save_mode_changed()

        return group

    def _create_controls(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border-radius: 6px;
            }
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        self._start_btn = QPushButton("Start Monitoring")
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 24px;
            }
            QPushButton:hover { background-color: #10B981; }
            QPushButton:pressed { background-color: #047857; }
            QPushButton:disabled {
                background-color: #1E3A5F;
                color: #64748B;
            }
        """)
        self._start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self._start_btn)

        layout.addStretch()

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 24px;
            }
            QPushButton:hover { background-color: #EF4444; }
            QPushButton:pressed { background-color: #B91C1C; }
            QPushButton:disabled {
                background-color: #1E3A5F;
                color: #64748B;
            }
        """)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self._stop_btn)

        return frame

    def _create_phase_indicator(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border-radius: 6px;
            }
        """)
        frame.setMinimumHeight(40)
        frame.setMaximumHeight(50)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)

        phase_label = QLabel("Phase:")
        phase_label.setStyleSheet("color: #94A3B8; font-weight: bold;")
        layout.addWidget(phase_label)

        self._phase_dot = QLabel("\u25cf")
        self._phase_dot.setStyleSheet("color: #64748B; font-size: 14px;")
        layout.addWidget(self._phase_dot)

        self._phase_label = QLabel("IDLE")
        self._phase_label.setFont(QFont("Consolas", 12, QFont.Bold))
        self._phase_label.setStyleSheet("color: #64748B;")
        layout.addWidget(self._phase_label)

        self._phase_progress = QProgressBar()
        self._phase_progress.setRange(0, 100)
        self._phase_progress.setValue(0)
        self._phase_progress.setTextVisible(True)
        self._phase_progress.setFormat("%v/%m")
        self._phase_progress.setStyleSheet("""
            QProgressBar {
                background-color: #0F172A;
                border: none;
                border-radius: 4px;
                height: 20px;
                text-align: center;
                color: #E2E8F0;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self._phase_progress, 1)

        return frame

    def _create_stats_row(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #0F172A;
                border-radius: 6px;
                border: 1px solid #334155;
            }
        """)
        frame.setMinimumHeight(50)
        frame.setMaximumHeight(60)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(32)

        # Baseline stat
        self._stat_baseline = self._create_stat_label("Baseline", "0/0")
        layout.addWidget(self._stat_baseline)

        # Monitored stat
        self._stat_monitored = self._create_stat_label("Monitored", "0")
        layout.addWidget(self._stat_monitored)

        # Anomalies stat
        self._stat_anomalies = self._create_stat_label("Anomalies", "0/30")
        layout.addWidget(self._stat_anomalies)

        layout.addStretch()

        return frame

    def _create_stat_label(self, title: str, value: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title_lbl = QLabel(f"{title}:")
        title_lbl.setStyleSheet("color: #64748B; font-size: 12px;")
        layout.addWidget(title_lbl)

        value_lbl = QLabel(value)
        value_lbl.setFont(QFont("Consolas", 14, QFont.Bold))
        value_lbl.setStyleSheet("color: #3B82F6;")
        value_lbl.setObjectName(f"stat_{title.lower()}")
        layout.addWidget(value_lbl)

        return widget

    def _connect_signals(self) -> None:
        self._pipeline.phase_changed.connect(self._on_phase_changed)
        self._pipeline.log_message.connect(self._on_log_message)
        self._pipeline.stats_updated.connect(self._on_stats_updated)
        self._pipeline.pipeline_complete.connect(self._on_pipeline_complete)
        self._sensor_combo.currentTextChanged.connect(self._on_sensor_selected)

    # ----- Public API (called by MainWindow) -----

    def update_sensors(self, sensors: Dict[str, SensorConfig]) -> None:
        """Update the sensor dropdown when sensors are discovered/lost."""
        self._sensors = sensors
        current = self._sensor_combo.currentText()

        self._sensor_combo.blockSignals(True)
        self._sensor_combo.clear()
        for hostname in sorted(sensors.keys()):
            self._sensor_combo.addItem(hostname)

        # Restore selection if still available
        idx = self._sensor_combo.findText(current)
        if idx >= 0:
            self._sensor_combo.setCurrentIndex(idx)
        self._sensor_combo.blockSignals(False)

        # Update info
        self._on_sensor_selected(self._sensor_combo.currentText())

    def stop_pipeline(self) -> None:
        """Stop the pipeline (called on window close)."""
        self._pipeline.stop()

    # ----- Slots -----

    @pyqtSlot()
    def _on_save_mode_changed(self) -> None:
        is_save = self._save_loc_radio.isChecked()
        self._folder_edit.setEnabled(is_save)
        self._browse_btn.setEnabled(is_save)
        dim = "color: #64748B;" if not is_save else ""
        self._folder_edit.setStyleSheet(dim)

    @pyqtSlot()
    def _on_browse_clicked(self) -> None:
        current = self._folder_edit.text()
        start_dir = current if current and Path(current).is_dir() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Select Save Folder", start_dir,
            QFileDialog.DontUseNativeDialog,
        )
        if folder:
            self._folder_edit.setText(folder)

    @pyqtSlot(str)
    def _on_sensor_selected(self, hostname: str) -> None:
        config = self._sensors.get(hostname)
        if config:
            self._sensor_info.setText(f"IP: {config.ip}  |  Battery: {config.battery:.0f}%")
        else:
            self._sensor_info.setText("")

    @pyqtSlot()
    def _on_start_clicked(self) -> None:
        # Validate
        hostname = self._sensor_combo.currentText()
        if not hostname:
            QMessageBox.warning(self, "No Sensor", "Please select a sensor first.")
            return

        sensor = self._sensors.get(hostname)
        if not sensor:
            QMessageBox.warning(self, "Invalid Sensor", "Selected sensor is no longer available.")
            return

        baseline_count = self._baseline_spin.value()
        if baseline_count < 2:
            QMessageBox.warning(self, "Invalid Config", "Baseline runs must be at least 2.")
            return

        save_mode = SaveMode.SAVE_LOCATION if self._save_loc_radio.isChecked() else SaveMode.MONITOR
        save_folder = None
        if save_mode == SaveMode.SAVE_LOCATION:
            folder_text = self._folder_edit.text().strip()
            if not folder_text or not Path(folder_text).is_dir():
                QMessageBox.warning(self, "No Folder", "Please select a valid save folder.")
                return
            save_folder = Path(folder_text)

        odr = self._odr_combo.currentData()

        config = MonitoringConfig(
            hostname=hostname,
            ip=sensor.ip,
            duration=self._duration_spin.value(),
            sample_rate=odr.value if odr else 104.0,
            baseline_count=baseline_count,
            save_mode=save_mode,
            save_folder=save_folder,
            license_key=self._license_edit.text().strip(),
            monitor_interval=self._interval_spin.value(),
        )

        # Disable controls
        self._set_controls_enabled(False)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        # Clear log
        self._log_widget.clear()

        self._pipeline.start(config)

    @pyqtSlot()
    def _on_stop_clicked(self) -> None:
        self._pipeline.stop()

    @pyqtSlot(object)
    def _on_phase_changed(self, phase: MonitoringPhase) -> None:
        color = PHASE_COLORS.get(phase, "#64748B")
        label = PHASE_LABELS.get(phase, "UNKNOWN")

        self._phase_dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        self._phase_label.setText(label)
        self._phase_label.setStyleSheet(f"color: {color};")

        # Update progress bar appearance based on phase
        if phase == MonitoringPhase.TRAINING:
            self._phase_progress.setRange(0, 0)  # Indeterminate
        elif phase == MonitoringPhase.MONITORING:
            self._phase_progress.setRange(0, 0)  # Indeterminate
        elif phase in (MonitoringPhase.STOPPED, MonitoringPhase.ERROR, MonitoringPhase.IDLE):
            self._phase_progress.setRange(0, 100)
            self._phase_progress.setValue(0)

    @pyqtSlot(str, str)
    def _on_log_message(self, message: str, level: str) -> None:
        level_map = {
            "info": self._log_widget.info,
            "success": self._log_widget.success,
            "warning": self._log_widget.warning,
            "error": self._log_widget.error,
            "debug": self._log_widget.debug,
            "status": self._log_widget.status,
        }
        log_fn = level_map.get(level, self._log_widget.info)
        log_fn(message)

    @pyqtSlot(object)
    def _on_stats_updated(self, stats: MonitoringStats) -> None:
        # Update baseline stat
        bl_label = self._stat_baseline.findChild(QLabel, "stat_baseline")
        if bl_label:
            bl_label.setText(f"{stats.baseline_collected}/{stats.baseline_total}")

        # Update monitored stat
        mon_label = self._stat_monitored.findChild(QLabel, "stat_monitored")
        if mon_label:
            mon_label.setText(str(stats.monitor_collected))

        # Update anomalies stat
        anom_label = self._stat_anomalies.findChild(QLabel, "stat_anomalies")
        if anom_label:
            anom_label.setText(f"{stats.anomalies_detected}/{stats.anomaly_limit}")
            # Color red if anomalies detected
            if stats.anomalies_detected > 0:
                anom_label.setStyleSheet("color: #F87171;")
            else:
                anom_label.setStyleSheet("color: #3B82F6;")

        # Update progress bar during baseline phase
        if self._pipeline.phase == MonitoringPhase.BASELINE and stats.baseline_total > 0:
            self._phase_progress.setRange(0, stats.baseline_total)
            self._phase_progress.setValue(stats.baseline_collected)
            self._phase_progress.setFormat(f"{stats.baseline_collected}/{stats.baseline_total}")

    @pyqtSlot()
    def _on_pipeline_complete(self) -> None:
        self._set_controls_enabled(True)
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable configuration controls."""
        self._sensor_combo.setEnabled(enabled)
        self._duration_spin.setEnabled(enabled)
        self._odr_combo.setEnabled(enabled)
        self._baseline_spin.setEnabled(enabled)
        self._interval_spin.setEnabled(enabled)
        self._save_loc_radio.setEnabled(enabled)
        self._monitor_radio.setEnabled(enabled)
        self._license_edit.setEnabled(enabled)
        if enabled:
            self._on_save_mode_changed()
        else:
            self._folder_edit.setEnabled(False)
            self._browse_btn.setEnabled(False)
