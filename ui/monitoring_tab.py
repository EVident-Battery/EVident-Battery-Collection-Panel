"""Machine Monitoring tab UI widget."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import requests
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QComboBox, QLineEdit, QFileDialog,
    QFrame, QProgressBar, QGroupBox, QGridLayout,
    QRadioButton, QSizePolicy, QMessageBox, QScrollArea,
    QToolButton, QTimeEdit, QButtonGroup,
)
from PyQt5.QtCore import Qt, QTime, QThread, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QFont

from models.sensor_config import SensorConfig, SampleRate
from models.monitoring_config import (
    MonitoringConfig, MonitoringPhase, MonitoringStats,
    SaveMode, MonitorStopMode,
)
from services.monitoring_pipeline import MonitoringPipeline
from services.aws_monitor_upload import AWS_ENDPOINT
from ui.log_widget import LogWidget
from ui.sensor_card import SensorCardWidget


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


class LicenseCheckWorker(QThread):
    """Background worker to validate a license key against AWS."""
    check_result = pyqtSignal(bool, str)  # (is_valid, message)

    def __init__(self, license_key: str, endpoint: str, sensor_id: str) -> None:
        super().__init__()
        self._key = license_key
        self._endpoint = endpoint
        self._sensor_id = sensor_id

    def run(self) -> None:
        try:
            headers = {
                "auth-token": self._key,
                "evb-user-type": "customer",
            }
            payload = {
                "sensor_id": self._sensor_id,
                "filenames": ["baseline.json"],
            }
            resp = requests.post(
                self._endpoint, json=payload, headers=headers, timeout=10,
            )
            if resp.status_code in (401, 403):
                self.check_result.emit(
                    False, f"Invalid or expired key (HTTP {resp.status_code})",
                )
            elif resp.status_code == 200:
                self.check_result.emit(True, "License key is valid")
            else:
                self.check_result.emit(
                    False, f"Unexpected response (HTTP {resp.status_code})",
                )
        except Exception as e:
            self.check_result.emit(False, f"Connection error: {e}")


class MonitoringTabWidget(QWidget):
    """Full monitoring tab UI."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._sensors: Dict[str, SensorConfig] = {}
        self._sensor_cards: Dict[str, SensorCardWidget] = {}
        self._selected_hostname: Optional[str] = None
        self._pipeline = MonitoringPipeline()
        self._license_worker: Optional[LicenseCheckWorker] = None

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
        group.setMinimumWidth(280)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(0, 8, 0, 0)
        group_layout.setSpacing(0)

        # Scroll area for sensor cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        # Container for cards
        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background: transparent;")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(4, 4, 4, 4)
        self._cards_layout.setSpacing(8)

        # Placeholder label (shown when no sensors)
        self._no_sensors_label = QLabel("No sensors discovered")
        self._no_sensors_label.setStyleSheet("color: #64748B; font-size: 12px; background: transparent;")
        self._no_sensors_label.setAlignment(Qt.AlignCenter)
        self._cards_layout.addWidget(self._no_sensors_label)

        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_container)
        group_layout.addWidget(scroll, 1)

        return group

    def _create_config_panel(self) -> QWidget:
        group = QGroupBox("Configuration")
        group.setMinimumHeight(250)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(0, 8, 0, 0)
        group_layout.setSpacing(0)

        # Wrap content in scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # ========== 1. License Key ==========
        license_header = QLabel("License Key")
        license_header.setStyleSheet(
            "color: #94A3B8; font-weight: bold; font-size: 12px; background: transparent;"
        )
        layout.addWidget(license_header)

        license_row = QHBoxLayout()
        license_row.setSpacing(6)
        self._license_edit = QLineEdit()
        self._license_edit.setPlaceholderText("Enter license key for AWS uploads")
        self._license_edit.setEchoMode(QLineEdit.Password)
        license_row.addWidget(self._license_edit, 1)

        self._license_check_btn = QPushButton("Check")
        self._license_check_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #E2E8F0;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #475569; }
            QPushButton:disabled { background-color: #1E293B; color: #64748B; }
        """)
        self._license_check_btn.clicked.connect(self._on_check_license)
        license_row.addWidget(self._license_check_btn)

        self._license_status_label = QLabel("")
        self._license_status_label.setFixedWidth(24)
        self._license_status_label.setAlignment(Qt.AlignCenter)
        self._license_status_label.setStyleSheet("background: transparent;")
        license_row.addWidget(self._license_status_label)

        layout.addLayout(license_row)

        # ========== 2. Save Mode ==========
        save_header = QLabel("Save Mode")
        save_header.setStyleSheet(
            "color: #94A3B8; font-weight: bold; font-size: 12px; background: transparent;"
        )
        layout.addWidget(save_header)

        save_layout = QVBoxLayout()
        save_layout.setSpacing(6)

        # Save Location radio + browse
        self._save_mode_group = QButtonGroup(self)
        loc_row = QHBoxLayout()
        self._save_loc_radio = QRadioButton("Save Location")
        self._save_loc_radio.setStyleSheet("color: #CBD5E1; background: transparent;")
        self._save_loc_radio.toggled.connect(self._on_save_mode_changed)
        self._save_mode_group.addButton(self._save_loc_radio)
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
        self._monitor_radio = QRadioButton("Temporary (no save)")
        self._monitor_radio.setStyleSheet("color: #CBD5E1; background: transparent;")
        self._monitor_radio.setChecked(True)
        self._save_mode_group.addButton(self._monitor_radio)
        save_layout.addWidget(self._monitor_radio)

        layout.addLayout(save_layout)

        # ========== 3. Learn Settings (collapsible, collapsed by default) ==========
        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: #334155;")
        sep1.setFixedHeight(1)
        layout.addWidget(sep1)

        learn_header_layout = QHBoxLayout()
        learn_header_layout.setSpacing(4)

        self._learn_toggle_btn = QToolButton()
        self._learn_toggle_btn.setArrowType(Qt.RightArrow)
        self._learn_toggle_btn.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
                color: #94A3B8;
            }
            QToolButton:hover { color: #E2E8F0; }
        """)
        self._learn_toggle_btn.clicked.connect(self._on_toggle_learn_settings)
        learn_header_layout.addWidget(self._learn_toggle_btn)

        learn_title = QLabel("Learn Settings")
        learn_title.setStyleSheet(
            "color: #94A3B8; font-weight: bold; font-size: 12px; "
            "background: transparent;"
        )
        learn_title.setCursor(Qt.PointingHandCursor)
        learn_title.mousePressEvent = lambda _event: self._on_toggle_learn_settings()
        learn_header_layout.addWidget(learn_title)
        learn_header_layout.addStretch()
        layout.addLayout(learn_header_layout)

        # Collapsible content
        self._learn_content = QWidget()
        self._learn_content.setStyleSheet("background: transparent;")
        self._learn_content.setVisible(False)  # collapsed by default

        learn_grid = QGridLayout(self._learn_content)
        learn_grid.setSpacing(8)
        learn_grid.setColumnStretch(1, 1)
        learn_grid.setColumnMinimumWidth(0, 120)

        row = 0

        # Duration
        lbl = QLabel("Duration:")
        lbl.setStyleSheet("background: transparent;")
        learn_grid.addWidget(lbl, row, 0)
        dur_layout = QHBoxLayout()
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 200000)
        self._duration_spin.setValue(20)
        self._duration_spin.setSuffix(" seconds")
        self._duration_spin.setMinimumWidth(120)
        dur_layout.addWidget(self._duration_spin)
        dur_layout.addStretch()
        learn_grid.addLayout(dur_layout, row, 1)

        row += 1

        # Baseline Interval (NEW)
        lbl = QLabel("Baseline Interval:")
        lbl.setStyleSheet("background: transparent;")
        learn_grid.addWidget(lbl, row, 0)
        bi_layout = QHBoxLayout()
        self._baseline_interval_spin = QSpinBox()
        self._baseline_interval_spin.setRange(1, 3600)
        self._baseline_interval_spin.setValue(2)
        self._baseline_interval_spin.setSuffix(" seconds")
        self._baseline_interval_spin.setMinimumWidth(120)
        bi_layout.addWidget(self._baseline_interval_spin)
        bi_layout.addStretch()
        learn_grid.addLayout(bi_layout, row, 1)

        row += 1

        # Sample Rate
        lbl = QLabel("Sample Rate:")
        lbl.setStyleSheet("background: transparent;")
        learn_grid.addWidget(lbl, row, 0)
        odr_layout = QHBoxLayout()
        self._odr_combo = QComboBox()
        for rate in SampleRate.all_rates():
            self._odr_combo.addItem(rate.display_name, rate)
        self._odr_combo.setCurrentText("1666 Hz")
        self._odr_combo.setMinimumWidth(120)
        odr_layout.addWidget(self._odr_combo)
        odr_layout.addStretch()
        learn_grid.addLayout(odr_layout, row, 1)

        row += 1

        # Baseline Runs
        lbl = QLabel("Baseline Runs:")
        lbl.setStyleSheet("background: transparent;")
        learn_grid.addWidget(lbl, row, 0)
        bl_layout = QHBoxLayout()
        self._baseline_spin = QSpinBox()
        self._baseline_spin.setRange(2, 1000)
        self._baseline_spin.setValue(10)
        self._baseline_spin.setMinimumWidth(80)
        bl_layout.addWidget(self._baseline_spin)
        bl_layout.addStretch()
        learn_grid.addLayout(bl_layout, row, 1)

        layout.addWidget(self._learn_content)

        # ========== 4. Monitor Settings (always visible) ==========
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background-color: #334155;")
        sep2.setFixedHeight(1)
        layout.addWidget(sep2)

        monitor_header = QLabel("Monitor Settings")
        monitor_header.setStyleSheet(
            "color: #94A3B8; font-weight: bold; font-size: 12px; background: transparent;"
        )
        layout.addWidget(monitor_header)

        monitor_grid = QGridLayout()
        monitor_grid.setSpacing(8)
        monitor_grid.setColumnStretch(1, 1)
        monitor_grid.setColumnMinimumWidth(0, 120)

        row = 0

        # Monitor Interval
        lbl = QLabel("Monitor Interval:")
        lbl.setStyleSheet("background: transparent;")
        monitor_grid.addWidget(lbl, row, 0)
        mi_layout = QHBoxLayout()
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 3600)
        self._interval_spin.setValue(5)
        self._interval_spin.setSuffix(" seconds")
        self._interval_spin.setMinimumWidth(120)
        mi_layout.addWidget(self._interval_spin)
        mi_layout.addStretch()
        monitor_grid.addLayout(mi_layout, row, 1)

        row += 1

        # Stop Mode
        lbl = QLabel("Stop Mode:")
        lbl.setStyleSheet("background: transparent;")
        monitor_grid.addWidget(lbl, row, 0, Qt.AlignTop)

        stop_mode_layout = QVBoxLayout()
        stop_mode_layout.setSpacing(6)

        # Continuous (default)
        self._stop_mode_group = QButtonGroup(self)
        self._mon_continuous_radio = QRadioButton("Continuous")
        self._mon_continuous_radio.setStyleSheet("color: #CBD5E1; background: transparent;")
        self._mon_continuous_radio.setChecked(True)
        self._mon_continuous_radio.toggled.connect(self._on_monitor_stop_mode_changed)
        self._stop_mode_group.addButton(self._mon_continuous_radio)
        stop_mode_layout.addWidget(self._mon_continuous_radio)

        # At time
        time_row = QHBoxLayout()
        self._mon_time_radio = QRadioButton("At")
        self._mon_time_radio.setStyleSheet("color: #CBD5E1; background: transparent;")
        self._mon_time_radio.toggled.connect(self._on_monitor_stop_mode_changed)
        self._stop_mode_group.addButton(self._mon_time_radio)
        time_row.addWidget(self._mon_time_radio)

        self._mon_stop_time_edit = QTimeEdit()
        self._mon_stop_time_edit.setDisplayFormat("hh:mm AP")
        self._mon_stop_time_edit.setTime(QTime(17, 0))
        self._mon_stop_time_edit.setEnabled(False)
        self._mon_stop_time_edit.setStyleSheet("background-color: #1E3A5F; color: #64748B;")
        time_row.addWidget(self._mon_stop_time_edit)
        time_row.addStretch()
        stop_mode_layout.addLayout(time_row)

        # After count
        count_row = QHBoxLayout()
        self._mon_count_radio = QRadioButton("After")
        self._mon_count_radio.setStyleSheet("color: #CBD5E1; background: transparent;")
        self._mon_count_radio.toggled.connect(self._on_monitor_stop_mode_changed)
        self._stop_mode_group.addButton(self._mon_count_radio)
        count_row.addWidget(self._mon_count_radio)

        self._mon_count_spin = QSpinBox()
        self._mon_count_spin.setRange(1, 9999)
        self._mon_count_spin.setValue(10)
        self._mon_count_spin.setMinimumWidth(70)
        self._mon_count_spin.setEnabled(False)
        count_row.addWidget(self._mon_count_spin)

        count_suffix = QLabel("collections")
        count_suffix.setStyleSheet("background: transparent; color: #CBD5E1;")
        count_row.addWidget(count_suffix)
        count_row.addStretch()
        stop_mode_layout.addLayout(count_row)

        monitor_grid.addLayout(stop_mode_layout, row, 1)

        layout.addLayout(monitor_grid)
        layout.addStretch()

        # Add content widget to scroll area, scroll area to group
        scroll.setWidget(content)
        group_layout.addWidget(scroll)

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

        # Start New Program button (green)
        self._start_new_btn = QPushButton("Start New Program")
        self._start_new_btn.setStyleSheet("""
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
        self._start_new_btn.clicked.connect(self._on_start_new_clicked)
        layout.addWidget(self._start_new_btn)

        # Continue Last Program button (blue)
        self._continue_btn = QPushButton("Continue Last Program")
        self._continue_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 24px;
            }
            QPushButton:hover { background-color: #60A5FA; }
            QPushButton:pressed { background-color: #2563EB; }
            QPushButton:disabled {
                background-color: #1E3A5F;
                color: #64748B;
            }
        """)
        self._continue_btn.clicked.connect(self._on_continue_clicked)
        layout.addWidget(self._continue_btn)

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

    # ----- Public API (called by MainWindow) -----

    def update_sensors(self, sensors: Dict[str, SensorConfig]) -> None:
        """Update the sensor cards when sensors are discovered/lost."""
        self._sensors = sensors

        # Remove cards for sensors that no longer exist
        removed = [h for h in self._sensor_cards if h not in sensors]
        for hostname in removed:
            card = self._sensor_cards.pop(hostname)
            self._cards_layout.removeWidget(card)
            card.deleteLater()
            if self._selected_hostname == hostname:
                self._selected_hostname = None

        # Add cards for new sensors, update existing ones
        for hostname, config in sorted(sensors.items()):
            if hostname not in self._sensor_cards:
                card = SensorCardWidget(config, show_controls=False)
                card.selected.connect(self._on_sensor_card_selected)
                self._sensor_cards[hostname] = card
                # Insert before the stretch (last item in layout)
                self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            else:
                self._sensor_cards[hostname].update_config(config)

        # Show/hide placeholder
        self._no_sensors_label.setVisible(len(sensors) == 0)

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
    def _on_sensor_card_selected(self, hostname: str) -> None:
        """Handle sensor card selection."""
        # Deselect previous
        if self._selected_hostname and self._selected_hostname in self._sensor_cards:
            self._sensor_cards[self._selected_hostname].set_selected(False)

        self._selected_hostname = hostname

        # Select new
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].set_selected(True)

    @pyqtSlot()
    def _on_toggle_learn_settings(self) -> None:
        is_visible = self._learn_content.isVisible()
        self._learn_content.setVisible(not is_visible)
        self._learn_toggle_btn.setArrowType(
            Qt.DownArrow if not is_visible else Qt.RightArrow
        )

    @pyqtSlot()
    def _on_check_license(self) -> None:
        key = self._license_edit.text().strip()
        if not key:
            self._license_status_label.setText("!")
            self._license_status_label.setStyleSheet(
                "color: #DC2626; font-weight: bold; font-size: 16px; background: transparent;"
            )
            return

        if not self._selected_hostname:
            self._license_status_label.setText("!")
            self._license_status_label.setStyleSheet(
                "color: #DC2626; font-weight: bold; font-size: 16px; background: transparent;"
            )
            QMessageBox.warning(
                self, "No Sensor", "Please select a sensor before checking the key.",
            )
            return

        self._license_check_btn.setEnabled(False)
        self._license_status_label.setText("...")
        self._license_status_label.setStyleSheet(
            "color: #94A3B8; background: transparent;"
        )

        self._license_worker = LicenseCheckWorker(key, AWS_ENDPOINT, self._selected_hostname)
        self._license_worker.check_result.connect(self._on_license_result)
        self._license_worker.finished.connect(
            lambda: self._license_check_btn.setEnabled(True)
        )
        self._license_worker.start()

    @pyqtSlot(bool, str)
    def _on_license_result(self, is_valid: bool, message: str) -> None:
        if is_valid:
            self._license_status_label.setText("\u2713")
            self._license_status_label.setStyleSheet(
                "color: #059669; font-size: 16px; font-weight: bold; background: transparent;"
            )
        else:
            self._license_status_label.setText("\u2717")
            self._license_status_label.setStyleSheet(
                "color: #DC2626; font-size: 16px; font-weight: bold; background: transparent;"
            )

    @pyqtSlot()
    def _on_monitor_stop_mode_changed(self) -> None:
        count_enabled = self._mon_count_radio.isChecked()
        time_enabled = self._mon_time_radio.isChecked()

        self._mon_count_spin.setEnabled(count_enabled)
        self._mon_stop_time_edit.setEnabled(time_enabled)

        self._mon_stop_time_edit.setStyleSheet(
            "background-color: #1E3A5F; color: #E2E8F0;"
            if time_enabled else
            "background-color: #1E3A5F; color: #64748B;"
        )

    def _build_config(self, skip_baseline: bool) -> Optional[MonitoringConfig]:
        """Build MonitoringConfig from UI state. Returns None if validation fails."""
        hostname = self._selected_hostname
        if not hostname:
            QMessageBox.warning(self, "No Sensor", "Please select a sensor first.")
            return None

        sensor = self._sensors.get(hostname)
        if not sensor:
            QMessageBox.warning(
                self, "Invalid Sensor", "Selected sensor is no longer available.",
            )
            return None

        baseline_count = self._baseline_spin.value()
        if baseline_count < 2 and not skip_baseline:
            QMessageBox.warning(
                self, "Invalid Config", "Baseline runs must be at least 2.",
            )
            return None

        save_mode = (
            SaveMode.SAVE_LOCATION if self._save_loc_radio.isChecked()
            else SaveMode.MONITOR
        )
        save_folder = None
        if save_mode == SaveMode.SAVE_LOCATION:
            folder_text = self._folder_edit.text().strip()
            if not folder_text or not Path(folder_text).is_dir():
                QMessageBox.warning(
                    self, "No Folder", "Please select a valid save folder.",
                )
                return None
            save_folder = Path(folder_text)

        odr = self._odr_combo.currentData()

        # Determine monitor stop mode
        if self._mon_continuous_radio.isChecked():
            stop_mode = MonitorStopMode.CONTINUOUS
        elif self._mon_time_radio.isChecked():
            stop_mode = MonitorStopMode.AT_TIME
        else:
            stop_mode = MonitorStopMode.AFTER_COUNT

        return MonitoringConfig(
            hostname=hostname,
            ip=sensor.ip,
            duration=self._duration_spin.value(),
            sample_rate=odr.value if odr else 104.0,
            baseline_count=baseline_count,
            save_mode=save_mode,
            save_folder=save_folder,
            license_key=self._license_edit.text().strip(),
            monitor_interval=self._interval_spin.value(),
            baseline_interval=self._baseline_interval_spin.value(),
            monitor_stop_mode=stop_mode,
            monitor_stop_count=self._mon_count_spin.value(),
            monitor_stop_time=(
                self._mon_stop_time_edit.time()
                if stop_mode == MonitorStopMode.AT_TIME else None
            ),
            skip_baseline=skip_baseline,
        )

    def _start_pipeline(self, config: MonitoringConfig) -> None:
        """Common start logic for both start buttons."""
        self._set_controls_enabled(False)
        self._start_new_btn.setEnabled(False)
        self._continue_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._log_widget.clear()
        self._pipeline.start(config)

    @pyqtSlot()
    def _on_start_new_clicked(self) -> None:
        """Start monitoring from scratch (baseline -> training -> monitoring)."""
        config = self._build_config(skip_baseline=False)
        if config is None:
            return
        self._start_pipeline(config)

    @pyqtSlot()
    def _on_continue_clicked(self) -> None:
        """Skip baseline, load existing baseline.json, go straight to monitoring."""
        save_mode = (
            SaveMode.SAVE_LOCATION if self._save_loc_radio.isChecked()
            else SaveMode.MONITOR
        )

        if save_mode == SaveMode.MONITOR:
            QMessageBox.warning(
                self, "No Baseline Available",
                "Temporary (no save) mode does not retain baseline data.\n"
                "Please select 'Save Location' mode with an existing baseline folder.",
            )
            return

        folder_text = self._folder_edit.text().strip()
        if not folder_text:
            QMessageBox.warning(
                self, "No Folder", "Please select a save folder first.",
            )
            return

        baseline_path = Path(folder_text) / "baseline.json"
        if not baseline_path.exists():
            QMessageBox.warning(
                self, "No Baseline Found",
                f"No baseline.json found in:\n{folder_text}\n\n"
                "Run 'Start New Program' first to create a baseline.",
            )
            return

        config = self._build_config(skip_baseline=True)
        if config is None:
            return
        self._start_pipeline(config)

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
        self._start_new_btn.setEnabled(True)
        self._continue_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable configuration controls."""
        for card in self._sensor_cards.values():
            card.setEnabled(enabled)
        self._duration_spin.setEnabled(enabled)
        self._odr_combo.setEnabled(enabled)
        self._baseline_spin.setEnabled(enabled)
        self._baseline_interval_spin.setEnabled(enabled)
        self._interval_spin.setEnabled(enabled)
        self._save_loc_radio.setEnabled(enabled)
        self._monitor_radio.setEnabled(enabled)
        self._license_edit.setEnabled(enabled)
        self._license_check_btn.setEnabled(enabled)
        self._mon_continuous_radio.setEnabled(enabled)
        self._mon_count_radio.setEnabled(enabled)
        self._mon_time_radio.setEnabled(enabled)
        if enabled:
            self._on_save_mode_changed()
            self._on_monitor_stop_mode_changed()
        else:
            self._folder_edit.setEnabled(False)
            self._browse_btn.setEnabled(False)
            self._mon_count_spin.setEnabled(False)
            self._mon_stop_time_edit.setEnabled(False)
