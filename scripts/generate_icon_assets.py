from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


SVG_NAME = "cinderleaf-icon.svg"
PNG_NAME = "app-icon.png"
ICO_NAME = "stardew-mod-manager.ico"
PNG_SIZE = 512
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _asset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "assets"


def _render_svg_to_image(svg_path: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG icon source: {svg_path}")

    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def _image_to_png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Unable to open in-memory PNG buffer")
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Unable to encode PNG image")
    buffer.close()
    return bytes(data)


def _write_ico(ico_path: Path, images: list[tuple[int, bytes]]) -> None:
    # ICO stores PNG blobs directly for modern icon sizes, which keeps the
    # source-of-truth SVG in control of every rendered variant.
    header = struct.pack("<HHH", 0, 1, len(images))
    entries: list[bytes] = []
    offset = 6 + 16 * len(images)
    for size, blob in images:
        width = size if size < 256 else 0
        height = size if size < 256 else 0
        entries.append(
            struct.pack(
                "<BBBBHHII",
                width,
                height,
                0,
                0,
                1,
                32,
                len(blob),
                offset,
            )
        )
        offset += len(blob)

    with ico_path.open("wb") as handle:
        handle.write(header)
        for entry in entries:
            handle.write(entry)
        for _, blob in images:
            handle.write(blob)


def main() -> int:
    asset_root = _asset_root()
    svg_path = asset_root / SVG_NAME
    png_path = asset_root / PNG_NAME
    ico_path = asset_root / ICO_NAME

    if not svg_path.is_file():
        raise FileNotFoundError(f"SVG source not found: {svg_path}")

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    png_image = _render_svg_to_image(svg_path, PNG_SIZE)
    if not png_image.save(str(png_path), "PNG"):
        raise RuntimeError(f"Unable to write PNG asset: {png_path}")

    ico_images: list[tuple[int, bytes]] = []
    for size in ICO_SIZES:
        image = _render_svg_to_image(svg_path, size)
        ico_images.append((size, _image_to_png_bytes(image)))
    _write_ico(ico_path, ico_images)

    print(png_path)
    print(ico_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
