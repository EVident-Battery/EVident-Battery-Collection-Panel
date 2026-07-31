"""Main application window - Evident Battery Device Hub."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QComboBox, QLineEdit, QFileDialog,
    QFrame, QScrollArea, QSplitter, QProgressBar,
    QGroupBox, QGridLayout, QCheckBox, QSizePolicy,
    QRadioButton, QTimeEdit, QMessageBox, QTabWidget, QDialog, QDialogButtonBox,
    QButtonGroup, QInputDialog, QToolTip
)
from PyQt5.QtCore import (
    Qt, pyqtSlot, QTimer, QTime, QElapsedTimer, QSize, QEvent, QObject,
)
from PyQt5.QtGui import QFont, QPixmap, QColor
from PyQt5.QtSvg import QSvgWidget, QSvgRenderer

from models.sensor_config import (
    SensorConfig, SensorStatus, IntervalUnit, SampleRate, AccelRange,
    GyroRange, SensorModel, StartMode, StopMode, DiscoverySource,
)
from services.discovery import DiscoveryController
from services.collector import CollectorService, CollectionStatus, CollectionResult
from services.multi_scheduler import MultiSensorScheduler
from services.manual_resolver import ManualResolverWorker
from services.settings_store import SensorSettingsStore
from services.reachability import ReachabilityMonitor
from services.capabilities import CapabilityDetector
from ui.sensor_card import SensorCardWidget
from ui.log_widget import LogWidget, LogLevel
from ui.monitoring_tab import MonitoringTabWidget
from ui.analysis_tab import AnalysisTabWidget
from ui.streaming_tab import StreamingTabWidget


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

QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
    background-color: #1E293B;
    color: #E2E8F0;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 20px;
}

QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {
    border-color: #3B82F6;
}

QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled {
    background-color: #0F172A;
    color: #475569;
    border-color: #1E293B;
}

QComboBox::down-arrow:disabled {
    border-top-color: #334155;
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

QCheckBox:disabled, QRadioButton:disabled {
    color: #475569;
}

QCheckBox::indicator:disabled {
    border-color: #1E293B;
    background-color: #0F172A;
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

QHeaderView::section {
    background-color: #1E3A5F;
    color: #E2E8F0;
    border: 1px solid #334155;
    padding: 4px 8px;
}

QTabWidget::pane {
    border: 1px solid #334155;
    border-radius: 6px;
    background-color: #0F172A;
    top: -1px;
}

QTabWidget::tab-bar {
    alignment: left;
}

QTabBar::tab {
    background-color: #1E293B;
    color: #94A3B8;
    border: 1px solid #334155;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 20px;
    margin-right: 4px;
    font-weight: bold;
    font-size: 12px;
    min-width: 140px;
}

QTabBar::tab:selected {
    background-color: #0F172A;
    color: #E2E8F0;
    border-bottom: 2px solid #3B82F6;
}

QTabBar::tab:hover:!selected {
    background-color: #293548;
    color: #CBD5E1;
}
"""


class InstantItemTooltips(QObject):
    """Show a combo popup item's tooltip the moment the mouse is over it.

    Qt's normal tooltip path waits ~700 ms before showing, which makes a
    greyed-out item's explanation easy to miss entirely - the user has
    usually moved on before it appears. This tracks mouse movement over the
    popup list and shows/hides the tooltip with zero delay.
    """

    def __init__(self, combo: QComboBox) -> None:
        view = combo.view()
        super().__init__(view)
        self._view = view
        self._last_row = -1
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseMove:
            index = self._view.indexAt(event.pos())
            row = index.row() if index.isValid() else -1
            if row != self._last_row:
                self._last_row = row
                tip = index.data(Qt.ToolTipRole) if index.isValid() else None
                if tip:
                    QToolTip.showText(event.globalPos(), tip, self._view)
                else:
                    QToolTip.hideText()
        elif event.type() in (QEvent.Hide, QEvent.Leave):
            self._last_row = -1
            QToolTip.hideText()
        return False  # never consume; the popup behaves normally


class WelcomeDialog(QDialog):
    """Startup dialog explaining network setup for sensor discovery."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Notice")
        self.setFixedSize(480, 340)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
            }
            QLabel#title {
                color: #E2E8F0;
                font-size: 18px;
                font-weight: bold;
            }
            QLabel#body {
                color: #CBD5E1;
                font-size: 12px;
                line-height: 1.5;
            }
            QPushButton#okButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 32px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton#okButton:hover {
                background-color: #60A5FA;
            }
            QPushButton#okButton:pressed {
                background-color: #2563EB;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Before You Begin")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignLeft)
        layout.addWidget(title)

        body_html = (
            '<p style="color:#CBD5E1; font-size:12px;">'
            'For the software to communicate with a sensor, whether via auto-discovery or '
            'manual IP entry, your computer and the sensor must be on the same network:'
            '</p>'
            '<p style="color:#3B82F6; font-size:13px; font-weight:bold; margin-bottom:2px;">'
            'Wi-Fi Mode'
            '</p>'
            '<p style="color:#CBD5E1; font-size:12px; margin-top:0px;">'
            'Connect your computer and sensor to the same network.'
            '</p>'
            '<p style="color:#3B82F6; font-size:13px; font-weight:bold; margin-bottom:2px;">'
            'AP Mode'
            '</p>'
            '<p style="color:#CBD5E1; font-size:12px; margin-top:0px;">'
            "Connect your computer directly to the sensor's access point "
            '(e.g., EVBS_xxxxx).'
            '</p>'
            '<p style="color:#CBD5E1; font-size:12px;">'
            'Once connected, the sensor\'s IP will populate automatically.'
            '</p>'
        )
        body = QLabel(body_html)
        body.setObjectName("body")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        layout.addWidget(body)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("okButton")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setFixedWidth(100)
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)


class MainWindow(QMainWindow):
    """Main application window - Evident Battery Device Hub."""

    def __init__(self) -> None:
        super().__init__()

        # Sensor configs and cards
        self._sensors: Dict[str, SensorConfig] = {}
        self._sensor_cards: Dict[str, SensorCardWidget] = {}
        self._selected_hostname: Optional[str] = None

        # Manual sensors tracking (separate from auto-discovered)
        self._manual_sensors: Dict[str, SensorConfig] = {}

        # Manual resolver thread
        self._resolver_thread: Optional[ManualResolverWorker] = None

        # Services
        self._discovery = DiscoveryController()
        self._collector = CollectorService()
        self._scheduler = MultiSensorScheduler()
        self._settings_store = SensorSettingsStore()
        self._reachability = ReachabilityMonitor()
        self._capabilities = CapabilityDetector()

        # Uptime tracking
        # Monotonic clock: QTime is time-of-day only and wraps at 24h
        self._uptime_clock = QElapsedTimer()
        self._uptime_clock.start()
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._update_uptime)

        self._setup_ui()
        self._connect_signals()
        self._start_discovery()

        # Show welcome dialog on first launch
        WelcomeDialog(self).exec_()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Evident Battery Device Hub")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 850)
        self.setStyleSheet(APP_STYLESHEET)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 12)
        main_layout.setSpacing(12)

        # Header (shared, above tabs)
        header = self._create_header()
        main_layout.addWidget(header)

        # Tab widget
        self._tab_widget = QTabWidget()
        # macOS-specific: prevent the native tab bar from eliding/clipping
        # styled tab labels (e.g. "Data Collection" rendering as "ata Collectio").
        self._tab_widget.tabBar().setElideMode(Qt.ElideNone)
        self._tab_widget.tabBar().setUsesScrollButtons(False)
        self._tab_widget.tabBar().setExpanding(False)

        # ---- Tab 1: Data Collection (existing UI) ----
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setContentsMargins(0, 8, 0, 0)
        tab1_layout.setSpacing(12)

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
        tab1_layout.addWidget(splitter, 1)

        self._tab_widget.addTab(tab1, "Data Collection")

        # ---- Tab 2: Live Streaming (DEPRECATED) ----
        # The standalone Live Streaming tab is now redundant — its connection
        # and start/stop controls have been moved into the Data Analysis tab's
        # "Live Stream" source mode. The widget itself is still constructed
        # (hidden) so its StreamingWorker pipeline can drive the analysis tab.
        self._streaming_tab = StreamingTabWidget()
        self._streaming_tab.hide()
        # self._tab_widget.addTab(self._streaming_tab, "Live Streaming")

        # ---- Tab 3: Data Analysis (HIDDEN on standard branch) ----
        # The widget is still instantiated so existing wiring (update_sensors,
        # cleanup, streaming hookups) keeps working — it's just not added as a
        # visible tab in this build.
        self._analysis_tab = AnalysisTabWidget()
        self._tab_widget.addTab(self._analysis_tab, "Data Analysis")

        # ---- Tab 4: AI Monitoring ----
        self._monitoring_tab = MonitoringTabWidget()
        self._tab_widget.addTab(self._monitoring_tab, "AI Monitoring")

        # Wire live streaming data + control flow to/from the analysis tab
        self._streaming_tab.live_frame.connect(self._analysis_tab.feed_live_frame)
        self._streaming_tab.stream_active_changed.connect(self._analysis_tab.set_stream_active)
        self._streaming_tab.connection_state_changed.connect(self._analysis_tab.set_connection_state)
        self._analysis_tab.stream_start_requested.connect(self._streaming_tab._on_start)
        self._analysis_tab.stream_stop_requested.connect(self._streaming_tab._on_stop)
        self._analysis_tab.connect_requested.connect(self._streaming_tab.connect_to_ip)
        self._analysis_tab.disconnect_requested.connect(self._streaming_tab._on_disconnect)

        main_layout.addWidget(self._tab_widget, 1)

        # Start uptime timer
        self._uptime_timer.start()

        # Footer (shared, below tabs)
        footer = self._create_footer()
        main_layout.addWidget(footer)

    def _create_header(self) -> QWidget:
        """Create the header with title and global controls."""
        header = QFrame()
        header.setMinimumHeight(80)
        header.setStyleSheet("""
            QFrame {
                background-color: #CBD5E1;
                border-radius: 12px;
            }
        """)

        # Main Horizontal Layout for the Header
        main_layout = QHBoxLayout(header)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(0)  # We will use a stretch for the gap

        # ==========================================================
        # GROUP 1: LEFT SIDE (Logo + Title)
        # ==========================================================
        left_widget = QWidget()
        left_widget.setStyleSheet("background: transparent;")
        left_layout = QHBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(20)  # 20px gap between Logo and Title

        # Logo
        import os
        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media", "LogoEVident-Vector.svg")
        if os.path.exists(logo_path):
            logo = QSvgWidget(logo_path)
            # Calculate ratio logic here as before...
            renderer = QSvgRenderer(logo_path)
            native_size = renderer.defaultSize()
            if native_size.height() > 0:
                aspect_ratio = native_size.width() / native_size.height()
                target_height = 55
                target_width = int(target_height * aspect_ratio)
                logo.setFixedSize(target_width, target_height)
            left_layout.addWidget(logo)

        # Title
        title = QLabel("Evident Battery Device Hub")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setStyleSheet("color: #0F172A; border: none;")
        # CRITICAL: This tells the layout "I need this space, do not shrink me"
        title.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        left_layout.addWidget(title)

        # Add the left group to main layout
        main_layout.addWidget(left_widget)

        # ==========================================================
        # THE SPACER (The only thing allowed to shrink)
        # ==========================================================
        main_layout.addStretch(1)

        # ==========================================================
        # GROUP 2: RIGHT SIDE (Uptime + Buttons)
        # ==========================================================
        right_widget = QWidget()
        right_widget.setStyleSheet("background: transparent;")
        right_layout = QHBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)  # Gap between items in the right group

        # Uptime Label
        uptime_hint = QLabel("Uptime:")
        uptime_hint.setStyleSheet("color: #64748B; font-size: 13px; font-weight: bold;")
        # CRITICAL: Lock width to content
        uptime_hint.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        right_layout.addWidget(uptime_hint)

        # Timer Display
        self._uptime_label = QLabel("00:00:00")
        self._uptime_label.setFont(QFont("Consolas", 16, QFont.Bold))
        self._uptime_label.setStyleSheet("color: #334155;")
        # CRITICAL: Lock width to content
        self._uptime_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # Optional: Add a tiny margin to the text so it isn't cramped
        self._uptime_label.setContentsMargins(5, 0, 5, 0)
        right_layout.addWidget(self._uptime_label)

        # Reset Button
        self._refresh_btn = QPushButton("↻ Reset")
        self._refresh_btn.setMinimumWidth(90)
        self._refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #E2E8F0;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #475569; }
            QPushButton:pressed { background-color: #1E293B; }
        """)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        right_layout.addWidget(self._refresh_btn)

        # Start All Button
        self._start_all_btn = QPushButton("▶  Start All")
        self._start_all_btn.setObjectName("startAllButton")
        self._start_all_btn.setMinimumWidth(110)
        self._start_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #10B981; }
            QPushButton:pressed { background-color: #047857; }
        """)
        self._start_all_btn.clicked.connect(self._on_start_all_clicked)
        right_layout.addWidget(self._start_all_btn)

        # Stop All Button
        self._stop_all_btn = QPushButton("■  Stop All")
        self._stop_all_btn.setObjectName("stopAllButton")
        self._stop_all_btn.setMinimumWidth(110)
        self._stop_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #EF4444; }
            QPushButton:pressed { background-color: #B91C1C; }
        """)
        self._stop_all_btn.setVisible(False)
        self._stop_all_btn.clicked.connect(self._on_stop_all_clicked)
        right_layout.addWidget(self._stop_all_btn)

        # Add the right group to main layout
        main_layout.addWidget(right_widget)

        return header

    def _create_sensor_panel(self) -> QWidget:
        """Create the scrollable discovered sensors panel."""
        group = QGroupBox("Discovered Sensors")
        group.setMinimumWidth(280)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        # Warning banner (hidden by default)
        self._warning_banner = self._create_warning_banner()
        layout.addWidget(self._warning_banner)

        # Discovery mode toggle
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(16)

        self._auto_radio = QRadioButton("Automatic")
        self._auto_radio.setChecked(True)
        self._auto_radio.setStyleSheet("color: #CBD5E1; background: transparent;")
        self._auto_radio.toggled.connect(self._on_discovery_mode_changed)
        mode_layout.addWidget(self._auto_radio)

        self._manual_radio = QRadioButton("Manual")
        self._manual_radio.setStyleSheet("color: #CBD5E1; background: transparent;")
        mode_layout.addWidget(self._manual_radio)

        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Manual entry widget (hidden by default)
        self._manual_entry_widget = self._create_manual_entry_widget()
        self._manual_entry_widget.setVisible(False)
        layout.addWidget(self._manual_entry_widget)

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
        self._blink_btn = QPushButton("Blink Selected")
        self._blink_btn.setEnabled(False)
        self._blink_btn.clicked.connect(self._on_blink_clicked)
        btn_layout.addWidget(self._blink_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return group

    def _create_warning_banner(self) -> QWidget:
        """Create the warning banner for discovery timeout."""
        banner = QFrame()
        banner.setStyleSheet("""
            QFrame {
                background-color: #78350F;
                border: 1px solid #F59E0B;
                border-radius: 6px;
            }
        """)
        banner.setVisible(False)

        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(10, 8, 10, 8)
        banner_layout.setSpacing(8)

        # Warning icon and message
        icon = QLabel("Warning:")
        icon.setStyleSheet("color: #FCD34D; font-weight: bold;")
        banner_layout.addWidget(icon)

        message = QLabel(
            "No sensors discovered. Windows Firewall may be blocking mDNS discovery. "
            "Allow this app on private networks, or use Manual mode below."
        )
        message.setStyleSheet("color: #FEF3C7; font-size: 11px;")
        message.setWordWrap(True)
        banner_layout.addWidget(message, 1)

        # Dismiss button
        dismiss_btn = QPushButton("X")
        dismiss_btn.setFixedSize(20, 20)
        dismiss_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #FCD34D;
                border: none;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #FEF3C7;
            }
        """)
        dismiss_btn.clicked.connect(lambda: banner.setVisible(False))
        banner_layout.addWidget(dismiss_btn)

        return banner

    def _create_manual_entry_widget(self) -> QWidget:
        """Create the manual sensor entry widget."""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background-color: #1E3A5F;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)

        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Entry row
        entry_row = QHBoxLayout()
        entry_row.setSpacing(8)

        self._manual_entry = QLineEdit()
        self._manual_entry.setPlaceholderText("EVBS_1234 or 192.168.1.x")
        self._manual_entry.setStyleSheet("""
            QLineEdit {
                background-color: #0F172A;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QLineEdit:focus {
                border-color: #3B82F6;
            }
        """)
        self._manual_entry.returnPressed.connect(self._on_manual_add_clicked)
        entry_row.addWidget(self._manual_entry, 1)

        self._manual_add_btn = QPushButton("+")
        self._manual_add_btn.setFixedSize(32, 32)
        self._manual_add_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #10B981;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748B;
            }
        """)
        self._manual_add_btn.clicked.connect(self._on_manual_add_clicked)
        entry_row.addWidget(self._manual_add_btn)

        layout.addLayout(entry_row)

        # Helper text
        helper = QLabel("Enter sensor name or IP address")
        helper.setStyleSheet("color: #64748B; font-size: 10px;")
        layout.addWidget(helper)

        return widget

    def _create_settings_panel(self) -> QWidget:
        """Create the settings panel for selected sensor."""
        group = QGroupBox("Sensor Settings")
        group.setMinimumHeight(350)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(0, 8, 0, 0)
        group_layout.setSpacing(0)
        
        # Wrap content in scroll area to handle vertical compression
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        # Content widget inside scroll area
        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(12, 8, 12, 8)
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
        settings_grid.setColumnMinimumWidth(0, 100)
        settings_grid.setColumnMinimumWidth(1, 200)
        # Set minimum row heights to prevent vertical overlap
        for i in range(8):
            settings_grid.setRowMinimumHeight(i, 32)
        
        row = 0
        
        # Duration
        settings_grid.addWidget(QLabel("Duration:"), row, 0)
        duration_layout = QHBoxLayout()
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 200000)
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
        self._interval_hint = QLabel("(min 1s)")
        self._interval_hint.setStyleSheet("color: #64748B; font-size: 10px;")
        interval_layout.addWidget(self._interval_hint)
        
        interval_layout.addStretch()
        settings_grid.addLayout(interval_layout, row, 1)

        row += 1

        # Start Mode section (right after Interval)
        settings_grid.addWidget(QLabel("Start Mode:"), row, 0, Qt.AlignTop)
        start_mode_layout = QVBoxLayout()
        start_mode_layout.setSpacing(6)

        # Own button group so these don't join the Stop Mode radios'
        # exclusivity group (radios sharing a parent are exclusive by default)
        self._start_mode_group = QButtonGroup(self)

        # Option 1: Immediate
        self._start_immediate_radio = QRadioButton("Immediate")
        self._start_immediate_radio.setChecked(True)
        self._start_immediate_radio.toggled.connect(self._on_start_mode_changed)
        self._start_mode_group.addButton(self._start_immediate_radio)
        start_mode_layout.addWidget(self._start_immediate_radio)

        # Option 2: At specific time
        start_time_layout = QHBoxLayout()
        self._start_time_radio = QRadioButton("At")
        self._start_time_radio.toggled.connect(self._on_start_mode_changed)
        self._start_mode_group.addButton(self._start_time_radio)
        start_time_layout.addWidget(self._start_time_radio)

        self._start_time_edit = QTimeEdit()
        self._start_time_edit.setDisplayFormat("hh:mm AP")
        self._start_time_edit.setTime(QTime(8, 0))  # Default 8:00 AM
        self._start_time_edit.setStyleSheet("background-color: #1E3A5F; color: #64748B;")
        self._start_time_edit.timeChanged.connect(self._on_settings_changed)
        start_time_layout.addWidget(self._start_time_edit)
        start_time_layout.addStretch()
        start_mode_layout.addLayout(start_time_layout)

        settings_grid.addLayout(start_mode_layout, row, 1)

        # Initialize start mode controls state
        self._start_time_edit.setEnabled(False)

        row += 1

        # Stop Mode section
        settings_grid.addWidget(QLabel("Stop Mode:"), row, 0, Qt.AlignTop)
        stop_mode_layout = QVBoxLayout()
        stop_mode_layout.setSpacing(6)

        self._stop_mode_group = QButtonGroup(self)

        # Option 1: Continuous
        self._continuous_radio = QRadioButton("Continuous")
        self._continuous_radio.setChecked(True)
        self._continuous_radio.toggled.connect(self._on_stop_mode_changed)
        self._stop_mode_group.addButton(self._continuous_radio)
        stop_mode_layout.addWidget(self._continuous_radio)

        # Option 2: After N runs
        count_layout = QHBoxLayout()
        self._count_radio = QRadioButton("After")
        self._count_radio.toggled.connect(self._on_stop_mode_changed)
        self._stop_mode_group.addButton(self._count_radio)
        count_layout.addWidget(self._count_radio)

        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 9999)
        self._count_spin.setValue(1)
        self._count_spin.setMinimumWidth(70)
        self._count_spin.valueChanged.connect(self._on_settings_changed)
        count_layout.addWidget(self._count_spin)
        count_layout.addWidget(QLabel("runs"))
        count_layout.addStretch()
        stop_mode_layout.addLayout(count_layout)

        # Option 3: At specific time
        time_layout = QHBoxLayout()
        self._time_radio = QRadioButton("At")
        self._time_radio.toggled.connect(self._on_stop_mode_changed)
        self._stop_mode_group.addButton(self._time_radio)
        time_layout.addWidget(self._time_radio)

        self._stop_time_edit = QTimeEdit()
        self._stop_time_edit.setDisplayFormat("hh:mm AP")
        self._stop_time_edit.setTime(QTime(17, 0))  # Default 5:00 PM
        self._stop_time_edit.setStyleSheet("background-color: #1E3A5F; color: #64748B;")
        self._stop_time_edit.timeChanged.connect(self._on_settings_changed)
        time_layout.addWidget(self._stop_time_edit)
        time_layout.addStretch()
        stop_mode_layout.addLayout(time_layout)

        # Repeat daily (only meaningful with a stop time: the window re-arms
        # for the next start time instead of ending the schedule)
        repeat_layout = QHBoxLayout()
        repeat_layout.addSpacing(22)
        self._repeat_daily_check = QCheckBox("Repeat daily")
        self._repeat_daily_check.setToolTip(
            "When the stop time is reached, wait for the next start time and\n"
            "run again - e.g. collect 9:00 AM to 5:00 PM every day.\n"
            "With Start Mode set to Immediate, the moment you press Start\n"
            "becomes the daily start time."
        )
        self._repeat_daily_check.toggled.connect(self._on_stop_mode_changed)
        repeat_layout.addWidget(self._repeat_daily_check)
        repeat_layout.addStretch()
        stop_mode_layout.addLayout(repeat_layout)

        settings_grid.addLayout(stop_mode_layout, row, 1)

        # Initialize stop mode controls state
        self._count_spin.setEnabled(False)
        self._stop_time_edit.setEnabled(False)
        self._repeat_daily_check.setEnabled(False)

        row += 1

        # Sample Rate (ODR)
        settings_grid.addWidget(QLabel("Sample Rate:"), row, 0)
        odr_layout = QHBoxLayout()
        odr_layout.setSpacing(8)
        self._odr_combo = QComboBox()
        for rate in SampleRate.all_rates():
            self._odr_combo.addItem(rate.display_name, rate)
        self._odr_combo.setCurrentText("1666 Hz")
        self._odr_combo.setMinimumWidth(120)
        self._odr_combo.currentIndexChanged.connect(self._on_settings_changed)
        # Greyed-out rates explain themselves instantly on hover
        self._odr_tooltips = InstantItemTooltips(self._odr_combo)
        odr_layout.addWidget(self._odr_combo)
        odr_layout.addStretch()
        settings_grid.addLayout(odr_layout, row, 1)

        row += 1

        # Accel Range (separate row). The row lives in a widget container so
        # clicks on a capability-locked (disabled) control can be caught by
        # the eventFilter and explained in the log instead of dying silently
        settings_grid.addWidget(QLabel("Accel Range:"), row, 0)
        self._accel_row_widget = QWidget()
        accel_layout = QHBoxLayout(self._accel_row_widget)
        accel_layout.setContentsMargins(0, 0, 0, 0)
        accel_layout.setSpacing(8)
        self._accel_range_combo = QComboBox()
        for accel_range in AccelRange.all_ranges():
            self._accel_range_combo.addItem(accel_range.display_name, accel_range)
        self._accel_range_combo.setCurrentText("±16g")
        self._accel_range_combo.setMinimumWidth(100)
        self._accel_range_combo.currentIndexChanged.connect(self._on_settings_changed)
        accel_layout.addWidget(self._accel_range_combo)
        self._gravity_check = QCheckBox("Gravity comp")
        self._gravity_check.setToolTip(
            "On-sensor high-pass filter that removes the constant gravity\n"
            "offset - accel output is centered on zero. Also removes any\n"
            "real DC/low-frequency content, so leave it off when slow\n"
            "drift or orientation matters."
        )
        self._gravity_check.toggled.connect(self._on_settings_changed)
        accel_layout.addWidget(self._gravity_check)
        self._accel_lock_hint = QLabel("")
        self._accel_lock_hint.setStyleSheet(
            "color: #64748B; font-size: 11px; font-style: italic;"
        )
        self._accel_lock_hint.setVisible(False)
        accel_layout.addWidget(self._accel_lock_hint)
        accel_layout.addStretch()
        self._accel_row_widget.installEventFilter(self)
        settings_grid.addWidget(self._accel_row_widget, row, 1)

        row += 1

        # Gyroscope (EVB-01 only; shares the ODR above with the accel)
        settings_grid.addWidget(QLabel("Gyroscope:"), row, 0)
        self._gyro_row_widget = QWidget()
        gyro_layout = QHBoxLayout(self._gyro_row_widget)
        gyro_layout.setContentsMargins(0, 0, 0, 0)
        gyro_layout.setSpacing(8)
        self._gyro_check = QCheckBox("Enable")
        self._gyro_check.setToolTip(
            "Record gyroscope data alongside the accelerometer.\n"
            "Both share the sample rate above. At 6666 Hz the sensor\n"
            "can only record one channel, so enabling the gyro caps\n"
            "the sample rate at 3333 Hz."
        )
        self._gyro_check.toggled.connect(self._on_gyro_toggled)
        gyro_layout.addWidget(self._gyro_check)
        self._gyro_range_combo = QComboBox()
        for gyro_range in GyroRange.all_ranges():
            self._gyro_range_combo.addItem(gyro_range.display_name, gyro_range)
        self._gyro_range_combo.setCurrentText("±500 dps")
        self._gyro_range_combo.setMinimumWidth(110)
        self._gyro_range_combo.setEnabled(False)
        self._gyro_range_combo.currentIndexChanged.connect(self._on_settings_changed)
        gyro_layout.addWidget(self._gyro_range_combo)
        self._gyro_lock_hint = QLabel("")
        self._gyro_lock_hint.setStyleSheet(
            "color: #64748B; font-size: 11px; font-style: italic;"
        )
        self._gyro_lock_hint.setVisible(False)
        gyro_layout.addWidget(self._gyro_lock_hint)
        gyro_layout.addStretch()
        self._gyro_row_widget.installEventFilter(self)
        settings_grid.addWidget(self._gyro_row_widget, row, 1)

        row += 1

        # Output folder
        settings_grid.addWidget(QLabel("Save Location:"), row, 0)
        folder_layout = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Select a folder...")
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setMinimumWidth(200)
        folder_layout.addWidget(self._folder_edit, 1)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        folder_layout.addWidget(self._browse_btn)
        settings_grid.addLayout(folder_layout, row, 1)

        row += 1

        # AWS upload
        self._aws_checkbox = QCheckBox("Upload to AWS after each collection")
        self._aws_checkbox.setChecked(False)
        self._aws_checkbox.stateChanged.connect(self._on_settings_changed)
        self._aws_checkbox.clicked.connect(self._on_aws_checkbox_clicked)
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
        
        # Add content widget to scroll area, scroll area to group
        scroll.setWidget(content_widget)
        group_layout.addWidget(scroll)
        
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
        
        from version import get_version
        version = QLabel(get_version())
        version.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(version)
        
        return footer

    def _set_settings_enabled(self, enabled: bool) -> None:
        """Enable/disable settings controls."""
        self._duration_spin.setEnabled(enabled)
        self._interval_spin.setEnabled(enabled)
        self._interval_unit_combo.setEnabled(enabled)
        self._odr_combo.setEnabled(enabled)
        self._accel_range_combo.setEnabled(enabled)
        self._gravity_check.setEnabled(enabled)
        self._gyro_check.setEnabled(enabled)
        self._gyro_range_combo.setEnabled(enabled and self._gyro_check.isChecked())
        self._browse_btn.setEnabled(enabled)
        self._aws_checkbox.setEnabled(enabled)
        self._apply_all_btn.setEnabled(enabled)
        # Stop mode controls
        self._continuous_radio.setEnabled(enabled)
        self._count_radio.setEnabled(enabled)
        self._time_radio.setEnabled(enabled)
        if enabled:
            # Update enabled state based on radio selection (no config save)
            self._update_stop_mode_controls_state()
            # Re-apply per-model gating (Lite locks range and hides gyro)
            config = self._sensors.get(self._selected_hostname)
            if config:
                self._apply_capability_gating(config)
        else:
            self._count_spin.setEnabled(False)
            self._stop_time_edit.setEnabled(False)

    def _connect_signals(self) -> None:
        """Connect all service signals."""
        # Discovery
        self._discovery.signals.device_found.connect(self._on_device_found)
        self._discovery.signals.device_lost.connect(self._on_device_lost)
        self._discovery.signals.discovery_timeout.connect(self._on_discovery_timeout)

        # Collector
        self._collector.status_changed.connect(self._on_collection_status)
        self._collector.progress_updated.connect(self._on_collection_progress)
        self._collector.collection_complete.connect(self._on_collection_complete)

        # Multi-scheduler
        self._scheduler.trigger_collection.connect(self._on_trigger_collection)
        self._scheduler.countdown_tick.connect(self._on_countdown_tick)
        self._scheduler.window_rearmed.connect(self._on_window_rearmed)

        # Reachability probing (for sensors that are mDNS-lost AND failing)
        self._reachability.sensor_reachable.connect(self._on_sensor_reachable)

        # Hardware model detection (gates gyro/ODR/range options per sensor)
        self._capabilities.model_detected.connect(self._on_model_detected)

    def _start_discovery(self) -> None:
        """Start sensor discovery."""
        self._log_widget.info("Starting sensor discovery...")
        self._discovery.start()

    @pyqtSlot(str, str)
    def _on_device_found(self, hostname: str, ip: str) -> None:
        """Handle discovered sensor."""
        if hostname in self._sensors:
            # Known sensor re-announced: refresh its presence (and IP)
            config = self._sensors[hostname]
            was_unreachable = config.status == SensorStatus.UNREACHABLE
            if config.ip != ip:
                self._log_widget.info(
                    f"{config.display_name} reappeared at new IP {ip} (was {config.ip})"
                )
                config.ip = ip
            config.mdns_lost = False
            config.consecutive_failures = 0
            self._reachability.stop_probing(hostname)
            # Re-check the hardware model (cheap, self-healing)
            self._capabilities.probe(hostname, ip)
            if was_unreachable and config.is_running:
                self._scheduler.resume_sensor(hostname, run_immediately=True)
                self._log_widget.success(
                    f"{config.display_name} re-announced via mDNS - resuming automation"
                )
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].refresh()
            return

        # Notify discovery controller to cancel timeout
        self._discovery.notify_device_found()

        # Hide warning banner when device found
        self._warning_banner.setVisible(False)

        # Fetch battery
        battery = -1
        try:
            from services.sensor_client import SensorClient
            client = SensorClient(ip)
            status = client.get_status()
            battery = status.get("Battery SOC", -1)
        except Exception:
            pass

        # Create config, restoring any settings saved from a previous session
        config = SensorConfig(hostname=hostname, ip=ip, battery=battery)
        self._settings_store.apply(config)
        # Restored settings must respect the restored model's hardware
        for note in config.clamp_to_capabilities():
            self._log_widget.warning(f"{hostname}: restored setting adjusted - {note}")
        self._sensors[hostname] = config
        self._scheduler.register_sensor(config)

        # Identify the hardware model in the background (gyro / ODR gating)
        self._capabilities.probe(hostname, ip)

        # Create card
        card = SensorCardWidget(config)
        card.selected.connect(self._on_sensor_card_selected)
        card.play_clicked.connect(self._on_sensor_play)
        card.pause_clicked.connect(self._on_sensor_pause)
        card.rename_clicked.connect(self._on_sensor_rename)

        self._sensor_cards[hostname] = card

        # Insert before stretch
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

        if battery >= 0:
            self._log_widget.success(f"Discovered: {hostname} ({ip}) - Battery: {battery:.0f}%")
        else:
            self._log_widget.success(f"Discovered: {hostname} ({ip})")

        # Auto-resume: the sensor was running when it dropped off the
        # network (or the app closed) and was never explicitly stopped.
        # If its previous collection is somehow still in flight (e.g.
        # Reset pressed mid-download), adopt it instead of triggering a
        # duplicate.
        if config.should_be_running and config.is_configured:
            adopt = self._collector.is_busy(hostname)
            if self._scheduler.start_sensor(
                hostname,
                run_immediately=True,
                ignore_start_mode=True,
                adopt_in_flight=adopt,
            ):
                if adopt:
                    self._adopt_in_flight(hostname, config)
                    self._log_widget.success(
                        f"Auto-resumed automation for {config.display_name}"
                        " - adopting the collection already in progress"
                    )
                else:
                    self._log_widget.success(
                        f"Auto-resumed automation for {config.display_name}"
                    )
                card.refresh()
                self._update_global_buttons()

        # Update monitoring tab sensor list
        self._monitoring_tab.update_sensors(self._sensors)
        self._streaming_tab.update_sensors(self._sensors)
        self._analysis_tab.update_sensors(self._sensors)

    @pyqtSlot(str)
    def _on_device_lost(self, hostname: str) -> None:
        """
        Handle an expired mDNS record.

        mDNS expiry is a weak signal (multicast loss routinely expires
        records for perfectly reachable sensors), so the sensor stays in
        the roster on probation: its schedule keeps running and each
        collection attempt doubles as the reachability check. Only mDNS
        loss PLUS consecutive collection failures suspends it (see
        _on_collection_complete).
        """
        config = self._sensors.get(hostname)
        if not config:
            return

        config.mdns_lost = True
        if config.is_running:
            self._log_widget.warning(
                f"mDNS lost for {config.display_name}"
                " - keeping it in the roster; collections continue as the reachability check"
            )
        else:
            self._log_widget.warning(
                f"mDNS lost for {config.display_name} (idle) - keeping it in the roster"
            )
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()

    def _remove_sensor(self, hostname: str) -> None:
        """Fully remove a sensor from the roster (used by Reset)."""
        if hostname not in self._sensors:
            return

        self._reachability.stop_probing(hostname)
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

        self._update_global_buttons()

        # Update monitoring tab sensor list
        self._monitoring_tab.update_sensors(self._sensors)
        self._streaming_tab.update_sensors(self._sensors)
        self._analysis_tab.update_sensors(self._sensors)

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
            self._update_selected_label(config)
            self._load_config_to_ui(config)

    def _load_config_to_ui(self, config: SensorConfig) -> None:
        """Load sensor config into UI controls."""
        # Block signals to avoid triggering saves
        self._duration_spin.blockSignals(True)
        self._interval_spin.blockSignals(True)
        self._interval_unit_combo.blockSignals(True)
        self._odr_combo.blockSignals(True)
        self._accel_range_combo.blockSignals(True)
        self._gravity_check.blockSignals(True)
        self._gyro_check.blockSignals(True)
        self._gyro_range_combo.blockSignals(True)
        self._aws_checkbox.blockSignals(True)
        self._start_immediate_radio.blockSignals(True)
        self._start_time_radio.blockSignals(True)
        self._start_time_edit.blockSignals(True)
        self._continuous_radio.blockSignals(True)
        self._count_radio.blockSignals(True)
        self._time_radio.blockSignals(True)
        self._count_spin.blockSignals(True)
        self._stop_time_edit.blockSignals(True)
        self._repeat_daily_check.blockSignals(True)

        self._duration_spin.setValue(config.duration)
        self._interval_spin.setValue(config.interval_value)
        self._interval_unit_combo.setCurrentText(config.interval_unit.value)
        self._refresh_odr_choices(config)
        self._accel_range_combo.setCurrentText(config.accel_range.display_name)
        self._gravity_check.setChecked(config.gravity_comp)
        self._gyro_check.setChecked(config.gyro_enabled)
        self._gyro_range_combo.setCurrentText(config.gyro_range.display_name)
        self._aws_checkbox.setChecked(config.upload_to_aws)

        # Load start mode
        if config.start_mode == StartMode.IMMEDIATE:
            self._start_immediate_radio.setChecked(True)
        elif config.start_mode == StartMode.AT_TIME:
            self._start_time_radio.setChecked(True)

        if config.start_at_time:
            self._start_time_edit.setTime(config.start_at_time)

        # Load stop mode
        if config.stop_mode == StopMode.CONTINUOUS:
            self._continuous_radio.setChecked(True)
        elif config.stop_mode == StopMode.AFTER_COUNT:
            self._count_radio.setChecked(True)
        elif config.stop_mode == StopMode.AT_TIME:
            self._time_radio.setChecked(True)

        self._count_spin.setValue(config.repetition_count)
        if config.stop_at_time:
            self._stop_time_edit.setTime(config.stop_at_time)
        self._repeat_daily_check.setChecked(config.repeat_daily)

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
        self._accel_range_combo.blockSignals(False)
        self._gravity_check.blockSignals(False)
        self._gyro_check.blockSignals(False)
        self._gyro_range_combo.blockSignals(False)
        self._aws_checkbox.blockSignals(False)
        self._start_immediate_radio.blockSignals(False)
        self._start_time_radio.blockSignals(False)
        self._start_time_edit.blockSignals(False)
        self._continuous_radio.blockSignals(False)
        self._count_radio.blockSignals(False)
        self._time_radio.blockSignals(False)
        self._count_spin.blockSignals(False)
        self._stop_time_edit.blockSignals(False)
        self._repeat_daily_check.blockSignals(False)

        # Update start/stop mode control states (no config save)
        self._update_start_mode_controls_state()
        self._update_stop_mode_controls_state()

        # Gate options by the detected hardware model
        self._apply_capability_gating(config)
        self._update_selected_label(config)

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

    def _refresh_odr_choices(self, config: SensorConfig) -> None:
        """Rebuild the ODR list from the sensor's model + gyro selection.

        Every rate stays visible; ones this sensor can't use right now are
        greyed out with a tooltip saying why, instead of silently missing.

        Caller must have already clamped config.sample_rate to an allowed
        value (clamp_to_capabilities), so the current selection is always
        selectable in the rebuilt list.
        """
        allowed = config.allowed_sample_rates()
        self._odr_combo.blockSignals(True)
        self._odr_combo.clear()
        item_model = self._odr_combo.model()
        for rate in SampleRate.all_rates():
            self._odr_combo.addItem(rate.display_name, rate)
            if rate not in allowed:
                item = item_model.item(self._odr_combo.count() - 1)
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                # The app-wide stylesheet pins one text color on everything,
                # which hides Qt's normal disabled-item dimming - dim the
                # item explicitly so it visibly reads as unavailable
                item.setForeground(QColor("#475569"))
                if rate.value > config.model.max_sample_rate_hz:
                    item.setToolTip(
                        f"Not supported on EVB-Lite (max "
                        f"{int(config.model.max_sample_rate_hz)} Hz)"
                    )
                else:
                    item.setToolTip(
                        "At 6666 Hz the sensor can record only one channel -\n"
                        "disable the gyroscope to use this rate"
                    )
        self._odr_combo.setCurrentText(config.sample_rate.display_name)
        self._odr_combo.blockSignals(False)

    def _apply_capability_gating(self, config: SensorConfig) -> None:
        """Enable/disable controls the detected model can't honor.

        A locked control is dimmed AND explained: an inline hint says why,
        and clicking the dead row logs the reason (see eventFilter).
        """
        gyro_ok = config.model.has_gyro
        self._gyro_check.setEnabled(gyro_ok)
        self._gyro_range_combo.setEnabled(gyro_ok and self._gyro_check.isChecked())
        self._gyro_lock_hint.setText("not available on EVB-Lite")
        self._gyro_lock_hint.setVisible(not gyro_ok)
        if not gyro_ok:
            self._gyro_check.setToolTip("EVB-Lite has no gyroscope")
            self._gyro_range_combo.setToolTip("EVB-Lite has no gyroscope")
        else:
            self._gyro_check.setToolTip(
                "Record gyroscope data alongside the accelerometer.\n"
                "Both share the sample rate above. At 6666 Hz the sensor\n"
                "can only record one channel, so enabling the gyro caps\n"
                "the sample rate at 3333 Hz."
            )
            self._gyro_range_combo.setToolTip("")

        locked = config.model.locked_accel_range
        self._accel_range_combo.setEnabled(locked is None)
        self._accel_range_combo.setToolTip(
            f"EVB-Lite is fixed at {locked.display_name}" if locked else ""
        )
        if locked:
            self._accel_lock_hint.setText(f"fixed at {locked.display_name} on EVB-Lite")
        self._accel_lock_hint.setVisible(locked is not None)

    def _update_selected_label(self, config: SensorConfig) -> None:
        """Show the selection with its detected hardware model."""
        text = f"Selected: {config.display_name}"
        if config.model is not SensorModel.UNKNOWN:
            text += f"   ({config.model.display_name})"
        self._selected_label.setText(text)

    def eventFilter(self, obj, event):
        """Explain clicks on capability-locked rows instead of silence."""
        if event.type() == QEvent.MouseButtonPress:
            if obj is self._gyro_row_widget and not self._gyro_check.isEnabled():
                self._explain_locked_control(
                    "has no gyroscope, so gyro recording can't be enabled"
                )
            elif (
                obj is self._accel_row_widget
                and not self._accel_range_combo.isEnabled()
            ):
                self._explain_locked_control(
                    "has a fixed ±16g accel range - it can't be changed"
                )
        return super().eventFilter(obj, event)

    def _explain_locked_control(self, reason: str) -> None:
        """Log why the clicked control is locked for the selected sensor."""
        if not self._selected_hostname:
            return  # row is only dead because no sensor is selected
        config = self._sensors.get(self._selected_hostname)
        if not config or config.model is not SensorModel.EVB_LITE:
            return
        self._log_widget.info(f"{config.display_name} is an EVB-Lite - it {reason}")

    @pyqtSlot(bool)
    def _on_gyro_toggled(self, checked: bool) -> None:
        """Gyro checkbox changed: update config, re-gate the ODR list."""
        self._gyro_range_combo.setEnabled(checked and self._gyro_check.isEnabled())

        if not self._selected_hostname:
            return
        config = self._sensors.get(self._selected_hostname)
        if not config:
            return

        config.gyro_enabled = checked
        # Enabling gyro at 6666 Hz bumps the rate down (accel XOR gyro there)
        for note in config.clamp_to_capabilities():
            self._log_widget.warning(f"{config.display_name}: {note}")
        self._refresh_odr_choices(config)
        self._on_settings_changed()

    @pyqtSlot(str, object)
    def _on_model_detected(self, hostname: str, model: SensorModel) -> None:
        """Background /settings probe identified a sensor's hardware model."""
        config = self._sensors.get(hostname)
        if not config or config.model is model:
            return

        config.model = model
        self._log_widget.info(f"{config.display_name} identified as {model.display_name}")
        for note in config.clamp_to_capabilities():
            self._log_widget.warning(f"{config.display_name}: setting adjusted - {note}")
        self._settings_store.save(config)

        if self._selected_hostname == hostname:
            self._load_config_to_ui(config)
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()

    def _update_start_mode_controls_state(self) -> None:
        """Update enabled/disabled state and styling of start mode sub-controls without saving."""
        time_enabled = self._start_time_radio.isChecked()
        self._start_time_edit.setEnabled(time_enabled)

        time_dim_style = "background-color: #1E3A5F; color: #64748B;"
        time_normal_style = "background-color: #1E3A5F; color: #E2E8F0;"
        self._start_time_edit.setStyleSheet(time_dim_style if not time_enabled else time_normal_style)

    @pyqtSlot()
    def _on_start_mode_changed(self) -> None:
        """Update enabled state of start mode controls and save to config."""
        self._update_start_mode_controls_state()
        self._on_settings_changed()

    def _update_stop_mode_controls_state(self) -> None:
        """Update enabled/disabled state and styling of stop mode sub-controls without saving."""
        count_enabled = self._count_radio.isChecked()
        time_enabled = self._time_radio.isChecked()

        # Dim/enable the inputs based on which radio is selected
        self._count_spin.setEnabled(count_enabled)
        self._stop_time_edit.setEnabled(time_enabled)
        self._repeat_daily_check.setEnabled(time_enabled)

        # Style dimmed controls
        dim_style = "color: #64748B;"
        normal_style = ""
        # Time edit styles with light blue background
        time_dim_style = "background-color: #1E3A5F; color: #64748B;"
        time_normal_style = "background-color: #1E3A5F; color: #E2E8F0;"

        self._count_spin.setStyleSheet(dim_style if not count_enabled else normal_style)
        self._stop_time_edit.setStyleSheet(time_dim_style if not time_enabled else time_normal_style)

    @pyqtSlot()
    def _on_stop_mode_changed(self) -> None:
        """Update enabled state of stop mode controls and save to config."""
        self._update_stop_mode_controls_state()
        self._on_settings_changed()

    def _on_aws_checkbox_clicked(self, checked: bool) -> None:
        """Show a storage warning when the user checks the AWS upload box."""
        if checked:
            QMessageBox.information(
                self,
                "AWS Upload",
                "Please verify that your account has sufficient storage "
                "capacity to accommodate the data from this job before "
                "proceeding.",
            )

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
        config.accel_range = self._accel_range_combo.currentData()
        config.gravity_comp = self._gravity_check.isChecked()
        config.gyro_enabled = self._gyro_check.isChecked()
        config.gyro_range = self._gyro_range_combo.currentData()
        config.upload_to_aws = self._aws_checkbox.isChecked()

        # Save start mode
        if self._start_immediate_radio.isChecked():
            config.start_mode = StartMode.IMMEDIATE
        elif self._start_time_radio.isChecked():
            config.start_mode = StartMode.AT_TIME

        config.start_at_time = self._start_time_edit.time()

        # Save stop mode
        if self._continuous_radio.isChecked():
            config.stop_mode = StopMode.CONTINUOUS
        elif self._count_radio.isChecked():
            config.stop_mode = StopMode.AFTER_COUNT
        elif self._time_radio.isChecked():
            config.stop_mode = StopMode.AT_TIME

        config.repetition_count = self._count_spin.value()
        config.stop_at_time = self._stop_time_edit.time()
        config.repeat_daily = self._repeat_daily_check.isChecked()

        self._settings_store.save(config)

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
            config.accel_range = source_config.accel_range
            config.gravity_comp = source_config.gravity_comp
            config.gyro_enabled = source_config.gyro_enabled
            config.gyro_range = source_config.gyro_range
            config.output_folder = source_config.output_folder
            config.upload_to_aws = source_config.upload_to_aws
            # Copy start mode settings
            config.start_mode = source_config.start_mode
            config.start_at_time = source_config.start_at_time
            # Copy stop mode settings
            config.stop_mode = source_config.stop_mode
            config.repetition_count = source_config.repetition_count
            config.stop_at_time = source_config.stop_at_time
            config.repeat_daily = source_config.repeat_daily
            # Note: label is deliberately NOT copied - it identifies the
            # sensor's physical location and is unique per sensor

            # A copied config may exceed this sensor's hardware (e.g. an
            # EVB-Lite receiving gyro-on at 3333 Hz) - clamp per target
            for note in config.clamp_to_capabilities():
                self._log_widget.warning(f"{config.display_name}: adjusted - {note}")

            self._settings_store.save(config)

            # Update card
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].refresh()

            count += 1

        if count > 0:
            self._log_widget.success(f"Applied settings to {count} other sensor(s)")

    @pyqtSlot()
    def _on_browse_clicked(self) -> None:
        """Open folder selection dialog."""
        current = self._folder_edit.text()
        start_dir = current if current and Path(current).is_dir() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", start_dir,
            QFileDialog.DontUseNativeDialog
        )
        if folder and self._selected_hostname:
            config = self._sensors.get(self._selected_hostname)
            if config:
                config.output_folder = Path(folder)
                self._folder_edit.setText(folder)
                self._settings_store.save(config)
                self._log_widget.info(f"Output folder set for {self._selected_hostname}: {folder}")
                
                # Update card
                if self._selected_hostname in self._sensor_cards:
                    self._sensor_cards[self._selected_hostname].refresh()

    @pyqtSlot()
    def _on_refresh_clicked(self) -> None:
        """Refresh sensor discovery."""
        # Clear all sensors (including manual)
        for hostname in list(self._sensors.keys()):
            self._remove_sensor(hostname)

        # Clear manual sensors tracking
        self._manual_sensors.clear()

        # Hide warning banner on refresh
        self._warning_banner.setVisible(False)

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

    @pyqtSlot()
    def _on_discovery_timeout(self) -> None:
        """Handle discovery timeout - show warning banner."""
        # Only show if no sensors have been discovered
        if not self._sensors:
            self._warning_banner.setVisible(True)
            self._log_widget.warning(
                "No sensors discovered after 15 seconds. Check firewall settings or use Manual mode."
            )

    @pyqtSlot(bool)
    def _on_discovery_mode_changed(self, checked: bool) -> None:
        """Handle discovery mode toggle."""
        # Only act on the automatic radio (to avoid double-firing)
        is_manual = self._manual_radio.isChecked()
        self._manual_entry_widget.setVisible(is_manual)

        if is_manual:
            self._log_widget.info("Switched to Manual mode - enter sensor IP or hostname")
        else:
            self._log_widget.info("Switched to Automatic mode - mDNS discovery active")

    @pyqtSlot()
    def _on_manual_add_clicked(self) -> None:
        """Handle manual sensor add button click."""
        entry = self._manual_entry.text().strip()
        if not entry:
            return

        # Disable button while resolving
        self._manual_add_btn.setEnabled(False)
        self._manual_entry.setEnabled(False)

        # Start resolver thread
        self._resolver_thread = ManualResolverWorker(entry)
        self._resolver_thread.resolved.connect(self._on_manual_resolved)
        self._resolver_thread.failed.connect(self._on_manual_failed)
        self._resolver_thread.finished.connect(self._on_resolver_finished)
        self._resolver_thread.start()

    @pyqtSlot(str, str)
    def _on_manual_resolved(self, hostname: str, ip: str) -> None:
        """Handle successful manual resolution."""
        # Check if already exists
        if hostname in self._sensors:
            self._log_widget.warning(f"Sensor {hostname} already in list")
            return

        # Hide warning banner
        self._warning_banner.setVisible(False)

        # Fetch battery
        battery = -1
        try:
            from services.sensor_client import SensorClient
            client = SensorClient(ip)
            status = client.get_status()
            battery = status.get("Battery SOC", -1)
        except Exception:
            pass

        # Create config with MANUAL source
        config = SensorConfig(
            hostname=hostname,
            ip=ip,
            battery=battery,
            discovery_source=DiscoverySource.MANUAL
        )
        self._settings_store.apply(config)
        # Restored settings must respect the restored model's hardware
        for note in config.clamp_to_capabilities():
            self._log_widget.warning(f"{hostname}: restored setting adjusted - {note}")
        self._sensors[hostname] = config
        self._manual_sensors[hostname] = config
        self._scheduler.register_sensor(config)

        # Identify the hardware model in the background (gyro / ODR gating)
        self._capabilities.probe(hostname, ip)

        # Create card
        card = SensorCardWidget(config)
        card.selected.connect(self._on_sensor_card_selected)
        card.play_clicked.connect(self._on_sensor_play)
        card.pause_clicked.connect(self._on_sensor_pause)
        card.rename_clicked.connect(self._on_sensor_rename)

        self._sensor_cards[hostname] = card

        # Insert before stretch
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

        # Clear entry field
        self._manual_entry.clear()

        if battery >= 0:
            self._log_widget.success(f"Added manually: {hostname} ({ip}) - Battery: {battery:.0f}%")
        else:
            self._log_widget.success(f"Added manually: {hostname} ({ip})")

        # Update monitoring tab sensor list
        self._monitoring_tab.update_sensors(self._sensors)
        self._streaming_tab.update_sensors(self._sensors)
        self._analysis_tab.update_sensors(self._sensors)

    @pyqtSlot(str)
    def _on_manual_failed(self, error: str) -> None:
        """Handle manual resolution failure."""
        self._log_widget.error(error)

    @pyqtSlot()
    def _on_resolver_finished(self) -> None:
        """Handle resolver thread completion."""
        self._manual_add_btn.setEnabled(True)
        self._manual_entry.setEnabled(True)
        self._manual_entry.setFocus()
        self._resolver_thread = None

    def _check_memory_warning(self, configs: list) -> bool:
        """Show warning if any config exceeds 16MB. Returns True to proceed."""
        exceeding = [c for c in configs if c.exceeds_memory_limit()]
        if not exceeding:
            return True

        sensor_list = "\n".join([
            f"  - {c.hostname}: {c.format_memory_size()} "
            f"({c.sample_rate.display_name} x {c.duration}s"
            f"{' + gyro' if c.gyro_enabled else ''})"
            for c in exceeding
        ])
        reply = QMessageBox.warning(
            self, "Memory Warning",
            f"These sensors may exceed 16MB device memory:\n\n{sensor_list}\n\nProceed anyway?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        return reply == QMessageBox.Yes

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

        # Check memory warning
        if not self._check_memory_warning([config]):
            return

        if self._begin_automation(config):
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].refresh()
            self._update_global_buttons()

    def _begin_automation(self, config: SensorConfig) -> bool:
        """
        Start (or restart) a sensor's automation.

        If the previous session's collection is still finishing, adopt it
        as this session's active cycle instead of triggering a duplicate -
        the schedule continues when it completes.
        """
        hostname = config.hostname
        self._capture_immediate_start(config)

        # Would this start defer to a future time rather than run now?
        would_defer = (
            config.start_mode == StartMode.AT_TIME
            and config.start_at_time is not None
            and not (config.has_daily_window and config.is_within_window())
        )
        adopt = self._collector.is_busy(hostname) and not would_defer

        if not self._scheduler.start_sensor(hostname, adopt_in_flight=adopt):
            return False
        if adopt:
            self._adopt_in_flight(hostname, config)

        config.should_be_running = True
        config.consecutive_failures = 0
        self._settings_store.save(config)

        if adopt:
            self._log_widget.success(
                f"Started automation for {hostname}"
                " - current collection still finishing, schedule continues after it"
            )
        elif config.has_daily_window:
            window = (
                f"{config.start_at_time.toString('h:mm AP')}-"
                f"{config.stop_at_time.toString('h:mm AP')} daily"
            )
            if config.is_within_window():
                self._log_widget.success(f"Started automation for {hostname} ({window})")
            else:
                self._log_widget.success(f"Scheduled {hostname} ({window}) - waiting for window")
        elif config.start_mode == StartMode.AT_TIME and config.start_at_time:
            self._log_widget.success(
                f"Scheduled {hostname} to start at {config.start_at_time.toString('h:mm AP')}"
            )
        else:
            self._log_widget.success(f"Started automation for {hostname}")
        return True

    @pyqtSlot(str)
    def _on_sensor_reachable(self, hostname: str) -> None:
        """A backoff probe reached a suspended sensor - resume its schedule."""
        config = self._sensors.get(hostname)
        if not config:
            return

        config.consecutive_failures = 0
        if config.is_running and config.status == SensorStatus.UNREACHABLE:
            self._scheduler.resume_sensor(hostname, run_immediately=True)
            self._log_widget.success(
                f"{config.display_name} is reachable again (mDNS still silent)"
                " - resuming automation"
            )
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()

    @pyqtSlot(str)
    def _on_sensor_rename(self, hostname: str) -> None:
        """Handle rename (pencil) click on a sensor card."""
        config = self._sensors.get(hostname)
        if not config:
            return

        label, ok = QInputDialog.getText(
            self,
            "Rename Sensor",
            f"Label for {hostname} (leave empty to clear):",
            text=config.label,
        )
        if not ok:
            return

        config.label = label.strip()
        self._settings_store.save(config)

        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()
        if hostname == self._selected_hostname:
            self._selected_label.setText(f"Selected: {config.display_name}")

        if config.label:
            self._log_widget.info(f"Renamed {hostname} to \"{config.label}\"")
        else:
            self._log_widget.info(f"Cleared label for {hostname}")

    def _adopt_in_flight(self, hostname: str, config: SensorConfig) -> None:
        """
        Mark a still-running collection as the current session's active
        cycle and show its actual phase, not a blanket "Collecting" - it
        may already be downloading or uploading.
        """
        self._scheduler.notify_collection_started(hostname)
        phase_map = {
            CollectionStatus.CONNECTING: SensorStatus.COLLECTING,
            CollectionStatus.COLLECTING: SensorStatus.COLLECTING,
            CollectionStatus.DOWNLOADING: SensorStatus.DOWNLOADING,
            CollectionStatus.UPLOADING: SensorStatus.UPLOADING,
            CollectionStatus.AWS_ERROR: SensorStatus.UPLOADING,
        }
        phase = phase_map.get(self._collector.last_status(hostname))
        if phase is not None:
            config.status = phase
        # Restore the recording countdown for a mid-recording adoption
        # (a fresh config after Reset starts at 00:00 otherwise)
        if phase == SensorStatus.COLLECTING:
            config.countdown_seconds = self._collector.recording_seconds_left(hostname)

    def _capture_immediate_start(self, config: SensorConfig) -> None:
        """
        Repeat daily + Immediate start: the press-Start moment becomes the
        daily start time, so the window has a defined start to return to
        tomorrow. Made visible by flipping the Start Mode UI to "At".
        """
        if not (
            config.repeat_daily
            and config.stop_mode == StopMode.AT_TIME
            and config.start_mode == StartMode.IMMEDIATE
        ):
            return

        config.start_mode = StartMode.AT_TIME
        config.start_at_time = QTime.currentTime()
        self._settings_store.save(config)
        self._log_widget.info(
            f"{config.display_name}: repeat daily - captured "
            f"{config.start_at_time.toString('h:mm AP')} as the daily start time"
        )
        if config.hostname == self._selected_hostname:
            self._load_config_to_ui(config)

    @pyqtSlot(str, int)
    def _on_window_rearmed(self, hostname: str, seconds: int) -> None:
        """A sensor's daily window ended; it re-armed for the next start."""
        config = self._sensors.get(hostname)
        if not config:
            return
        hours, mins = divmod(seconds // 60, 60)
        self._log_widget.info(
            f"{config.display_name}: daily window ended - next start at "
            f"{config.start_at_time.toString('h:mm AP')} (in {hours}h {mins:02d}m)"
        )
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()

    @pyqtSlot(str)
    def _on_sensor_pause(self, hostname: str) -> None:
        """Handle pause button on sensor card."""
        config = self._sensors.get(hostname)
        in_flight = self._collector.is_busy(hostname)
        remaining = config.countdown_seconds if config else 0

        self._scheduler.stop_sensor(hostname)
        self._reachability.stop_probing(hostname)
        if config:
            config.should_be_running = False
            config.consecutive_failures = 0
            self._settings_store.save(config)
        if config and in_flight:
            # Stop only cancels future cycles - the in-flight collection
            # finishes and saves. Make that visible instead of going idle,
            # and keep the recording countdown ticking (stop_sensor zeroes it).
            config.status = SensorStatus.STOPPING
            config.countdown_seconds = remaining
            self._scheduler.ensure_ticking()
            self._log_widget.warning(
                f"Stopped automation for {hostname}"
                " - letting the current collection finish"
            )
        else:
            self._log_widget.warning(f"Stopped automation for {hostname}")
        
        if hostname in self._sensor_cards:
            self._sensor_cards[hostname].refresh()
        self._update_global_buttons()

    @pyqtSlot()
    def _on_start_all_clicked(self) -> None:
        """Start all configured sensors."""
        # Get all configured sensors that aren't already running
        configs_to_start = [
            c for c in self._sensors.values()
            if c.is_configured and not c.is_running
        ]

        if not configs_to_start:
            self._log_widget.warning("No configured sensors to start")
            return

        # Check memory warning for all sensors being started
        if not self._check_memory_warning(configs_to_start):
            return

        count = sum(1 for config in configs_to_start if self._begin_automation(config))
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
        in_flight = {
            hostname: (self._collector.is_busy(hostname), config.countdown_seconds)
            for hostname, config in self._sensors.items()
        }
        self._scheduler.stop_all()
        finishing = 0
        for hostname, config in self._sensors.items():
            self._reachability.stop_probing(hostname)
            config.consecutive_failures = 0
            if config.should_be_running:
                config.should_be_running = False
                self._settings_store.save(config)
            busy, remaining = in_flight[hostname]
            if busy:
                config.status = SensorStatus.STOPPING
                config.countdown_seconds = remaining
                finishing += 1
        if finishing:
            self._scheduler.ensure_ticking()
            self._log_widget.warning(
                f"Stopped all sensors - {finishing} still finishing their current collection"
            )
        else:
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
            accel_range=config.accel_range.value,
            gyro_enabled=config.gyro_enabled,
            gyro_range=config.gyro_range.value,
            gravity_comp=config.gravity_comp,
        )
        
        if not success:
            self._log_widget.warning(
                f"{hostname}: previous collection still finishing - will retry next cycle"
            )
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
            CollectionStatus.AWS_ERROR: LogLevel.ERROR,
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
                CollectionStatus.AWS_ERROR: SensorStatus.UPLOADING,
            }
            config.status = status_map.get(status, SensorStatus.IDLE)

            # While recording, the countdown shows time left in the recording;
            # once the download/upload phase starts, snap any leftover to zero
            if status == CollectionStatus.COLLECTING:
                config.countdown_seconds = config.duration
            elif status in (CollectionStatus.DOWNLOADING, CollectionStatus.UPLOADING):
                config.countdown_seconds = 0

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
                elif result.aws_status and result.aws_status.lower().startswith("failed"):
                    config.stats.errors += 1
            else:
                config.stats.errors += 1
            
            # Notify scheduler
            self._scheduler.notify_collection_complete(hostname)

            # If the stop mode just ended the schedule (after N runs /
            # at time), that's a legitimate stop - clear the resume intent
            if not config.is_running and config.should_be_running:
                config.should_be_running = False
                self._settings_store.save(config)
                self._update_global_buttons()

            # Reachability probation: mDNS loss alone never suspends a
            # sensor, but mDNS loss corroborated by consecutive collection
            # failures does - then hand it to the backoff prober.
            if result.success:
                config.consecutive_failures = 0
            else:
                config.consecutive_failures += 1
                if (
                    config.mdns_lost
                    and config.is_running
                    and config.consecutive_failures >= 3
                    and not self._reachability.is_probing(hostname)
                ):
                    config.status = SensorStatus.UNREACHABLE
                    self._reachability.start_probing(hostname, config.ip)
                    self._log_widget.warning(
                        f"{config.display_name} is unreachable"
                        f" ({config.consecutive_failures} failed attempts after mDNS loss)"
                        " - suspending schedule, probing with backoff up to 5 min"
                    )

            # Update card
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].set_progress(0)
                self._sensor_cards[hostname].refresh()
            
            # Update settings panel if this sensor is selected
            if hostname == self._selected_hostname:
                self._progress_bar.setValue(0)
                self._update_stats_display(config)
        
        # A stopped sensor's in-flight collection just finished: leave the
        # transient STOPPING/worker status and settle at idle, visibly
        if config and not config.is_running and config.status != SensorStatus.IDLE:
            config.status = SensorStatus.IDLE
            if result.success:
                self._log_widget.info(
                    f"{config.display_name}: in-flight collection saved - now idle"
                )
            if hostname in self._sensor_cards:
                self._sensor_cards[hostname].refresh()

        # Update status only if no other collections running
        any_collecting = any(
            c.status in (SensorStatus.COLLECTING, SensorStatus.DOWNLOADING, SensorStatus.UPLOADING)
            for c in self._sensors.values()
        )
        if not any_collecting:
            self._status_label.setText("Ready")

    def _update_uptime(self) -> None:
        """Update the uptime counter display."""
        elapsed = self._uptime_clock.elapsed() // 1000
        days, rem = divmod(elapsed, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)

        if days > 0:
            self._uptime_label.setText(f"{days}d {hours:02d}:{mins:02d}:{secs:02d}")
        else:
            self._uptime_label.setText(f"{hours:02d}:{mins:02d}:{secs:02d}")

    def closeEvent(self, event) -> None:
        """Handle window close."""
        self._uptime_timer.stop()
        self._scheduler.stop_all()
        self._reachability.shutdown()
        self._capabilities.shutdown()
        self._collector.shutdown()
        self._monitoring_tab.stop_pipeline()
        self._streaming_tab.cleanup()
        self._analysis_tab.cleanup()
        self._discovery.stop()
        super().closeEvent(event)
