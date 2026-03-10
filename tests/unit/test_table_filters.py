from sdvmm.app.table_filters import row_matches_filter


def test_row_matches_filter_allows_empty_filter() -> None:
    assert row_matches_filter(("Visible Fish", "TehPers"), "")


def test_row_matches_filter_is_case_insensitive_contains() -> None:
    assert row_matches_filter(("Visible Fish", "TehPers"), "visible")
    assert row_matches_filter(("Visible Fish", "TehPers"), "TEHP")


def test_row_matches_filter_requires_all_tokens() -> None:
    assert row_matches_filter(("Visible Fish", "Pathoschild.ContentPatcher"), "fish content")
    assert not row_matches_filter(("Visible Fish", "Pathoschild.ContentPatcher"), "fish tractor")
