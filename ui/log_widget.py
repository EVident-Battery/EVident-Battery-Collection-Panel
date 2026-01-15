"""Custom log console widget with colored, timestamped entries."""
from __future__ import annotations

from datetime import datetime
from enum import Enum, auto
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton,
    QLabel, QFrame
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QColor, QTextCursor, QFont, QTextCharFormat


class LogLevel(Enum):
    """Log message severity levels."""
    DEBUG = auto()
    INFO = auto()
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()
    STATUS = auto()  # Special status updates


class LogWidget(QWidget):
    """
    A rich text log console with colored, timestamped messages.
    
    Features:
    - Color-coded log levels
    - Auto-scroll with pause on user interaction
    - Clear and export functionality
    - Monospace font for readability
    """
    
    # Color scheme - vibrant but readable on dark background
    COLORS = {
        LogLevel.DEBUG: "#6B7280",     # Gray
        LogLevel.INFO: "#93C5FD",      # Light blue
        LogLevel.SUCCESS: "#4ADE80",   # Green
        LogLevel.WARNING: "#FBBF24",   # Amber
        LogLevel.ERROR: "#F87171",     # Red
        LogLevel.STATUS: "#A78BFA",    # Purple
    }
    
    LEVEL_LABELS = {
        LogLevel.DEBUG: "DEBUG",
        LogLevel.INFO: "INFO",
        LogLevel.SUCCESS: "SUCCESS",
        LogLevel.WARNING: "WARN",
        LogLevel.ERROR: "ERROR",
        LogLevel.STATUS: "STATUS",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._auto_scroll = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header bar
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border-bottom: 1px solid #334155;
                padding: 4px 8px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        
        title = QLabel("Log Console")
        title.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 11px;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Clear button
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #CBD5E1;
                border: none;
                border-radius: 4px;
                padding: 2px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            QPushButton:pressed {
                background-color: #1E293B;
            }
        """)
        self._clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(self._clear_btn)
        
        layout.addWidget(header)
        
        # Log text area
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Consolas", 10))
        self._text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #0F172A;
                color: #E2E8F0;
                border: none;
                padding: 8px;
                selection-background-color: #334155;
            }
            QScrollBar:vertical {
                background-color: #1E293B;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 4px;
                min-height: 30px;
                margin: 2px;
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
        """)
        
        # Pause auto-scroll when user scrolls up
        scrollbar = self._text_edit.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll)
        
        layout.addWidget(self._text_edit)

    def _on_scroll(self, value: int) -> None:
        """Handle scroll events - pause auto-scroll if user scrolls up."""
        scrollbar = self._text_edit.verticalScrollBar()
        at_bottom = value >= scrollbar.maximum() - 10
        self._auto_scroll = at_bottom

    @pyqtSlot()
    def clear(self) -> None:
        """Clear all log entries."""
        self._text_edit.clear()
        self._auto_scroll = True

    def log(
        self,
        message: str,
        level: LogLevel = LogLevel.INFO,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Add a log entry.
        
        Args:
            message: The log message
            level: Severity level
            timestamp: Optional timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        time_str = timestamp.strftime("%H:%M:%S")
        level_str = self.LEVEL_LABELS[level]
        color = self.COLORS[level]
        
        # Build formatted HTML line
        html = (
            f'<span style="color: #64748B;">[{time_str}]</span> '
            f'<span style="color: {color}; font-weight: bold;">[{level_str}]</span> '
            f'<span style="color: #E2E8F0;">{self._escape_html(message)}</span><br>'
        )
        
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html)
        
        if self._auto_scroll:
            self._text_edit.moveCursor(QTextCursor.End)
            self._text_edit.ensureCursorVisible()

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

    # Convenience methods
    def debug(self, message: str) -> None:
        self.log(message, LogLevel.DEBUG)

    def info(self, message: str) -> None:
        self.log(message, LogLevel.INFO)

    def success(self, message: str) -> None:
        self.log(message, LogLevel.SUCCESS)

    def warning(self, message: str) -> None:
        self.log(message, LogLevel.WARNING)

    def error(self, message: str) -> None:
        self.log(message, LogLevel.ERROR)

    def status(self, message: str) -> None:
        self.log(message, LogLevel.STATUS)

