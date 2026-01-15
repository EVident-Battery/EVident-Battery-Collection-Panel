"""Sensor card widget for the discovered sensors panel."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QProgressBar
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

from models.sensor_config import SensorConfig, SensorStatus


class SensorCardWidget(QFrame):
    """
    A card widget representing a single discovered sensor.
    
    Displays:
    - Hostname and battery percentage
    - IP address
    - Countdown timer
    - Play/Pause controls
    
    Signals:
        selected: Emitted when card is clicked
        play_clicked: Emitted when play button is clicked
        pause_clicked: Emitted when pause button is clicked
    """
    
    selected = pyqtSignal(str)  # hostname
    play_clicked = pyqtSignal(str)  # hostname
    pause_clicked = pyqtSignal(str)  # hostname
    
    def __init__(self, config: SensorConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config
        self._is_selected = False
        self._setup_ui()
        
    def _setup_ui(self) -> None:
        self.setObjectName("sensorCard")
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        
        # Top row: Hostname + Battery
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        
        self._hostname_label = QLabel(self.config.hostname)
        self._hostname_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._hostname_label.setStyleSheet("color: #F1F5F9;")
        top_row.addWidget(self._hostname_label)
        
        top_row.addStretch()
        
        self._battery_label = QLabel()
        self._battery_label.setFont(QFont("Segoe UI", 10))
        self._update_battery_display()
        top_row.addWidget(self._battery_label)
        
        layout.addLayout(top_row)
        
        # IP address
        self._ip_label = QLabel(self.config.ip)
        self._ip_label.setStyleSheet("color: #64748B; font-size: 10px;")
        layout.addWidget(self._ip_label)
        
        # Bottom row: Countdown + Controls
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        
        # Countdown display
        self._countdown_label = QLabel("⏱ --:--")
        self._countdown_label.setFont(QFont("Consolas", 11))
        self._countdown_label.setStyleSheet("color: #94A3B8;")
        bottom_row.addWidget(self._countdown_label)
        
        # Status indicator
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #64748B; font-size: 10px;")
        bottom_row.addWidget(self._status_label)
        
        bottom_row.addStretch()
        
        # Play button
        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(28, 28)
        self._play_btn.setToolTip("Start collection")
        self._play_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #10B981;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748B;
            }
        """)
        self._play_btn.clicked.connect(self._on_play)
        bottom_row.addWidget(self._play_btn)
        
        # Pause button
        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setFixedSize(28, 28)
        self._pause_btn.setToolTip("Stop collection")
        self._pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #EF4444;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748B;
            }
        """)
        self._pause_btn.clicked.connect(self._on_pause)
        self._pause_btn.setVisible(False)
        bottom_row.addWidget(self._pause_btn)
        
        layout.addLayout(bottom_row)
        
        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #334155;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 2px;
            }
        """)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)
        
        self._update_display()
    
    def _update_style(self) -> None:
        """Update card style based on selection state."""
        if self._is_selected:
            self.setStyleSheet("""
                QFrame#sensorCard {
                    background-color: #1E3A5F;
                    border: 2px solid #3B82F6;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#sensorCard {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 8px;
                }
                QFrame#sensorCard:hover {
                    background-color: #293548;
                    border-color: #475569;
                }
            """)
    
    def _update_battery_display(self) -> None:
        """Update battery label with icon and color."""
        battery = self.config.battery
        if battery < 0:
            self._battery_label.setText("🔋 --")
            self._battery_label.setStyleSheet("color: #64748B;")
        else:
            if battery >= 50:
                color = "#22C55E"
                icon = "🔋"
            elif battery >= 20:
                color = "#FBBF24"
                icon = "🪫"
            else:
                color = "#EF4444"
                icon = "🪫"
            self._battery_label.setText(f"{icon} {battery:.0f}%")
            self._battery_label.setStyleSheet(f"color: {color};")
    
    def _update_display(self) -> None:
        """Update all display elements from config."""
        self._update_battery_display()
        
        # Countdown
        if self.config.is_running:
            self._countdown_label.setText(f"⏱ {self.config.format_countdown()}")
            self._countdown_label.setStyleSheet("color: #3B82F6;")
        else:
            self._countdown_label.setText("⏱ --:--")
            self._countdown_label.setStyleSheet("color: #94A3B8;")
        
        # Status
        status = self.config.status
        status_colors = {
            SensorStatus.IDLE: "#64748B",
            SensorStatus.WAITING: "#3B82F6",
            SensorStatus.COLLECTING: "#A78BFA",
            SensorStatus.DOWNLOADING: "#22C55E",
            SensorStatus.UPLOADING: "#F59E0B",
            SensorStatus.ERROR: "#EF4444",
        }
        color = status_colors.get(status, "#64748B")
        
        if status != SensorStatus.IDLE:
            self._status_label.setText(self.config.status_text)
            self._status_label.setStyleSheet(f"color: {color}; font-size: 10px;")
        else:
            self._status_label.setText("")
        
        # Button states
        is_running = self.config.is_running
        is_configured = self.config.is_configured
        
        self._play_btn.setVisible(not is_running)
        self._play_btn.setEnabled(is_configured)
        self._pause_btn.setVisible(is_running)
        
        # Progress bar - show during active operations
        is_active = status in (SensorStatus.COLLECTING, SensorStatus.DOWNLOADING, SensorStatus.UPLOADING)
        self._progress_bar.setVisible(is_active)
        self._progress_bar.setValue(self.config.progress)
    
    def set_selected(self, selected: bool) -> None:
        """Set selection state."""
        if self._is_selected != selected:
            self._is_selected = selected
            self._update_style()
    
    def update_config(self, config: SensorConfig) -> None:
        """Update the config and refresh display."""
        self.config = config
        self._update_display()
    
    def refresh(self) -> None:
        """Refresh display from current config."""
        self._update_display()
    
    def set_progress(self, value: int) -> None:
        """Set progress bar value (0-100)."""
        self.config.progress = value
        self._progress_bar.setValue(value)
        if value > 0 and not self._progress_bar.isVisible():
            self._progress_bar.setVisible(True)
    
    def mousePressEvent(self, event) -> None:
        """Handle mouse click to select card."""
        self.selected.emit(self.config.hostname)
        super().mousePressEvent(event)
    
    def _on_play(self) -> None:
        """Handle play button click."""
        self.play_clicked.emit(self.config.hostname)
    
    def _on_pause(self) -> None:
        """Handle pause button click."""
        self.pause_clicked.emit(self.config.hostname)

