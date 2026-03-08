from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from sdvmm.domain.install_codes import BLOCKED, INSTALL_NEW, OVERWRITE_WITH_ARCHIVE
from sdvmm.services.sandbox_installer import (
    SandboxInstallError,
    build_sandbox_install_plan,
    execute_sandbox_install_plan,
)


def test_install_plan_creation_for_new_target(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()

    package = _build_zip(
        tmp_path / "direct.zip",
        {
            "MyMod/manifest.json": '{"Name":"My Mod","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
            "MyMod/content.json": "{}",
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=False,
    )

    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.target_path == sandbox / "MyMod"
    assert entry.action == INSTALL_NEW
    assert entry.target_exists is False
    assert entry.archive_path is None
    assert entry.can_install is True
    assert entry.warnings == ()


def test_install_plan_detects_existing_target_conflict_when_overwrite_disabled(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()
    (sandbox / "MyMod").mkdir()

    package = _build_zip(
        tmp_path / "direct.zip",
        {
            "MyMod/manifest.json": '{"Name":"My Mod","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=False,
    )

    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.target_exists is True
    assert entry.action == BLOCKED
    assert entry.can_install is False
    assert entry.archive_path is None
    assert any("already exists" in warning for warning in entry.warnings)


def test_install_plan_allows_overwrite_and_sets_archive_path(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()
    (sandbox / "MyMod").mkdir()

    package = _build_zip(
        tmp_path / "direct.zip",
        {
            "MyMod/manifest.json": '{"Name":"My Mod","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=True,
    )

    entry = plan.entries[0]
    assert entry.action == OVERWRITE_WITH_ARCHIVE
    assert entry.can_install is True
    assert entry.archive_path == archive_root / "MyMod__sdvmm_archive_001"


def test_archive_path_generation_uses_next_available_suffix(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()
    (sandbox / "MyMod").mkdir()
    (archive_root / "MyMod__sdvmm_archive_001").mkdir()

    package = _build_zip(
        tmp_path / "direct.zip",
        {
            "MyMod/manifest.json": '{"Name":"My Mod","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=True,
    )

    assert plan.entries[0].archive_path == archive_root / "MyMod__sdvmm_archive_002"


def test_execute_sandbox_install_for_new_target(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()

    package = _build_zip(
        tmp_path / "install.zip",
        {
            "MyMod/manifest.json": '{"Name":"My Mod","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
            "MyMod/assets/file.txt": "hello",
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=False,
    )
    result = execute_sandbox_install_plan(plan)

    assert len(result.installed_targets) == 1
    installed = result.installed_targets[0]
    assert installed == sandbox / "MyMod"
    assert (installed / "manifest.json").exists()
    assert (installed / "assets" / "file.txt").read_text(encoding="utf-8") == "hello"

    assert result.archived_targets == ()
    assert result.scan_context_path == sandbox
    assert len(result.inventory.mods) == 1
    assert result.inventory.mods[0].unique_id == "Pkg.MyMod"


def test_execute_overwrite_creates_archive_then_replaces_target(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()

    existing_target = sandbox / "MyMod"
    existing_target.mkdir()
    (existing_target / "old.txt").write_text("old", encoding="utf-8")
    (existing_target / "manifest.json").write_text(
        '{"Name":"Old","UniqueID":"Pkg.MyMod","Version":"0.9.0"}',
        encoding="utf-8",
    )

    package = _build_zip(
        tmp_path / "overwrite.zip",
        {
            "MyMod/manifest.json": '{"Name":"New","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
            "MyMod/new.txt": "new",
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=True,
    )
    result = execute_sandbox_install_plan(plan)

    assert (existing_target / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (existing_target / "old.txt").exists()

    assert len(result.archived_targets) == 1
    archived_path = result.archived_targets[0]
    assert archived_path.exists()
    assert (archived_path / "old.txt").read_text(encoding="utf-8") == "old"


def test_execute_overwrite_is_blocked_when_archive_step_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()

    existing_target = sandbox / "MyMod"
    existing_target.mkdir()
    (existing_target / "keep.txt").write_text("keep", encoding="utf-8")
    (existing_target / "manifest.json").write_text(
        '{"Name":"Keep","UniqueID":"Pkg.MyMod","Version":"0.9.0"}',
        encoding="utf-8",
    )

    package = _build_zip(
        tmp_path / "overwrite.zip",
        {
            "MyMod/manifest.json": '{"Name":"New","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
            "MyMod/new.txt": "new",
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=True,
    )
    archive_path = plan.entries[0].archive_path
    assert archive_path is not None

    def failing_move(source: Path, destination: Path) -> None:
        if source == existing_target and destination == archive_path:
            raise OSError("simulated archive failure")
        source.rename(destination)

    monkeypatch.setattr("sdvmm.services.sandbox_installer._move_path", failing_move)

    with pytest.raises(SandboxInstallError, match="Could not archive existing target"):
        execute_sandbox_install_plan(plan)

    assert existing_target.exists()
    assert (existing_target / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not archive_path.exists()


def test_execute_overwrite_attempts_bounded_recovery_when_replacement_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()

    existing_target = sandbox / "MyMod"
    existing_target.mkdir()
    (existing_target / "keep.txt").write_text("keep", encoding="utf-8")
    (existing_target / "manifest.json").write_text(
        '{"Name":"Keep","UniqueID":"Pkg.MyMod","Version":"0.9.0"}',
        encoding="utf-8",
    )

    package = _build_zip(
        tmp_path / "overwrite.zip",
        {
            "MyMod/manifest.json": '{"Name":"New","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
            "MyMod/new.txt": "new",
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=True,
    )

    def failing_replace_move(source: Path, destination: Path) -> None:
        if destination == existing_target and source.parent.name.startswith(".sdvmm-stage-"):
            raise OSError("simulated replacement failure")
        source.rename(destination)

    monkeypatch.setattr("sdvmm.services.sandbox_installer._move_path", failing_replace_move)

    with pytest.raises(SandboxInstallError, match="Best-effort recovery restored original target"):
        execute_sandbox_install_plan(plan)

    assert existing_target.exists()
    assert (existing_target / "keep.txt").read_text(encoding="utf-8") == "keep"

    archive_path = plan.entries[0].archive_path
    assert archive_path is not None
    assert not archive_path.exists()


def test_plan_supports_nested_and_multi_package_layouts(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()

    package = _build_zip(
        tmp_path / "multi_nested.zip",
        {
            "Pack/ModA/manifest.json": '{"Name":"A","UniqueID":"Pkg.A","Version":"1.0.0"}',
            "Pack/ModB/manifest.json": '{"Name":"B","UniqueID":"Pkg.B","Version":"1.0.0"}',
            "Outer/Inner/ModC/manifest.json": '{"Name":"C","UniqueID":"Pkg.C","Version":"1.0.0"}',
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=False,
    )

    assert len(plan.entries) == 3
    assert sorted(entry.target_path.name for entry in plan.entries) == ["ModA", "ModB", "ModC"]
    assert all(entry.can_install for entry in plan.entries)


def test_plan_marks_too_deep_package_with_no_entries(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()

    package = _build_zip(
        tmp_path / "too_deep.zip",
        {
            "A/B/C/D/manifest.json": '{"Name":"Deep","UniqueID":"Pkg.Deep","Version":"1.0.0"}',
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=False,
    )

    assert plan.entries == ()
    assert any("no installable mods" in warning.lower() for warning in plan.plan_warnings)


def test_execute_blocked_plan_raises_error(tmp_path: Path) -> None:
    sandbox = tmp_path / "SandboxMods"
    archive_root = tmp_path / "SandboxArchive"
    sandbox.mkdir()
    archive_root.mkdir()
    (sandbox / "MyMod").mkdir()

    package = _build_zip(
        tmp_path / "direct.zip",
        {
            "MyMod/manifest.json": '{"Name":"My Mod","UniqueID":"Pkg.MyMod","Version":"1.0.0"}',
        },
    )

    plan = build_sandbox_install_plan(
        package,
        sandbox,
        archive_root,
        allow_overwrite=False,
    )

    with pytest.raises(SandboxInstallError, match="No installable entries"):
        execute_sandbox_install_plan(plan)


def _build_zip(zip_path: Path, files: dict[str, str]) -> Path:
    with ZipFile(zip_path, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)

    return zip_path
