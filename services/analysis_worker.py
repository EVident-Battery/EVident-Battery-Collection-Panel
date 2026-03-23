"""Background worker for CSV loading and analysis computation."""
from __future__ import annotations

import traceback
from typing import Dict, List, Optional

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from lib.analysis_registry import BaseAnalysis, AnalysisResult


class AnalysisWorker(QThread):
    """Runs CSV load or analysis compute off the main thread."""

    load_complete = pyqtSignal(float, dict, list)     # fs, signals, column_names
    load_failed = pyqtSignal(str)                     # error message
    analysis_complete = pyqtSignal(object)             # AnalysisResult
    analysis_failed = pyqtSignal(str)                  # error message

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._task: Optional[tuple] = None

    # ------------------------------------------------------------------
    def request_load(self, csv_path: str) -> None:
        """Queue a CSV load task and start the thread."""
        self._task = ("load", csv_path)
        if not self.isRunning():
            self.start()

    def request_analysis(self, analysis: BaseAnalysis, fs: float,
                         signals: Dict[str, np.ndarray],
                         channels: List[str],
                         params: Optional[Dict] = None) -> None:
        """Queue an analysis compute task and start the thread."""
        self._task = ("analyze", analysis, fs, signals, channels, params or {})
        if not self.isRunning():
            self.start()

    # ------------------------------------------------------------------
    def run(self) -> None:
        task = self._task
        if task is None:
            return

        try:
            if task[0] == "load":
                self._do_load(task[1])
            elif task[0] == "analyze":
                self._do_analyze(task[1], task[2], task[3], task[4], task[5])
        except Exception:
            tb = traceback.format_exc()
            if task[0] == "load":
                self.load_failed.emit(str(tb))
            else:
                self.analysis_failed.emit(str(tb))

    # ------------------------------------------------------------------
    def _do_load(self, csv_path: str) -> None:
        from lib.spectral_fingerprint import load_csv
        fs, signals = load_csv(csv_path)
        column_names = list(signals.keys())
        self.load_complete.emit(fs, signals, column_names)

    def _do_analyze(self, analysis: BaseAnalysis, fs: float,
                    signals: Dict[str, np.ndarray],
                    channels: List[str], params: Dict) -> None:
        result = analysis.compute(fs, signals, channels, **params)
        self.analysis_complete.emit(result)
