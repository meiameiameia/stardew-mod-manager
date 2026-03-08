from __future__ import annotations

import argparse
from pathlib import Path

from sdvmm.services.mod_scanner import scan_mods_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan a Stardew Valley Mods directory and print inventory findings."
    )
    parser.add_argument("mods_dir", type=Path, help="Path to a Mods directory")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    inventory = scan_mods_directory(args.mods_dir)

    print(f"mods: {len(inventory.mods)}")
    print(f"warnings: {len(inventory.parse_warnings)}")
    print(f"duplicate_unique_ids: {len(inventory.duplicate_unique_ids)}")
    print(f"missing_required_dependencies: {len(inventory.missing_required_dependencies)}")

    for warning in inventory.parse_warnings:
        print(f"warning[{warning.code}] {warning.mod_path}: {warning.message}")

    for finding in inventory.duplicate_unique_ids:
        folders = ", ".join(str(path) for path in finding.folder_paths)
        print(f"duplicate[{finding.unique_id}] folders={folders}")

    for finding in inventory.missing_required_dependencies:
        print(
            "missing_dependency"
            f"[required_by={finding.required_by_unique_id}]"
            f" missing={finding.missing_unique_id}"
            f" folder={finding.required_by_folder}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
