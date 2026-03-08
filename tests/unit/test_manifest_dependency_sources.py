from __future__ import annotations

from pathlib import Path

from sdvmm.services.manifest_parser import parse_manifest_text


def test_parse_manifest_keeps_direct_dependencies() -> None:
    parse_result = parse_manifest_text(
        raw_text=(
            "{"
            '"Name":"Consumer",'
            '"UniqueID":"Sample.Consumer",'
            '"Version":"1.0.0",'
            '"Dependencies":[{"UniqueID":"Sample.Required","IsRequired":true}]'
            "}"
        ),
        mod_dir=Path("/tmp/Consumer"),
        manifest_path=Path("/tmp/Consumer/manifest.json"),
    )

    assert parse_result.manifest is not None
    assert len(parse_result.manifest.dependencies) == 1
    assert parse_result.manifest.dependencies[0].unique_id == "Sample.Required"
    assert parse_result.manifest.dependencies[0].required is True


def test_parse_manifest_adds_required_dependency_from_content_pack_for() -> None:
    parse_result = parse_manifest_text(
        raw_text=(
            "{"
            '"Name":"CP Pack",'
            '"UniqueID":"Sample.ContentPack",'
            '"Version":"1.0.0",'
            '"ContentPackFor":{"UniqueID":"Pathoschild.ContentPatcher"}'
            "}"
        ),
        mod_dir=Path("/tmp/ContentPack"),
        manifest_path=Path("/tmp/ContentPack/manifest.json"),
    )

    assert parse_result.manifest is not None
    assert len(parse_result.manifest.dependencies) == 1
    dependency = parse_result.manifest.dependencies[0]
    assert dependency.unique_id == "Pathoschild.ContentPatcher"
    assert dependency.required is True

