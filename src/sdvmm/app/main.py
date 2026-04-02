from __future__ import annotations

import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib

from PySide6.QtCore import QRectF
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from sdvmm.app.paths import default_app_state_file
from sdvmm.app.shell_service import AppShellService
from sdvmm.ui.main_window import MainWindow

APP_PACKAGE_NAME = "stardew-mod-manager"
APP_DISPLAY_NAME = "Cinderleaf"
APP_VERSION_FALLBACK = "unknown"
APP_VERSION_FILENAME = "app-version.txt"
APP_RUNTIME_ICON_NAMES = ("cinderleaf-icon.svg", "app-icon.png", "stardew-mod-manager.ico")
WINDOWS_APP_USER_MODEL_ID = "local.cinderleaf.cinderleaf"


def _resolve_app_version() -> str:
    runtime_root = _resolve_runtime_root()
    runtime_version_path = runtime_root / APP_VERSION_FILENAME
    if runtime_version_path.is_file():
        runtime_version_text = runtime_version_path.read_text(encoding="utf-8").strip()
        if runtime_version_text:
            return runtime_version_text

    pyproject_path = runtime_root / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
            pyproject_version = str(project["version"]).strip()
            if pyproject_version:
                return pyproject_version
        except Exception:
            pass

    try:
        return version(APP_PACKAGE_NAME)
    except PackageNotFoundError:
        return APP_VERSION_FALLBACK


def _resolve_runtime_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        return Path(bundle_root)
    return Path(__file__).resolve().parents[3]


def _resolve_runtime_icon_asset_path() -> Path | None:
    assets_root = _resolve_runtime_root() / "assets"
    for icon_name in APP_RUNTIME_ICON_NAMES:
        icon_path = assets_root / icon_name
        if icon_path.exists():
            return icon_path
    return None


def _load_svg_icon(icon_path: Path) -> QIcon | None:
    renderer = QSvgRenderer(str(icon_path))
    if not renderer.isValid():
        return None

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(QPixmap.fromImage(image))
    return icon if not icon.isNull() else None


def _resolve_app_icon() -> QIcon | None:
    icon_path = _resolve_runtime_icon_asset_path()
    if icon_path is None:
        return None
    if icon_path.suffix.lower() == ".svg":
        return _load_svg_icon(icon_path)

    icon = QIcon(str(icon_path))
    if not icon.isNull():
        return icon
    return None


def _configure_frozen_qt_plugin_paths() -> None:
    if getattr(sys, "_MEIPASS", None) is None:
        return

    runtime_root = _resolve_runtime_root()
    pyside_root = runtime_root / "PySide6"
    plugins_dir = pyside_root / "plugins"
    platforms_dir = plugins_dir / "platforms"

    if plugins_dir.is_dir():
        os.environ["QT_PLUGIN_PATH"] = str(plugins_dir)
    if platforms_dir.is_dir():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)


def _configure_windows_app_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            WINDOWS_APP_USER_MODEL_ID
        )
    except Exception:
        return


def main() -> int:
    _configure_windows_app_identity()
    _configure_frozen_qt_plugin_paths()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(_resolve_app_version())
    app_icon = _resolve_app_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)

    shell_service = AppShellService(state_file=default_app_state_file())
    window = MainWindow(shell_service=shell_service)
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
