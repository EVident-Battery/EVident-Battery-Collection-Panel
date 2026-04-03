"""WebSocket worker thread for real-time IMU data streaming."""
from __future__ import annotations

import json
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from websockets.sync.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed


class StreamingWorker(QThread):
    """Connects to a sensor's WebSocket server and streams IMU data."""

    connected = pyqtSignal()
    disconnected = pyqtSignal(str)
    stream_status = pyqtSignal(bool)
    data_received = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, ip: str, parent: Optional[QThread] = None) -> None:
        super().__init__(parent)
        self._ip = ip
        self._should_start = False
        self._should_stop = False
        self._should_disconnect = False

    # -- public control methods (called from main thread) --

    def request_start(self) -> None:
        self._should_start = True

    def request_stop(self) -> None:
        self._should_stop = True

    def request_disconnect(self) -> None:
        self._should_disconnect = True

    # -- thread entry point --

    def run(self) -> None:
        try:
            ws = ws_connect(f"ws://{self._ip}:81/", open_timeout=5)
        except Exception as exc:
            self.error_occurred.emit(f"Connection failed: {exc}")
            self.disconnected.emit(str(exc))
            return

        try:
            # Wait for hello
            raw = ws.recv(timeout=5)
            msg = json.loads(raw)
            if msg.get("type") != "hello":
                self.error_occurred.emit(f"Unexpected hello: {raw}")
                self.disconnected.emit("bad handshake")
                return

            self.connected.emit()

            # Main receive loop
            while not self._should_disconnect:
                # Check command flags
                if self._should_start:
                    self._should_start = False
                    ws.send("start")
                if self._should_stop:
                    self._should_stop = False
                    ws.send("stop")

                try:
                    raw = ws.recv(timeout=0.1)
                except TimeoutError:
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "status":
                    self.stream_status.emit(msg.get("stream") == "on")
                elif "t" in msg:
                    self.data_received.emit(msg)
                elif msg.get("type") == "error":
                    self.error_occurred.emit(msg.get("msg", "unknown error"))

        except ConnectionClosed as exc:
            self.disconnected.emit(f"Connection closed: {exc}")
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            self.disconnected.emit(str(exc))
        finally:
            try:
                ws.close()
            except Exception:
                pass
            self.disconnected.emit("disconnected")
