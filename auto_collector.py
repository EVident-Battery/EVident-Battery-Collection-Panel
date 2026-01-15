#!/usr/bin/env python3
"""
Sensor Auto Collector - Automated periodic data collection with AWS upload.

A beautiful PyQt5 application that:
- Discovers sensors on the network via mDNS
- Collects data at configurable intervals
- Downloads CSV files to a user-selected folder
- Uploads data to AWS S3 via the sensor's built-in endpoint
- Provides comprehensive logging and status tracking
"""
from __future__ import annotations

import os
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QCoreApplication
from PyQt5.QtGui import QGuiApplication, QFont

from ui.main_window import MainWindow


def configure_high_dpi() -> None:
    """Enable high-DPI scaling for crisp rendering on modern displays."""
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    
    try:
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass
    
    try:
        # Available on Qt >= 5.14
        policy = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
        if policy is not None:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy.PassThrough)
    except Exception:
        pass


def main() -> int:
    """Application entry point."""
    configure_high_dpi()
    
    app = QApplication(sys.argv)
    app.setApplicationName("Sensor Auto Collector")
    app.setOrganizationName("SensorQA")
    
    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())

