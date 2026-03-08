from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from sdvmm.app.paths import default_app_state_file
from sdvmm.app.shell_service import AppShellService
from sdvmm.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    shell_service = AppShellService(state_file=default_app_state_file())
    window = MainWindow(shell_service=shell_service)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
