"""Data Analysis tab UI widget."""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QFileDialog,
    QGroupBox, QGridLayout, QCheckBox, QListWidget,
    QListWidgetItem, QSplitter, QSpinBox, QDoubleSpinBox,
    QRadioButton, QButtonGroup, QStackedWidget,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot

# Trigger analysis plugin registration on import
import lib.analyses  # noqa: F401

from lib.analysis_registry import AnalysisRegistry, AnalysisResult, UnitConverter
from services.analysis_worker import AnalysisWorker
from ui.log_widget import LogWidget, LogLevel
from ui.plot_widget import PlotWidget


_INNER_GROUP_STYLE = """
    QGroupBox { border: none; background: transparent; margin-top: 12px; padding-top: 8px; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; color: #94A3B8; }
"""


_LIVE_FS = 50.0  # WebSocket IMU stream rate (Hz)
_LIVE_CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]


class AnalysisTabWidget(QWidget):
    """Self-contained Data Analysis tab."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # State
        self._fs: float = 0.0
        self._signals: Dict[str, np.ndarray] = {}
        self._column_names: List[str] = []
        self._last_result: Optional[AnalysisResult] = None
        self._param_widgets: Dict[str, tuple] = {}  # key -> (AnalysisParameter, widget)
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)
        self._debounce_timer.timeout.connect(self._run_analysis)

        # Live streaming state
        self._live_mode = False
        self._live_stream_active = False
        self._live_bufs: Dict[str, deque] = {}
        self._live_dirty = False
        self._live_refresh_timer = QTimer()
        self._live_refresh_timer.setInterval(500)
        self._live_refresh_timer.timeout.connect(self._on_live_refresh)

        # Worker
        self._worker = AnalysisWorker()

        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 4)
        layout.setSpacing(8)

        # ---- Controls strip ----
        controls = QHBoxLayout()
        controls.setSpacing(12)

        controls.addWidget(self._create_source_group())
        controls.addWidget(self._create_analysis_group())
        controls.addWidget(self._create_channels_group())
        controls.addWidget(self._create_units_group())
        controls.addWidget(self._create_signal_processing_group())
        self._params_group = self._create_params_group()
        controls.addWidget(self._params_group)

        layout.addLayout(controls)

        # Now that all groups exist, populate the category combo
        self._populate_categories()

        # ---- Plot + Log splitter ----
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        self._plot_widget = PlotWidget()
        splitter.addWidget(self._plot_widget)

        self._log_widget = LogWidget()
        splitter.addWidget(self._log_widget)

        splitter.setSizes([500, 120])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    def _create_source_group(self) -> QGroupBox:
        grp = QGroupBox("Source")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QGridLayout(grp)
        lay.setContentsMargins(8, 12, 8, 4)

        # Radio toggle: File vs Live Stream
        self._src_file_radio = QRadioButton("File")
        self._src_live_radio = QRadioButton("Live Stream")
        self._src_file_radio.setChecked(True)
        src_btn_group = QButtonGroup(self)
        src_btn_group.addButton(self._src_file_radio)
        src_btn_group.addButton(self._src_live_radio)
        lay.addWidget(self._src_file_radio, 0, 0)
        lay.addWidget(self._src_live_radio, 0, 1)

        # Stacked widget for source-specific controls
        self._source_stack = QStackedWidget()

        # Page 0: File controls
        file_page = QWidget()
        fp_lay = QHBoxLayout(file_page)
        fp_lay.setContentsMargins(0, 0, 0, 0)
        self._file_edit = QLineEdit()
        self._file_edit.setReadOnly(True)
        self._file_edit.setPlaceholderText("No file selected")
        self._file_edit.setMinimumWidth(160)
        fp_lay.addWidget(self._file_edit)
        self._browse_btn = QPushButton("Browse\u2026")
        self._browse_btn.setMinimumWidth(80)
        fp_lay.addWidget(self._browse_btn)
        self._source_stack.addWidget(file_page)

        # Page 1: Live stream controls
        live_page = QWidget()
        lp_lay = QHBoxLayout(live_page)
        lp_lay.setContentsMargins(0, 0, 0, 0)
        lp_lay.addWidget(QLabel("Buffer:"))
        self._buf_size_spin = QSpinBox()
        self._buf_size_spin.setRange(16, 10000)
        self._buf_size_spin.setValue(256)
        self._buf_size_spin.setSingleStep(16)
        self._buf_size_spin.setMinimumWidth(70)
        lp_lay.addWidget(self._buf_size_spin)
        self._buf_unit_combo = QComboBox()
        self._buf_unit_combo.addItems(["samples", "seconds"])
        self._buf_unit_combo.setCurrentIndex(0)
        lp_lay.addWidget(self._buf_unit_combo)
        self._live_status_label = QLabel("Not streaming")
        self._live_status_label.setStyleSheet("color: #94A3B8;")
        lp_lay.addWidget(self._live_status_label)
        self._source_stack.addWidget(live_page)

        lay.addWidget(self._source_stack, 1, 0, 1, 2)
        return grp

    # ------------------------------------------------------------------
    def _create_analysis_group(self) -> QGroupBox:
        grp = QGroupBox("Analysis")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QGridLayout(grp)
        lay.setContentsMargins(8, 12, 8, 4)

        lay.addWidget(QLabel("Category:"), 0, 0)
        self._category_combo = QComboBox()
        self._category_combo.setMinimumWidth(140)
        lay.addWidget(self._category_combo, 0, 1)

        lay.addWidget(QLabel("Type:"), 1, 0)
        self._type_combo = QComboBox()
        self._type_combo.setMinimumWidth(140)
        lay.addWidget(self._type_combo, 1, 1)

        self._save_signal_btn = QPushButton("Save as Signal")
        self._save_signal_btn.setToolTip(
            "Add the current result back as a new channel for further analysis")
        self._save_signal_btn.setEnabled(False)
        lay.addWidget(self._save_signal_btn, 2, 0, 1, 2)

        # _populate_categories() is called after all groups are created
        return grp

    # ------------------------------------------------------------------
    def _create_channels_group(self) -> QGroupBox:
        grp = QGroupBox("Channels")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(8, 12, 8, 4)

        self._channel_list = QListWidget()
        self._channel_list.setMaximumHeight(80)
        self._channel_list.setMinimumWidth(150)
        lay.addWidget(self._channel_list)

        return grp

    # ------------------------------------------------------------------
    def _create_units_group(self) -> QGroupBox:
        grp = QGroupBox("Units && Scale")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QGridLayout(grp)
        lay.setContentsMargins(8, 12, 8, 4)

        lay.addWidget(QLabel("X Unit:"), 0, 0)
        self._x_unit_combo = QComboBox()
        self._x_unit_combo.setMinimumWidth(90)
        lay.addWidget(self._x_unit_combo, 0, 1)

        lay.addWidget(QLabel("Y Unit:"), 1, 0)
        self._y_unit_combo = QComboBox()
        self._y_unit_combo.setMinimumWidth(90)
        lay.addWidget(self._y_unit_combo, 1, 1)

        self._log_x_cb = QCheckBox("Log X")
        lay.addWidget(self._log_x_cb, 0, 2)

        self._log_y_cb = QCheckBox("Log Y")
        lay.addWidget(self._log_y_cb, 1, 2)

        self._log_z_cb = QCheckBox("Log Z")
        self._log_z_cb.setToolTip("Logarithmic colour scale")
        self._log_z_cb.hide()
        lay.addWidget(self._log_z_cb, 2, 2)

        return grp

    # ------------------------------------------------------------------
    def _create_signal_processing_group(self) -> QGroupBox:
        grp = QGroupBox("Signal Processing")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QGridLayout(grp)
        lay.setContentsMargins(8, 12, 8, 4)

        # --- Filter ---
        lay.addWidget(QLabel("Filter:"), 0, 0)
        self._filter_combo = QComboBox()
        self._filter_combo.addItems([
            "None", "High Pass", "Low Pass", "Band Pass", "Band Stop",
        ])
        self._filter_combo.setMinimumWidth(100)
        lay.addWidget(self._filter_combo, 0, 1)

        self._filter_freq_label = QLabel("Freq (Hz):")
        lay.addWidget(self._filter_freq_label, 1, 0)
        self._filter_freq_spin = QDoubleSpinBox()
        self._filter_freq_spin.setRange(0.1, 50000.0)
        self._filter_freq_spin.setSingleStep(1.0)
        self._filter_freq_spin.setDecimals(1)
        self._filter_freq_spin.setValue(10.0)
        lay.addWidget(self._filter_freq_spin, 1, 1)

        self._filter_freq2_label = QLabel("Freq 2 (Hz):")
        lay.addWidget(self._filter_freq2_label, 2, 0)
        self._filter_freq2_spin = QDoubleSpinBox()
        self._filter_freq2_spin.setRange(0.1, 50000.0)
        self._filter_freq2_spin.setSingleStep(1.0)
        self._filter_freq2_spin.setDecimals(1)
        self._filter_freq2_spin.setValue(1000.0)
        lay.addWidget(self._filter_freq2_spin, 2, 1)

        self._filter_order_label = QLabel("Order:")
        lay.addWidget(self._filter_order_label, 3, 0)
        self._filter_order_spin = QSpinBox()
        self._filter_order_spin.setRange(1, 10)
        self._filter_order_spin.setValue(4)
        lay.addWidget(self._filter_order_spin, 3, 1)

        # --- Transform ---
        lay.addWidget(QLabel("Transform:"), 4, 0)
        self._transform_combo = QComboBox()
        self._transform_combo.addItems(["None", "Hilbert Envelope"])
        self._transform_combo.setMinimumWidth(100)
        lay.addWidget(self._transform_combo, 4, 1)

        self._smooth_label = QLabel("Smooth (pts):")
        lay.addWidget(self._smooth_label, 5, 0)
        self._smooth_spin = QSpinBox()
        self._smooth_spin.setRange(1, 5001)
        self._smooth_spin.setSingleStep(10)
        self._smooth_spin.setValue(51)
        self._smooth_spin.setToolTip(
            "Moving-average window for smoothing the envelope (1 = none)")
        lay.addWidget(self._smooth_spin, 5, 1)

        # Initial visibility — hide sub-parameters
        self._filter_freq_label.hide()
        self._filter_freq_spin.hide()
        self._filter_freq2_label.hide()
        self._filter_freq2_spin.hide()
        self._filter_order_label.hide()
        self._filter_order_spin.hide()
        self._smooth_label.hide()
        self._smooth_spin.hide()

        return grp

    # ------------------------------------------------------------------
    def _create_params_group(self) -> QGroupBox:
        grp = QGroupBox("Parameters")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        self._params_layout = QGridLayout(grp)
        self._params_layout.setContentsMargins(8, 12, 8, 4)
        grp.hide()
        return grp

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self._src_file_radio.toggled.connect(self._on_source_toggled)
        self._browse_btn.clicked.connect(self._on_browse)
        self._buf_size_spin.valueChanged.connect(self._on_buffer_config_changed)
        self._buf_unit_combo.currentIndexChanged.connect(self._on_buffer_config_changed)
        self._save_signal_btn.clicked.connect(self._on_save_signal)
        self._category_combo.currentTextChanged.connect(self._on_category_changed)
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._channel_list.itemChanged.connect(self._schedule_analysis)
        self._x_unit_combo.currentTextChanged.connect(self._on_display_changed)
        self._y_unit_combo.currentTextChanged.connect(self._on_display_changed)
        self._log_x_cb.stateChanged.connect(self._on_display_changed)
        self._log_y_cb.stateChanged.connect(self._on_display_changed)
        self._log_z_cb.stateChanged.connect(self._on_display_changed)

        # Signal processing group
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self._filter_combo.currentTextChanged.connect(self._schedule_analysis)
        self._filter_freq_spin.valueChanged.connect(self._schedule_analysis)
        self._filter_freq2_spin.valueChanged.connect(self._schedule_analysis)
        self._filter_order_spin.valueChanged.connect(self._schedule_analysis)
        self._transform_combo.currentTextChanged.connect(self._on_transform_changed)
        self._transform_combo.currentTextChanged.connect(self._schedule_analysis)
        self._smooth_spin.valueChanged.connect(self._schedule_analysis)

        # Worker signals
        self._worker.load_complete.connect(self._on_load_complete)
        self._worker.load_failed.connect(self._on_load_failed)
        self._worker.analysis_complete.connect(self._on_analysis_complete)
        self._worker.analysis_failed.connect(self._on_analysis_failed)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _populate_categories(self) -> None:
        cats = AnalysisRegistry.get_categories()
        self._category_combo.blockSignals(True)
        self._category_combo.clear()
        self._category_combo.addItems(sorted(cats.keys()))
        self._category_combo.blockSignals(False)
        self._on_category_changed()

    def _selected_channels(self) -> List[str]:
        channels = []
        for i in range(self._channel_list.count()):
            item = self._channel_list.item(i)
            if item.checkState() == Qt.Checked:
                channels.append(item.text())
        return channels

    def _current_analysis(self):
        cat = self._category_combo.currentText()
        name = self._type_combo.currentText()
        if not cat or not name:
            return None
        return AnalysisRegistry.get(cat, name)

    def _collect_params(self) -> Dict:
        """Read current values from dynamic parameter widgets + signal processing."""
        params: Dict = {}
        # Analysis-specific params
        for key, entry in self._param_widgets.items():
            pdef, widget = entry[0], entry[1]
            if pdef.param_type in ("int", "float"):
                params[key] = widget.value()
            elif pdef.param_type == "choice":
                params[key] = widget.currentText()
        # Signal processing params
        params["filter_type"] = self._filter_combo.currentText()
        params["filter_freq"] = self._filter_freq_spin.value()
        params["filter_freq2"] = self._filter_freq2_spin.value()
        params["filter_order"] = self._filter_order_spin.value()
        params["transform"] = self._transform_combo.currentText()
        params["smooth_window"] = self._smooth_spin.value()
        return params

    # ------------------------------------------------------------------
    def _rebuild_params_ui(self) -> None:
        """Recreate the parameter widgets for the currently selected analysis."""
        # Clear old widgets
        while self._params_layout.count():
            child = self._params_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._param_widgets.clear()

        analysis = self._current_analysis()
        if analysis is None:
            self._params_group.hide()
            return

        param_defs = analysis.get_parameters()
        if not param_defs:
            self._params_group.hide()
            return

        self._params_group.show()
        for row, p in enumerate(param_defs):
            label = QLabel(p.label + ":")
            self._params_layout.addWidget(label, row, 0)

            if p.param_type == "int":
                w = QSpinBox()
                w.setRange(int(p.min_val or 0), int(p.max_val or 999999))
                w.setSingleStep(int(p.step or 1))
                w.setValue(int(p.default))
                w.valueChanged.connect(self._schedule_analysis)
            elif p.param_type == "float":
                w = QDoubleSpinBox()
                w.setRange(p.min_val or 0.0, p.max_val or 999999.0)
                w.setSingleStep(p.step or 0.1)
                w.setDecimals(2)
                w.setValue(float(p.default))
                w.valueChanged.connect(self._schedule_analysis)
            elif p.param_type == "choice":
                w = QComboBox()
                w.addItems(p.choices or [])
                w.setCurrentText(str(p.default))
                w.currentTextChanged.connect(self._schedule_analysis)
            else:
                continue

            if p.tooltip:
                w.setToolTip(p.tooltip)

            self._params_layout.addWidget(w, row, 1)
            self._param_widgets[p.key] = (p, w)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot(str)
    def _on_filter_changed(self, text: str) -> None:
        """Show/hide filter sub-parameters based on filter type."""
        has_filter = text != "None"
        is_band = text in ("Band Pass", "Band Stop")
        self._filter_freq_label.setVisible(has_filter)
        self._filter_freq_spin.setVisible(has_filter)
        self._filter_freq2_label.setVisible(is_band)
        self._filter_freq2_spin.setVisible(is_band)
        self._filter_order_label.setVisible(has_filter)
        self._filter_order_spin.setVisible(has_filter)

    @pyqtSlot(str)
    def _on_transform_changed(self, text: str) -> None:
        """Show/hide smooth parameter based on transform selection."""
        visible = text == "Hilbert Envelope"
        self._smooth_label.setVisible(visible)
        self._smooth_spin.setVisible(visible)

    # ------------------------------------------------------------------
    # Source toggle & live streaming
    # ------------------------------------------------------------------
    @pyqtSlot(bool)
    def _on_source_toggled(self, file_checked: bool) -> None:
        """Switch between File and Live Stream source."""
        self._live_mode = not file_checked
        self._source_stack.setCurrentIndex(0 if file_checked else 1)
        if self._live_mode:
            self._init_live_buffers()
            if self._live_stream_active:
                self._live_refresh_timer.start()
        else:
            self._live_refresh_timer.stop()

    @pyqtSlot()
    def _on_buffer_config_changed(self) -> None:
        """Buffer size or unit changed — reinitialise buffers."""
        if self._live_mode:
            self._init_live_buffers()

    def _live_buffer_samples(self) -> int:
        """Return buffer size in samples based on current UI settings."""
        val = self._buf_size_spin.value()
        if self._buf_unit_combo.currentText() == "seconds":
            return max(1, int(val * _LIVE_FS))
        return val

    def _init_live_buffers(self) -> None:
        """Create or resize the rolling deques for live data."""
        n = self._live_buffer_samples()
        self._live_bufs = {ch: deque(maxlen=n) for ch in _LIVE_CHANNELS}
        self._live_dirty = False

    @pyqtSlot(dict)
    def feed_live_frame(self, frame: dict) -> None:
        """Receive a single IMU frame from the streaming tab."""
        if not self._live_mode:
            return
        for ch in _LIVE_CHANNELS:
            self._live_bufs[ch].append(frame.get(ch, 0.0))
        self._live_dirty = True

    @pyqtSlot(bool)
    def set_stream_active(self, active: bool) -> None:
        """Called when the streaming tab starts/stops streaming."""
        self._live_stream_active = active
        if self._live_mode:
            if active:
                self._init_live_buffers()
                self._live_refresh_timer.start()
                self._live_status_label.setText("Streaming")
                self._live_status_label.setStyleSheet("color: #34D399; font-weight: bold;")
            else:
                self._live_refresh_timer.stop()
                self._live_status_label.setText("Stopped")
                self._live_status_label.setStyleSheet("color: #FBBF24;")

    @pyqtSlot()
    def _on_live_refresh(self) -> None:
        """Periodically snapshot the live buffers and trigger analysis."""
        if not self._live_dirty:
            return
        self._live_dirty = False

        # Need at least 2 samples for any meaningful analysis
        if not self._live_bufs or len(self._live_bufs[_LIVE_CHANNELS[0]]) < 2:
            return

        # Snapshot deques into signals dict
        self._fs = _LIVE_FS
        self._signals = {ch: np.array(buf) for ch, buf in self._live_bufs.items()}
        n = len(self._signals[_LIVE_CHANNELS[0]])

        # Populate channels list if needed (only on first data or buffer resize)
        if self._column_names != _LIVE_CHANNELS:
            self._column_names = list(_LIVE_CHANNELS)
            nyquist = _LIVE_FS / 2.0 * 0.95
            self._filter_freq_spin.setMaximum(nyquist)
            self._filter_freq2_spin.setMaximum(nyquist)

            self._channel_list.blockSignals(True)
            self._channel_list.clear()
            for col in _LIVE_CHANNELS:
                item = QListWidgetItem(col)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self._channel_list.addItem(item)
            self._channel_list.blockSignals(False)

        self._run_analysis()

    @pyqtSlot()
    def _on_browse(self) -> None:
        start_dir = str(Path.home())
        current = self._file_edit.text()
        if current:
            parent = str(Path(current).parent)
            if Path(parent).is_dir():
                start_dir = parent

        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", start_dir,
            "CSV Files (*.csv);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return

        self._file_edit.setText(path)
        self._log_widget.log(f"Loading {Path(path).name}\u2026", LogLevel.INFO)
        self._worker.request_load(path)

    @pyqtSlot(float, dict, list)
    def _on_load_complete(self, fs: float, signals: dict, columns: list) -> None:
        self._fs = fs
        self._signals = signals
        self._column_names = columns
        n = len(next(iter(signals.values())))
        self._log_widget.log(
            f"Loaded: {len(columns)} channels, fs={fs:.1f} Hz, {n} samples",
            LogLevel.SUCCESS,
        )

        # Update filter frequency limits to Nyquist
        nyquist = fs / 2.0 * 0.95
        self._filter_freq_spin.setMaximum(nyquist)
        self._filter_freq2_spin.setMaximum(nyquist)

        # Populate channel list — all checked by default
        self._channel_list.blockSignals(True)
        self._channel_list.clear()
        for col in columns:
            item = QListWidgetItem(col)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._channel_list.addItem(item)
        self._channel_list.blockSignals(False)

        self._schedule_analysis()

    @pyqtSlot(str)
    def _on_load_failed(self, msg: str) -> None:
        self._log_widget.log(f"Load failed: {msg}", LogLevel.ERROR)

    @pyqtSlot()
    def _on_category_changed(self) -> None:
        cat = self._category_combo.currentText()
        types = AnalysisRegistry.get_categories().get(cat, [])
        self._type_combo.blockSignals(True)
        self._type_combo.clear()
        self._type_combo.addItems(types)
        self._type_combo.blockSignals(False)
        self._on_type_changed()

    @pyqtSlot()
    def _on_type_changed(self) -> None:
        """Analysis type changed — rebuild parameter UI and recompute."""
        self._rebuild_params_ui()
        self._schedule_analysis()

    @pyqtSlot()
    def _schedule_analysis(self) -> None:
        """Debounce analysis runs."""
        self._debounce_timer.start()

    @pyqtSlot()
    def _run_analysis(self) -> None:
        analysis = self._current_analysis()
        channels = self._selected_channels()
        if analysis is None or not channels or not self._signals:
            return
        params = self._collect_params()
        self._log_widget.log(
            f"Computing {analysis.name} for {', '.join(channels)}\u2026",
            LogLevel.INFO,
        )
        self._worker.request_analysis(
            analysis, self._fs, self._signals, channels, params)

    @pyqtSlot(object)
    def _on_analysis_complete(self, result: AnalysisResult) -> None:
        self._last_result = result
        self._log_widget.log("Analysis complete", LogLevel.SUCCESS)

        # Show/hide scale checkboxes based on 1D vs 2D
        if result.is_2d:
            self._log_x_cb.hide()
            self._log_y_cb.show()   # log frequency axis
            self._log_z_cb.show()
        else:
            self._log_x_cb.show()
            self._log_y_cb.show()
            self._log_z_cb.hide()

        # Enable "Save as Signal" for time-domain-compatible results
        can_save = False
        if not result.is_2d and self._signals:
            n_original = len(next(iter(self._signals.values())))
            can_save = any(len(y) == n_original
                          for y in result.y_data.values())
        self._save_signal_btn.setEnabled(can_save)

        # Update unit combos for the result's quantities
        self._update_unit_combos(result)

        # Render
        self._replot()

    @pyqtSlot(str)
    def _on_analysis_failed(self, msg: str) -> None:
        self._log_widget.log(f"Analysis failed: {msg}", LogLevel.ERROR)

    @pyqtSlot()
    def _on_display_changed(self) -> None:
        """Unit or log-scale changed — just re-render, no recompute."""
        if self._last_result is not None:
            self._replot()

    # ------------------------------------------------------------------
    def _update_unit_combos(self, result: AnalysisResult) -> None:
        """Refresh unit dropdown contents based on the result's axis quantities."""
        for combo, axis in [
            (self._x_unit_combo, result.x_axis),
            (self._y_unit_combo, result.y_axis),
        ]:
            prev = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            units = UnitConverter.get_units_for_quantity(axis.quantity)
            combo.addItems(units)
            # Restore previous selection if still valid, else use default
            if prev in units:
                combo.setCurrentText(prev)
            else:
                combo.setCurrentText(axis.default_unit)
            combo.blockSignals(False)

    def _replot(self) -> None:
        result = self._last_result
        if result is None:
            return
        x_unit = self._x_unit_combo.currentText() or result.x_axis.default_unit
        y_unit = self._y_unit_combo.currentText() or result.y_axis.default_unit
        log_x = self._log_x_cb.isChecked()
        log_y = self._log_y_cb.isChecked()
        log_z = self._log_z_cb.isChecked()
        self._plot_widget.plot(result, x_unit, y_unit, log_x, log_y, log_z,
                               all_channels=self._column_names)

    # ------------------------------------------------------------------
    @pyqtSlot()
    def _on_save_signal(self) -> None:
        """Add the current analysis result back as new channel(s)."""
        result = self._last_result
        if result is None or result.is_2d or not self._signals:
            return

        n_original = len(next(iter(self._signals.values())))
        analysis = self._current_analysis()
        suffix = analysis.name if analysis else "Derived"

        saved = 0
        self._channel_list.blockSignals(True)
        for ch, y in result.y_data.items():
            if len(y) != n_original:
                continue
            new_name = f"{ch} [{suffix}]"
            self._signals[new_name] = y.copy()
            if new_name not in self._column_names:
                self._column_names.append(new_name)
                item = QListWidgetItem(new_name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self._channel_list.addItem(item)
            saved += 1
        self._channel_list.blockSignals(False)

        if saved:
            self._log_widget.log(
                f"Saved {saved} signal(s) as new channels — "
                f"check them in the channel list to use",
                LogLevel.SUCCESS,
            )

    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        """Stop any running worker thread (called on app close)."""
        self._live_refresh_timer.stop()
        if self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
