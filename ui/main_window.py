"""Main application window - Evident Battery Device Hub."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QComboBox, QLineEdit, QFileDialog,
    QFrame, QScrollArea, QSplitter, QProgressBar,
    QGroupBox, QGridLayout, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer, QTime, QElapsedTimer, QSize
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtSvg import QSvgWidget, QSvgRenderer

from models.sensor_config import SensorConfig, SensorStatus, IntervalUnit, SampleRate
from services.discovery import DiscoveryController
from services.collector import CollectorService, CollectionStatus, CollectionResult
from services.multi_scheduler import MultiSensorScheduler
from ui.sensor_card import SensorCardWidget
from ui.log_widget import LogWidget, LogLevel


# Stylesheet for the entire application
APP_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0F172A;
    color: #E2E8F0;
}

QLabel {
    color: #CBD5E1;
}

QGroupBox {
    font-weight: bold;
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    background-color: #1E293B;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: #94A3B8;
}

QPushButton {
    background-color: #334155;
    color: #E2E8F0;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #475569;
}

QPushButton:pressed {
    background-color: #1E293B;
}

QPushButton:disabled {
    background-color: #1E293B;
    color: #475569;
}

QPushButton#startAllButton {
    background-color: #059669;
    color: white;
    font-size: 13px;
    padding: 10px 20px;
}

QPushButton#startAllButton:hover {
    background-color: #10B981;
}

QPushButton#stopAllButton {
    background-color: #DC2626;
    color: white;
    font-size: 13px;
    padding: 10px 20px;
}

QPushButton#stopAllButton:hover {
    background-color: #EF4444;
}

QSpinBox, QComboBox, QLineEdit {
    background-color: #1E293B;
    color: #E2E8F0;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 20px;
}

QSpinBox:focus, QComboBox:focus, QLineEdit:focus {
    border-color: #3B82F6;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #94A3B8;
    margin-right: 8px;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:vertical {
    background-color: #1E293B;
    width: 10px;
    border: none;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #475569;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #64748B;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QProgressBar {
    background-color: #1E293B;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #3B82F6;
    border-radius: 4px;
}

QCheckBox {
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #475569;
    background-color: #1E293B;
}

QCheckBox::indicator:checked {
    background-color: #3B82F6;
    border-color: #3B82F6;
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjQiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBvbHlsaW5lIHBvaW50cz0iMjAgNiA5IDE3IDQgMTIiPjwvcG9seWxpbmU+PC9zdmc+);
}

QSplitter::handle {
    background-color: #334155;
}

QSplitter::handle:vertical {
    height: 4px;
}
"""


class MainWindow(QMainWindow):
    """Main application window - Evident Battery Device Hub."""
    
    def __init__(self) -> None:
        super().__init__()
        
        # Sensor configs and cards
        self._sensors: Dict[str, SensorConfig] = {}
        self._sensor_cards: Dict[str, SensorCardWidget] = {}
        self._selected_hostname: Optional[str] = None
        
        # Services
        self._discovery = DiscoveryController()
        self._collector = CollectorService()
        self._scheduler = MultiSensorScheduler()
        
        # Uptime tracking
        self._start_time = QTime.currentTime()
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._update_uptime)
        
        self._setup_ui()
        self._connect_signals()
        self._start_discovery()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Evident Battery Device Hub")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 850)
        self.setStyleSheet(APP_STYLESHEET)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 12)
        main_layout.setSpacing(12)
        
        # Header
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Main content splitter
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        
        # Top section: sensor list + settings
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)
        
        # Left: Discovered sensors panel (scrollable)
        sensor_panel = self._create_sensor_panel()
        top_layout.addWidget(sensor_panel, 1)
        
        # Right: Settings panel
        settings_panel = self._create_settings_panel()
        top_layout.addWidget(settings_panel, 1)
        
        splitter.addWidget(top_widget)
        
        # Status bar above log
        self._status_bar = self._create_status_bar()
        splitter.addWidget(self._status_bar)
        
        # Bottom: Log console
        self._log_widget = LogWidget()
        splitter.addWidget(self._log_widget)
        
        splitter.setSizes([380, 40, 220])
        main_layout.addWidget(splitter, 1)
        
        # Start uptime timer
        self._uptime_timer.start()
        
        # Footer
        footer = self._create_footer()
        main_layout.addWidget(footer)

    def _create_header(self) -> QWidget:
        """Create the header with title and global controls."""
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #CBD5E1;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 16, 20, 16)
        
        # Left: Logo - preserve aspect ratio
        import os
        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media", "LogoEVident-Vector.svg")
        if os.path.exists(logo_path):
            logo = QSvgWidget(logo_path)
            logo.setStyleSheet("background: transparent;")
            # Calculate correct width from SVG's native aspect ratio
            renderer = QSvgRenderer(logo_path)
            native_size = renderer.defaultSize()
            if native_size.height() > 0:
                aspect_ratio = native_size.width() / native_size.height()
                # Fill header vertical space (header padding is 16px top/bottom)
                target_height = 55
                target_width = int(target_height * aspect_ratio)
                logo.setFixedSize(target_width, target_height)
            layout.addWidget(logo)
        
        layout.addStretch()
        
        # Center: Title
        title = QLabel("Evident Battery Device Hub")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setStyleSheet("color: #0F172A;")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Right side: Uptime + Controls
        right_section = QHBoxLayout()
        right_section.setSpacing(16)
        
        # Uptime counter - bigger and bolder
        uptime_section = QVBoxLayout()
        uptime_section.setSpacing(0)
        uptime_section.setAlignment(Qt.AlignCenter)
        
        self._uptime_label = QLabel("00:00:00")
        self._uptime_label.setFont(QFont("Consolas", 16, QFont.Bold))
        self._uptime_label.setStyleSheet("color: #334155;")
        self._uptime_label.setAlignment(Qt.AlignCenter)
        uptime_section.addWidget(self._uptime_label)
        
        uptime_hint = QLabel("Uptime")
        uptime_hint.setStyleSheet("color: #64748B; font-size: 10px;")
        uptime_hint.setAlignment(Qt.AlignCenter)
        uptime_section.addWidget(uptime_hint)
        
        right_section.addLayout(uptime_section)
        right_section.addSpacing(8)
        
        # Reset button (was Refresh)
        self._refresh_btn = QPushButton("↻ Reset")
        self._refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #E2E8F0;
                color: #1E293B;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #CBD5E1;
            }
            QPushButton:pressed {
                background-color: #94A3B8;
            }
        """)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        right_section.addWidget(self._refresh_btn)
        
        # Start All button
        self._start_all_btn = QPushButton("▶  Start All")
        self._start_all_btn.setObjectName("startAllButton")
        self._start_all_btn.clicked.connect(self._on_start_all_clicked)
        right_section.addWidget(self._start_all_btn)
        
        # Stop All button
        self._stop_all_btn = QPushButton("■  Stop All")
        self._stop_all_btn.setObjectName("stopAllButton")
        self._stop_all_btn.setVisible(False)
        self._stop_all_btn.clicked.connect(self._on_stop_all_clicked)
        right_section.addWidget(self._stop_all_btn)
        
        layout.addLayout(right_section)
        
        return header

    def _create_sensor_panel(self) -> QWidget:
        """Create the scrollable discovered sensors panel."""
        group = QGroupBox("Discovered Sensors")
        group.setMinimumWidth(280)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        
        # Scroll area for sensor cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Container for cards
        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(4, 4, 4, 4)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()
        
        scroll.setWidget(self._cards_container)
        layout.addWidget(scroll, 1)
        
        # Blink button
        btn_layout = QHBoxLayout()
        self._blink_btn = QPushButton("💡 Blink Selected")
        self._blink_btn.setEnabled(False)
        self._blink_btn.clicked.connect(self._on_blink_clicked)
        btn_layout.addWidget(self._blink_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return group

    def _create_settings_panel(self) -> QWidget:
        """Create the settings panel for selected sensor."""
        group = QGroupBox("Sensor Settings")
        layout = QVBoxLayout(group)
        layout.setSpacing(12)
        
        # Selected sensor info
        self._selected_label = QLabel("No sensor selected")
        self._selected_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self._selected_label.setStyleSheet("color: #F1F5F9;")
        layout.addWidget(self._selected_label)
        
        # Settings grid
        settings_grid = QGridLayout()
        settings_grid.setSpacing(10)
        settings_grid.setColumnStretch(1, 1)
        
        row = 0
        
        # Duration
        settings_grid.addWidget(QLabel("Duration:"), row, 0)
        duration_layout = QHBoxLayout()
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 300)
        self._duration_spin.setValue(10)
        self._duration_spin.setSuffix(" seconds")
        self._duration_spin.setMinimumWidth(120)
        self._duration_spin.valueChanged.connect(self._on_settings_changed)
        duration_layout.addWidget(self._duration_spin)
        duration_layout.addStretch()
        settings_grid.addLayout(duration_layout, row, 1)
        
        row += 1
        
        # Interval (two-part: value + unit)
        settings_grid.addWidget(QLabel("Interval:"), row, 0)
        interval_layout = QHBoxLayout()
        interval_layout.setSpacing(8)
        
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 999)
        self._interval_spin.setValue(5)
        self._interval_spin.setMinimumWidth(80)
        self._interval_spin.valueChanged.connect(self._on_settings_changed)
        interval_layout.addWidget(self._interval_spin)
        
        self._interval_unit_combo = QComboBox()
        for unit in IntervalUnit.all_units():
            self._interval_unit_combo.addItem(unit)
        self._interval_unit_combo.setCurrentText("minutes")
        self._interval_unit_combo.setMinimumWidth(100)
        self._interval_unit_combo.currentTextChanged.connect(self._on_settings_changed)
        interval_layout.addWidget(self._interval_unit_combo)
        
        # Minimum indicator
        self._interval_hint = QLabel("(min 30s)")
        self._interval_hint.setStyleSheet("color: #64748B; font-size: 10px;")
        interval_layout.addWidget(self._interval_hint)
        
        interval_layout.addStretch()
        settings_grid.addLayout(interval_layout, row, 1)
        
        row += 1
        
        # Sample Rate (ODR)
        settings_grid.addWidget(QLabel("Sample Rate:"), row, 0)
        odr_layout = QHBoxLayout()
        self._odr_combo = QComboBox()
        for rate in SampleRate.all_rates():
            self._odr_combo.addItem(rate.display_name, rate)
        self._odr_combo.setCurrentText("104 Hz")
        self._odr_combo.setMinimumWidth(100)
        self._odr_combo.currentIndexChanged.connect(self._on_settings_changed)
        odr_layout.addWidget(self._odr_combo)
        odr_layout.addStretch()
        settings_grid.addLayout(odr_layout, row, 1)
        
        row += 1
        
        # Output folder
        settings_grid.addWidget(QLabel("Save Location:"), row, 0)
        folder_layout = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Select a folder...")
        self._folder_edit.setReadOnly(True)
        folder_layout.addWidget(self._folder_edit, 1)
        
        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        folder_layout.addWidget(self._browse_btn)
        settings_grid.addLayout(folder_layout, row, 1)
        
        row += 1
        
        # AWS upload
        self._aws_checkbox = QCheckBox("Upload to AWS after each collection")
        self._aws_checkbox.setChecked(True)
        self._aws_checkbox.stateChanged.connect(self._on_settings_changed)
        settings_grid.addWidget(self._aws_checkbox, row, 0, 1, 2)
        
        layout.addLayout(settings_grid)
        
        # Apply to All button
        apply_layout = QHBoxLayout()
        apply_layout.addStretch()
        self._apply_all_btn = QPushButton("📋 Apply to All Sensors")
        self._apply_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #1D4ED8;
                color: white;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QPushButton:disabled {
                background-color: #1E3A5F;
                color: #64748B;
            }
        """)
        self._apply_all_btn.clicked.connect(self._on_apply_to_all)
        apply_layout.addWidget(self._apply_all_btn)
        layout.addLayout(apply_layout)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #334155;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        
        # Progress
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("Progress:"))
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        progress_layout.addWidget(self._progress_bar, 1)
        layout.addLayout(progress_layout)
        
        # Statistics
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            QFrame {
                background-color: #0F172A;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setSpacing(20)
        
        self._stats_collections = self._create_stat_widget("Collections", "0")
        stats_layout.addWidget(self._stats_collections)
        
        self._stats_uploaded = self._create_stat_widget("Uploaded", "0")
        stats_layout.addWidget(self._stats_uploaded)
        
        self._stats_errors = self._create_stat_widget("Errors", "0")
        stats_layout.addWidget(self._stats_errors)
        
        stats_layout.addStretch()
        layout.addWidget(stats_frame)
        
        layout.addStretch()
        
        # Initially disable until sensor selected
        self._set_settings_enabled(False)
        
        return group

    def _create_stat_widget(self, label: str, value: str) -> QWidget:
        """Create a statistics display widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        value_lbl = QLabel(value)
        value_lbl.setFont(QFont("Segoe UI", 18, QFont.Bold))
        value_lbl.setStyleSheet("color: #3B82F6;")
        value_lbl.setObjectName(f"stat_{label.lower()}")
        layout.addWidget(value_lbl)
        
        label_lbl = QLabel(label)
        label_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        layout.addWidget(label_lbl)
        
        return widget

    def _create_status_bar(self) -> QWidget:
        """Create the status bar above log console."""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border-radius: 6px;
            }
        """)
        frame.setMinimumHeight(32)
        frame.setMaximumHeight(40)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 0, 12, 0)
        
        status_icon = QLabel("●")
        status_icon.setStyleSheet("color: #22C55E; font-size: 10px;")
        layout.addWidget(status_icon)
        
        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("color: #94A3B8;")
        layout.addWidget(self._status_label)
        
        layout.addStretch()
        
        return frame

    def _create_footer(self) -> QWidget:
        """Create the footer with support info."""
        footer = QFrame()
        footer.setFixedHeight(32)
        
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(8, 0, 8, 0)
        
        support = QLabel("Support: info@batteryevidence.com")
        support.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(support)
        
        layout.addStretch()
        
        version = QLabel("v1.0.0")
        version.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(version)
        
        return footer

    def _set_settings_enabled(self, enabled: bool) -> None:
        """Enable/disable settings controls."""
        self._duration_spin.setEnabled(enabled)
        self._interval_spin.setEnabled(enabled)
        self._interval_unit_combo.setEnabled(enabled)
        self._odr_combo.setEnabled(enabled)
        self._browse_btn.setEnabled(enabled)
        self._aws_checkbox.setEnabled(enabled)
        self._apply_all_btn.setEnabled(enabled)

    def _connect_signals(self) -> None:
        """Connect all service signals."""
        # Discovery
        self._discovery.signals.device_found.connect(self._on_device_found)
        self._discovery.signals.device_lost.connect(self._on_device_lost)
        
        # Collector
        self._collector.status_changed.connect(self._on_collection_status)
        self._collector.progress_updated.connect(self._on_collection_progress)
        self._collector.collection_complete.connect(self._on_collection_complete)
        
        # Multi-scheduler
        self._scheduler.trigger_collection.connect(self._on_trigger_collection)
        self._scheduler.countdown_tick.connect(self._on_countdown_tick)

    def _start_discovery(self) -> None:
        """Start sensor discovery."""
        self._log_widget.info("Starting sensor discovery...")
        self._discovery.start()

    @pyqtSlot(str, str)
    def _on_device_found(self, hostname: str, ip: str) -> None:
        """Handle discovered sensor."""
        if hostname in self._sensors:
            return
        
        # Fetch battery
        battery = -1
        try:
            from services.sensor_client import SensorClient
            client = SensorClient(ip)
            status = client.get_status()
            battery = status.get("Battery SOC", -1)
        except Exception:
            pass
        
        # Create config
        config = SensorConfig(hostname=hostname, ip=ip, battery=battery)
        self._sensors[hostname] = config
        self._scheduler.register_sensor(config)
        
        # Create card
        card = SensorCardWidget(config)
        card.selected.connect(self._on_sensor_card_selected)
        card.play_clicked.connect(self._on_sensor_play)
        card.pause_clicked.connect(self._on_sensor_pause)
        
        self._sensor_cards[hostname] = card
        
        # Insert before stretch
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
        
        if battery >= 0:
            self._log_widget.success(f"Discovered: {hostname} ({ip}) - Battery: {battery:.0f}%")
        else:
            self._log_widget.success(f"Discovered: {hostname} ({ip})")

    @pyqtSlot(str)
    def _on_device_lost(self, hostname: str) -> None:
        """Handle lost sensor."""
        if hostname not in self._sensors:
            return
        
        self._scheduler.unregister_sensor(hostname)
        del self._sensors[hostname]
        
        card = self._sensor_cards.pop(hostname, None)
        if card:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        
        if self._selected_hostname == hostname:
            self._selected_hostname = None
            self._selected_label.setText("No sensor selected")
            self._set_settings_enabled(False)
        
        self._log_widget.warning(f"Sensor disconnected: {hostname}")

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
        
        self._blink_btn.setEnabled(True)
        self._set_settings_enabled(True)
        
        # Load config into settings panel
        config = self._sensors.get(hostname)
        if config:
            self._selected_label.setText(f"Selected: {config.hostname}")
            self._load_config_to_ui(config)

    def _load_config_to_ui(self, config: SensorConfig) -> None:
        """Load sensor config into UI controls."""
        # Block signals to avoid triggering saves
        self._duration_spin.blockSignals(True)
        self._interval_spin.blockSignals(True)
        self._interval_unit_combo.blockSignals(True)
        self._odr_combo.blockSignals(True)
        self._aws_checkbox.blockSignals(True)
        
        self._duration_spin.setValue(config.duration)
        self._interval_spin.setValue(config.interval_value)
        self._interval_unit_combo.setCurrentText(config.interval_unit.value)
        self._odr_combo.setCurrentText(config.sample_rate.display_name)
        self._aws_checkbox.setChecked(config.upload_to_aws)
        
        if config.output_folder:
            self._folder_edit.setText(str(config.output_folder))
        else:
            self._folder_edit.setText("")
        
        # Update stats
        self._update_stats_display(config)
        
        # Unblock signals
        self._duration_spin.blockSignals(False)
        self._interval_spin.blockSignals(False)
        self._interval_unit_combo.blockSignals(False)
        self._odr_combo.blockSignals(False)
        self._aws_checkbox.blockSignals(False)

    def _update_stats_display(self, config: SensorConfig) -> None:
        """Update statistics display for a sensor."""
        collections_lbl = self._stats_collections.findChild(QLabel, "stat_collections")
        uploaded_lbl = self._stats_uploaded.findChild(QLabel, "stat_uploaded")
        errors_lbl = self._stats_errors.findChild(QLabel, "stat_errors")
        
        if collections_lbl:
            collections_lbl.setText(str(config.stats.collections))
        if uploaded_lbl:
            uploaded_lbl.setText(str(config.stats.uploaded))
        if errors_lbl:
            errors_lbl.setText(str(config.stats.errors))

    @pyqtSlot()
    def _on_settings_changed(self) -> None:
        """Handle settings change - save to selected config."""
        if not self._selected_hostname:
            return
        
        config = self._sensors.get(self._selected_hostname)
        if not config:
            return
        
        config.duration = self._duration_spin.value()
        config.interval_value = self._interval_spin.value()
        config.interval_unit = IntervalUnit(self._interval_unit_combo.currentText())
        config.sample_rate = self._odr_combo.currentData()
        config.upload_to_aws = self._aws_checkbox.isChecked()
        
        # Update card
        if self._selected_hostname in self._sensor_cards:
            self._sensor_cards[self._selected_hostname].refresh()

    @pyqtSlot()
    def _on_apply_to_all(self) -> None:
        """Apply current settings to all sensors."""
        if not self._selected_hostname:
            return
        
        source_config = self._sensors.get(self._selected_hostname)
        if not source_config:
            return
        
        count = 0
        for hostname, config in self._sensors.items():
            if hostname == self._selected_hostname:
                continue
            
            config.duration = source_config.duration
            config.interval_value = source_config.interval_value
            config.interval_unit = source_config.interval_unit
            config.sample_rate = source_config.sample_rate
            config.output_folder = source_config.output_folder
            config.upload_to_aws = source_config.upload_to_aws
            
            # Update card
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].refresh()
            
            count += 1
        
        if count > 0:
            self._log_widget.success(f"Applied settings to {count} other sensor(s)")

    @pyqtSlot()
    def _on_browse_clicked(self) -> None:
        """Open folder selection dialog."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(Path.home())
        )
        if folder and self._selected_hostname:
            config = self._sensors.get(self._selected_hostname)
            if config:
                config.output_folder = Path(folder)
                self._folder_edit.setText(folder)
                self._log_widget.info(f"Output folder set for {self._selected_hostname}: {folder}")
                
                # Update card
                if self._selected_hostname in self._sensor_cards:
                    self._sensor_cards[self._selected_hostname].refresh()

    @pyqtSlot()
    def _on_refresh_clicked(self) -> None:
        """Refresh sensor discovery."""
        # Clear all
        for hostname in list(self._sensors.keys()):
            self._on_device_lost(hostname)
        
        self._discovery.stop()
        self._discovery.start()
        self._log_widget.info("Refreshing sensor discovery...")

    @pyqtSlot()
    def _on_blink_clicked(self) -> None:
        """Blink selected sensor."""
        if not self._selected_hostname:
            return
        
        config = self._sensors.get(self._selected_hostname)
        if config:
            from services.sensor_client import SensorClient
            try:
                client = SensorClient(config.ip)
                client.blink()
                self._log_widget.info(f"Blinking {config.hostname}...")
            except Exception as e:
                self._log_widget.error(f"Failed to blink: {e}")

    @pyqtSlot(str)
    def _on_sensor_play(self, hostname: str) -> None:
        """Handle play button on sensor card."""
        config = self._sensors.get(hostname)
        if not config:
            return
        
        if not config.is_configured:
            self._log_widget.warning(f"{hostname}: Please select an output folder first")
            # Select the sensor so user can configure it
            self._on_sensor_card_selected(hostname)
            return
        
        if self._scheduler.start_sensor(hostname, run_immediately=True):
            self._log_widget.success(f"Started automation for {hostname}")
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].refresh()
            self._update_global_buttons()

    @pyqtSlot(str)
    def _on_sensor_pause(self, hostname: str) -> None:
        """Handle pause button on sensor card."""
        self._scheduler.stop_sensor(hostname)
        self._log_widget.warning(f"Stopped automation for {hostname}")
        
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()
        self._update_global_buttons()

    @pyqtSlot()
    def _on_start_all_clicked(self) -> None:
        """Start all configured sensors."""
        count = self._scheduler.start_all(run_immediately=True)
        if count > 0:
            self._log_widget.success(f"Started automation for {count} sensor(s)")
            for card in self._sensor_cards.values():
                card.refresh()
        else:
            self._log_widget.warning("No configured sensors to start")
        self._update_global_buttons()

    @pyqtSlot()
    def _on_stop_all_clicked(self) -> None:
        """Stop all sensors."""
        self._scheduler.stop_all()
        self._log_widget.warning("Stopped all sensors")
        for card in self._sensor_cards.values():
            card.refresh()
        self._update_global_buttons()

    def _update_global_buttons(self) -> None:
        """Update Start All / Stop All button visibility."""
        any_running = any(c.is_running for c in self._sensors.values())
        self._start_all_btn.setVisible(not any_running)
        self._stop_all_btn.setVisible(any_running)

    @pyqtSlot(str)
    def _on_trigger_collection(self, hostname: str) -> None:
        """Handle scheduler trigger for a sensor."""
        config = self._sensors.get(hostname)
        if not config or not config.output_folder:
            return
        
        self._scheduler.notify_collection_started(hostname)
        self._status_label.setText(f"Collecting from {hostname}...")
        
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()
        
        # Start collection - now with hostname
        success = self._collector.start_collection(
            hostname=hostname,
            ip=config.ip,
            duration=config.duration,
            output_folder=config.output_folder,
            upload_to_aws=config.upload_to_aws,
            sample_rate=config.sample_rate.value,
        )
        
        if not success:
            self._log_widget.error(f"{hostname}: Collection already in progress")
            self._scheduler.notify_collection_complete(hostname)

    @pyqtSlot(str, int)
    def _on_countdown_tick(self, hostname: str, seconds: int) -> None:
        """Update countdown display for a sensor."""
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()

    @pyqtSlot(str, CollectionStatus, str)
    def _on_collection_status(self, hostname: str, status: CollectionStatus, message: str) -> None:
        """Handle collection status updates."""
        level_map = {
            CollectionStatus.CONNECTING: LogLevel.INFO,
            CollectionStatus.COLLECTING: LogLevel.STATUS,
            CollectionStatus.DOWNLOADING: LogLevel.INFO,
            CollectionStatus.UPLOADING: LogLevel.STATUS,
            CollectionStatus.COMPLETE: LogLevel.SUCCESS,
            CollectionStatus.ERROR: LogLevel.ERROR,
        }
        level = level_map.get(status, LogLevel.INFO)
        self._log_widget.log(message, level)
        self._status_label.setText(message)
        
        # Update sensor config status
        config = self._sensors.get(hostname)
        if config:
            status_map = {
                CollectionStatus.CONNECTING: SensorStatus.COLLECTING,
                CollectionStatus.COLLECTING: SensorStatus.COLLECTING,
                CollectionStatus.DOWNLOADING: SensorStatus.DOWNLOADING,
                CollectionStatus.UPLOADING: SensorStatus.UPLOADING,
                CollectionStatus.COMPLETE: SensorStatus.WAITING,
                CollectionStatus.ERROR: SensorStatus.ERROR,
            }
            config.status = status_map.get(status, SensorStatus.IDLE)
            
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].refresh()

    @pyqtSlot(str, int, int)
    def _on_collection_progress(self, hostname: str, downloaded: int, total: int) -> None:
        """Handle download progress updates."""
        if total > 0:
            percent = int((downloaded / total) * 100)
        else:
            percent = 50  # Indeterminate
        
        # Update the specific sensor's card progress
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].set_progress(percent)
        
        # Also update settings panel if this sensor is selected
        if hostname == self._selected_hostname:
            self._progress_bar.setValue(percent)

    @pyqtSlot(str, CollectionResult)
    def _on_collection_complete(self, hostname: str, result: CollectionResult) -> None:
        """Handle collection completion."""
        # Update the specific sensor's stats
        config = self._sensors.get(hostname)
        if config:
            config.progress = 0
            
            if result.success:
                config.stats.collections += 1
                if result.aws_status and "successful" in result.aws_status.lower():
                    config.stats.uploaded += 1
            else:
                config.stats.errors += 1
            
            # Notify scheduler
            self._scheduler.notify_collection_complete(hostname)
            
            # Update card
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].set_progress(0)
                self._sensor_cards[hostname].refresh()
            
            # Update settings panel if this sensor is selected
            if hostname == self._selected_hostname:
                self._progress_bar.setValue(0)
                self._update_stats_display(config)
        
        # Update status only if no other collections running
        any_collecting = any(
            c.status in (SensorStatus.COLLECTING, SensorStatus.DOWNLOADING, SensorStatus.UPLOADING)
            for c in self._sensors.values()
        )
        if not any_collecting:
            self._status_label.setText("Ready")

    def _update_uptime(self) -> None:
        """Update the uptime counter display."""
        elapsed = self._start_time.secsTo(QTime.currentTime())
        if elapsed < 0:
            elapsed += 86400  # Handle midnight rollover
        
        hours = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        self._uptime_label.setText(f"{hours:02d}:{mins:02d}:{secs:02d}")

    def closeEvent(self, event) -> None:
        """Handle window close."""
        self._uptime_timer.stop()
        self._scheduler.stop_all()
        self._discovery.stop()
        super().closeEvent(event)
