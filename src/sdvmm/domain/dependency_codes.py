from __future__ import annotations

from typing import Literal

DependencyState = Literal[
    "satisfied",
    "missing_required_dependency",
    "optional_dependency_missing",
    "unresolved_dependency_context",
]

SATISFIED: DependencyState = "satisfied"
MISSING_REQUIRED_DEPENDENCY: DependencyState = "missing_required_dependency"
OPTIONAL_DEPENDENCY_MISSING: DependencyState = "optional_dependency_missing"
UNRESOLVED_DEPENDENCY_CONTEXT: DependencyState = "unresolved_dependency_context"

