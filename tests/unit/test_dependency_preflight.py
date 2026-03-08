from __future__ import annotations

from pathlib import Path

from sdvmm.domain.models import InstalledMod, ManifestDependency, PackageModEntry
from sdvmm.services.dependency_preflight import (
    evaluate_installed_dependencies,
    evaluate_package_dependencies,
)


def test_installed_dependency_is_marked_satisfied_when_provider_is_present() -> None:
    provider = _installed_mod(unique_id="Sample.Provider", dependencies=tuple())
    consumer = _installed_mod(
        unique_id="Sample.Consumer",
        dependencies=(ManifestDependency(unique_id="Sample.Provider", required=True),),
    )

    findings = evaluate_installed_dependencies((provider, consumer))

    assert len(findings) == 1
    assert findings[0].state == "satisfied"
    assert findings[0].dependency_unique_id == "Sample.Provider"


def test_installed_dependency_is_marked_missing_when_required_provider_absent() -> None:
    consumer = _installed_mod(
        unique_id="Sample.Consumer",
        dependencies=(ManifestDependency(unique_id="Sample.Provider", required=True),),
    )

    findings = evaluate_installed_dependencies((consumer,))

    assert len(findings) == 1
    assert findings[0].state == "missing_required_dependency"
    assert findings[0].required is True


def test_package_dependency_can_be_resolved_against_installed_context() -> None:
    package_mod = PackageModEntry(
        name="Package Consumer",
        unique_id="Pkg.Consumer",
        version="1.0.0",
        manifest_path="Pkg/manifest.json",
        dependencies=(ManifestDependency(unique_id="Sample.Provider", required=True),),
    )
    installed_provider = _installed_mod(unique_id="Sample.Provider", dependencies=tuple())

    findings = evaluate_package_dependencies(
        package_mods=(package_mod,),
        installed_mods=(installed_provider,),
        source="package_inspection",
    )

    assert len(findings) == 1
    assert findings[0].state == "satisfied"


def test_package_dependency_uses_unresolved_state_without_inventory_context() -> None:
    package_mod = PackageModEntry(
        name="Package Consumer",
        unique_id="Pkg.Consumer",
        version="1.0.0",
        manifest_path="Pkg/manifest.json",
        dependencies=(ManifestDependency(unique_id="Sample.Provider", required=True),),
    )

    findings = evaluate_package_dependencies(
        package_mods=(package_mod,),
        installed_mods=None,
        source="package_inspection",
    )

    assert len(findings) == 1
    assert findings[0].state == "unresolved_dependency_context"


def test_package_dependency_marks_optional_missing_when_known_context_lacks_provider() -> None:
    package_mod = PackageModEntry(
        name="Package Consumer",
        unique_id="Pkg.Consumer",
        version="1.0.0",
        manifest_path="Pkg/manifest.json",
        dependencies=(ManifestDependency(unique_id="Sample.Optional", required=False),),
    )

    findings = evaluate_package_dependencies(
        package_mods=(package_mod,),
        installed_mods=tuple(),
        source="downloads_intake",
    )

    assert len(findings) == 1
    assert findings[0].state == "optional_dependency_missing"
    assert findings[0].required is False


def _installed_mod(
    *,
    unique_id: str,
    dependencies: tuple[ManifestDependency, ...],
) -> InstalledMod:
    folder = Path("/tmp") / unique_id.replace(".", "_")
    return InstalledMod(
        unique_id=unique_id,
        name=unique_id,
        version="1.0.0",
        folder_path=folder,
        manifest_path=folder / "manifest.json",
        dependencies=dependencies,
        update_keys=tuple(),
    )

