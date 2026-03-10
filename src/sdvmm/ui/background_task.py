from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal


class BackgroundTaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class BackgroundTask(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.signals = BackgroundTaskSignals()

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # pragma: no cover - exercised via GUI integration
            self.signals.failed.emit(exc)
            return
        self.signals.succeeded.emit(result)
