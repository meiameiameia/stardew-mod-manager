from __future__ import annotations

"""UniqueID normalization policy for local scan comparisons.

Policy:
- Preserve manifest-provided UniqueID strings for display and reporting.
- Compare UniqueIDs using a canonical form: stripped + casefolded.

This keeps scan behavior deterministic across case-sensitive and
case-insensitive filesystems while preserving original user-facing values.
"""


def canonicalize_unique_id(value: str) -> str:
    return value.strip().casefold()
