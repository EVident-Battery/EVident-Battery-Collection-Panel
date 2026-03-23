"""Data Analysis tab UI widget."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QFileDialog,
    QGroupBox, QGridLayout, QCheckBox, QListWidget,
    QListWidgetItem, QSplitter, QSpinBox, QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot

# Trigger analysis plugin registration on import
import lib.analyses  # noqa: F401

from lib.analysis_registry import AnalysisRegistry, AnalysisResult, UnitConverter
from services.analysis_worker import AnalysisWorker
from ui.log_widget import LogWidget, LogLevel
from ui.plot_widget import PlotWidget


_INNER_GROUP_STYLE = """
    QGroupBox { border: none; background: transparent; margin-top: 0px; }
    QGroupBox::title { color: #94A3B8; }
"""


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

        controls.addWidget(self._create_file_group())
        controls.addWidget(self._create_analysis_group())
        controls.addWidget(self._create_channels_group())
        controls.addWidget(self._create_units_group())
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
    def _create_file_group(self) -> QGroupBox:
        grp = QGroupBox("File")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QGridLayout(grp)
        lay.setContentsMargins(8, 4, 8, 4)

        self._file_edit = QLineEdit()
        self._file_edit.setReadOnly(True)
        self._file_edit.setPlaceholderText("No file selected")
        self._file_edit.setMinimumWidth(180)
        lay.addWidget(self._file_edit, 0, 0)

        self._browse_btn = QPushButton("Browse\u2026")
        self._browse_btn.setFixedWidth(80)
        lay.addWidget(self._browse_btn, 0, 1)

        return grp

    # ------------------------------------------------------------------
    def _create_analysis_group(self) -> QGroupBox:
        grp = QGroupBox("Analysis")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QGridLayout(grp)
        lay.setContentsMargins(8, 4, 8, 4)

        lay.addWidget(QLabel("Category:"), 0, 0)
        self._category_combo = QComboBox()
        self._category_combo.setMinimumWidth(140)
        lay.addWidget(self._category_combo, 0, 1)

        lay.addWidget(QLabel("Type:"), 1, 0)
        self._type_combo = QComboBox()
        self._type_combo.setMinimumWidth(140)
        lay.addWidget(self._type_combo, 1, 1)

        # _populate_categories() is called after all groups are created
        return grp

    # ------------------------------------------------------------------
    def _create_channels_group(self) -> QGroupBox:
        grp = QGroupBox("Channels")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(8, 4, 8, 4)

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
        lay.setContentsMargins(8, 4, 8, 4)

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
    def _create_params_group(self) -> QGroupBox:
        grp = QGroupBox("Parameters")
        grp.setStyleSheet(_INNER_GROUP_STYLE)
        self._params_layout = QGridLayout(grp)
        self._params_layout.setContentsMargins(8, 4, 8, 4)
        grp.hide()
        return grp

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self._browse_btn.clicked.connect(self._on_browse)
        self._category_combo.currentTextChanged.connect(self._on_category_changed)
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._channel_list.itemChanged.connect(self._schedule_analysis)
        self._x_unit_combo.currentTextChanged.connect(self._on_display_changed)
        self._y_unit_combo.currentTextChanged.connect(self._on_display_changed)
        self._log_x_cb.stateChanged.connect(self._on_display_changed)
        self._log_y_cb.stateChanged.connect(self._on_display_changed)
        self._log_z_cb.stateChanged.connect(self._on_display_changed)

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
        """Read current values from the dynamic parameter widgets."""
        params: Dict = {}
        for key, (pdef, widget) in self._param_widgets.items():
            if pdef.param_type in ("int", "float"):
                params[key] = widget.value()
            elif pdef.param_type == "choice":
                params[key] = widget.currentText()
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
    def cleanup(self) -> None:
        """Stop any running worker thread (called on app close)."""
        if self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
