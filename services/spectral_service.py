"""Qt-threaded wrapper around spectral_fingerprint for training and detection."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from lib.spectral_fingerprint import (
    SpectralAnalyzer,
    SpectralBaseline,
    DetectionResult,
    train_from_folder,
    load_csv,
)


class TrainWorker(QThread):
    """Trains a spectral baseline from a folder of CSV recordings."""

    training_complete = pyqtSignal(object)  # SpectralBaseline
    training_failed = pyqtSignal(str)

    def __init__(
        self,
        folder: str,
        fs: float,
        nperseg: int = 4096,
        p_fa: float = 0.01,
    ) -> None:
        super().__init__()
        self.folder = folder
        self.fs = fs
        self.nperseg = nperseg
        self.p_fa = p_fa

    def run(self) -> None:
        try:
            analyzer = SpectralAnalyzer(fs=self.fs, nperseg=self.nperseg)
            baseline = train_from_folder(
                self.folder, analyzer, p_fa=self.p_fa, verbose=False,
            )
            self.training_complete.emit(baseline)
        except Exception as e:
            self.training_failed.emit(str(e))


class CheckWorker(QThread):
    """Checks a single CSV recording against a trained baseline."""

    check_complete = pyqtSignal(str, object, bool)  # filename, DetectionResult, any_triggered
    check_failed = pyqtSignal(str, str)              # filename, error

    def __init__(self, csv_path: str, baseline: SpectralBaseline) -> None:
        super().__init__()
        self.csv_path = csv_path
        self.baseline = baseline

    def run(self) -> None:
        try:
            fs, signals = load_csv(self.csv_path)
            result = self.baseline.detect(signals)
            any_triggered = any(result.triggered.values())
            self.check_complete.emit(self.csv_path, result, any_triggered)
        except Exception as e:
            self.check_failed.emit(self.csv_path, str(e))


class SpectralService(QObject):
    """Manages spectral training and detection workers."""

    training_complete = pyqtSignal(object)   # SpectralBaseline
    training_failed = pyqtSignal(str)
    check_complete = pyqtSignal(str, object, bool)  # filename, DetectionResult, any_triggered
    check_failed = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._baseline: Optional[SpectralBaseline] = None
        self._train_worker: Optional[TrainWorker] = None
        self._check_worker: Optional[CheckWorker] = None

    @property
    def baseline(self) -> Optional[SpectralBaseline]:
        return self._baseline

    def set_baseline(self, baseline: SpectralBaseline) -> None:
        """Set a pre-loaded baseline for detection (used by 'Continue Last Program')."""
        self._baseline = baseline

    def start_training(
        self,
        folder: str,
        fs: float,
        nperseg: int = 4096,
        p_fa: float = 0.01,
    ) -> None:
        """Start training in a background thread."""
        self._train_worker = TrainWorker(folder, fs, nperseg, p_fa)
        self._train_worker.training_complete.connect(self._on_training_complete)
        self._train_worker.training_failed.connect(self._on_training_failed)
        self._train_worker.start()

    def check_recording(self, csv_path: str) -> None:
        """Check a single recording against the trained baseline."""
        if self._baseline is None:
            self.check_failed.emit(csv_path, "No trained baseline available")
            return

        self._check_worker = CheckWorker(csv_path, self._baseline)
        self._check_worker.check_complete.connect(self._on_check_complete)
        self._check_worker.check_failed.connect(self._on_check_failed)
        self._check_worker.start()

    def _on_training_complete(self, baseline: SpectralBaseline) -> None:
        self._baseline = baseline
        self.training_complete.emit(baseline)

    def _on_training_failed(self, error: str) -> None:
        self.training_failed.emit(error)

    def _on_check_complete(self, filename: str, result: DetectionResult, any_triggered: bool) -> None:
        self.check_complete.emit(filename, result, any_triggered)

    def _on_check_failed(self, filename: str, error: str) -> None:
        self.check_failed.emit(filename, error)
