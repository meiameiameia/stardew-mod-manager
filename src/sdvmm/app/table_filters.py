from __future__ import annotations

from collections.abc import Iterable


def row_matches_filter(values: Iterable[str], filter_text: str) -> bool:
    """Return whether a row should remain visible for a local text filter.

    Matching is case-insensitive and token-based: each token from the filter
    text must be present in the concatenated row text.
    """
    normalized_filter = " ".join(filter_text.split()).casefold()
    if not normalized_filter:
        return True

    haystack = " ".join(value.strip() for value in values if value).casefold()
    return all(token in haystack for token in normalized_filter.split())
