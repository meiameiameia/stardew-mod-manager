# AI Audit Brief

## Purpose

This brief is for an external AI model to audit the current repository state, challenge the roadmap, and suggest the next highest-value product and architecture moves.

The goal is not to restate the whole codebase. The goal is to give enough high-signal context that another model can:

- assess current product maturity
- identify weak spots in architecture and UX
- challenge the roadmap ordering
- suggest missing risks, gaps, or simplifications

## Repository Snapshot

- Repository: `stardew-mod-manager`
- Platform: Python 3.12 + PySide6 desktop app
- Entry point: `sdvmm-ui` -> [`src/sdvmm/app/main.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/app/main.py)
- Current validation baseline:
  - `.\.venv\Scripts\python.exe -m pytest tests\unit -q`
  - latest verified result in this thread: `351 passed, 1 skipped`
  - UI startup smoke also passes offscreen
- Product posture:
  - local-first
  - safe-by-default
  - reversible where possible
  - sandbox remains the recommended path
  - no scraping, no browser automation, no premium-bypass behavior

## Current Product Shape

The app is no longer just a scanner. It now has a coherent local workflow:

1. scan installed mods
2. check update metadata
3. open the selected mod's remote page manually
4. download zip manually
5. intake/inspect detected zips
6. stage a package into `Plan & Install`
7. build an install plan
8. review/confirm execution
9. record install history
10. derive/review/execute recovery
11. inspect linked recovery history

The product is not feature-complete for public release, but it is materially beyond prototype state.

## Current Architecture

### High-level layers

- Domain models and codes:
  - [`src/sdvmm/domain/models.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/domain/models.py)
  - `*_codes.py` files under [`src/sdvmm/domain`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/domain)
- App/service orchestration:
  - [`src/sdvmm/app/shell_service.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/app/shell_service.py)
- Persistence:
  - [`src/sdvmm/services/app_state_store.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/services/app_state_store.py)
- UI shell:
  - [`src/sdvmm/ui/main_window.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/ui/main_window.py)
  - composed helper surfaces under [`src/sdvmm/ui`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/ui)

### Architectural direction

The current architecture intentionally keeps:

- policy and execution logic in app/service/domain layers
- Qt as a consumer of service contracts, not the source of truth
- install/recovery safety semantics below the UI
- local file-based persistence instead of a database

### Main seams that matter now

- `MainWindow` is still the largest integration surface and the main UX composition point
- `AppShellService` is the workflow backbone
- install and recovery history are file-backed, versioned, and now include stable IDs

## Current Strengths

### Install / recovery workflow

The strongest part of the app right now is the install/recovery foundation:

- install execution review contract exists
- explicit approval is required for real Mods execution
- install operations are recorded
- recovery plans can be derived from install history
- recovery plans can be reviewed against live filesystem state
- reviewed recovery plans can be executed
- recovery execution is recorded
- install and recovery records have stable IDs
- UI can inspect and execute recovery in a narrow, guarded flow

### Workflow continuity

The previously fragmented workflow has been tightened:

- `Packages & Intake` stages into `Plan & Install`
- `Plan & Install` owns planning/review/execution
- recovery is local to the same workflow surface
- install completion now links back into recovery selection

### UI composition progress

The app has already corrected several structural UI mistakes:

- `Plan & Install` now has a tab-local scroll host for constrained height
- `Packages & Intake`, `Plan & Install`, and `Recovery` have local output surfaces
- primary controls were moved out of the global detail area

## Current Weak Spots

### 1. Update-source diagnostics are still heuristic

The newest work in progress is around blocked update rows such as:

- `no_remote_link`
- `metadata_unavailable`

Current diagnostics are still inferred from UI-visible strings and existing selected-row state. This is useful, but not yet a durable backend contract.

The main unresolved product question is:

> Should update-source diagnostics stay as UI heuristics, or should the app promote them into a proper domain/app contract?

### 2. `MainWindow` is still the densest integration point

The app has improved composition and ownership boundaries, but `MainWindow` still carries substantial UI workflow logic and cross-surface coordination.

This is acceptable for now because product-facing workflow completion was prioritized over continued extraction, but it remains a maintenance risk.

### 3. Narrative output boxes still exist as secondary truth surfaces

Structured summaries/explanations/facts have been added to reduce dependence on narrative output, but the narrative boxes are still useful fallback/detail/debug surfaces.

The app should not remove them yet, but a future audit should determine when they can be collapsed or retired.

### 4. Public-release readiness work has barely started

Notably still pending:

- packaging/installer strategy
- code signing strategy
- release docs
- contributor run scripts / simpler launch ergonomics
- CI/release hardening
- migration discipline for public users

## Roadmap Status

### Completed or effectively closed

#### 1. Core Workflow Foundation

- scanning
- package inspection
- install planning and execution review
- sandbox install execution
- real-Mods guarded execution
- install history
- recovery derivation/review/execution
- recovery history with stable IDs

#### 2. Guided Manual Update Flow

- selected update row -> remote page
- manual download -> intake
- intake staging -> `Plan & Install`
- local workflow output in owning tabs

#### 3. Managed Live Mods Safety Baseline

- persistent live-destination safety panel
- explicit confirmation for real Mods execution
- real-Mods messaging now visible before execution

#### 4. History / Recovery UX Baseline

- readable recovery selector
- newest-first presentation
- linked recovery outcomes
- filterable recovery selector
- safer/no-ID legacy handling

### In progress

#### 5. Dependency / Conflict / Update Ergonomics

Already completed within this phase:

- update actionability filter in Inventory
- selected-row update guidance
- selected-row remote action enablement
- plan review summary/explanation/facts in `Plan & Install`
- initial selected-row update-source diagnostics line

Current recommendation:

- finish the selected-row update-source diagnostics track
- then reassess whether remaining pain is:
  - dependency/conflict clarity
  - update-source repair
  - or broader UI overload

### Next likely phase

#### 6. Update Source Diagnostics and Repair UX

This phase should distinguish:

- local/private mod
- missing update key
- unsupported update key format
- remote metadata lookup failure
- no provider mapping
- generic unknown source issue

And then later determine whether a repair flow is needed for:

- manual source association
- update-key correction
- unsupported provider mapping explanation

### Later planned phase

#### 7. UI/UX Consolidation and Release Readiness

This should happen only after the current workflow surfaces are stable enough to audit meaningfully.

Planned audits:

1. information architecture / duplicate-information audit
2. interaction-model / redesign-necessity audit
3. visual feedback / polish audit

## Current UX/Product Concerns Worth Challenging

An external model should specifically challenge these points:

### A. Is the current roadmap still in the right order?

The present recommendation is to continue with update-source diagnostics before doing the bigger UX consolidation phase.

Question:

> Is that the right order, or has the UI reached the point where consolidation should happen sooner?

### B. Should update diagnostics become a real service/domain contract?

Right now they are mostly UI-derived from existing states/messages.

Question:

> Is it time to add a first-class update-source diagnostics model below the UI, or is that premature?

### C. What should remain global vs tab-local?

The app now has:

- a global status strip
- tab-local outputs
- local summary/explanation/facts in `Plan & Install`
- selected-row guidance in `Inventory`
- a legacy bottom detail surface

Question:

> Which of these should remain, collapse, or be retired?

### D. Is the current desktop interaction model still too dense?

The current UI is functionally coherent, but still visually crowded.

Question:

> Where should the app adopt progressive disclosure, modals, expanders, or a stronger task-oriented layout?

## Explicit Constraints for the External Audit

The external audit should respect these repository/product constraints:

- no database unless there is a concrete product need
- no scraping or browser automation for downloads
- no premium-bypass behavior
- sandbox remains the recommended path until live flows are fully validated
- destructive or live-Mods operations require archive/recovery semantics
- product-facing workflow completion is favored over refactor churn

## Recommended Files To Read First

1. [`AGENTS.md`](/Users/darth/Projects/stardew-mod-manager/AGENTS.md)
2. [`README.md`](/Users/darth/Projects/stardew-mod-manager/README.md)
3. [`src/sdvmm/app/shell_service.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/app/shell_service.py)
4. [`src/sdvmm/domain/models.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/domain/models.py)
5. [`src/sdvmm/services/app_state_store.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/services/app_state_store.py)
6. [`src/sdvmm/ui/main_window.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/ui/main_window.py)
7. [`src/sdvmm/ui/plan_install_tab_surface.py`](/Users/darth/Projects/stardew-mod-manager/src/sdvmm/ui/plan_install_tab_surface.py)
8. [`tests/unit/test_main_window_gui_regression.py`](/Users/darth/Projects/stardew-mod-manager/tests/unit/test_main_window_gui_regression.py)
9. [`tests/unit/test_app_shell_service.py`](/Users/darth/Projects/stardew-mod-manager/tests/unit/test_app_shell_service.py)
10. [`tests/unit/test_app_state_store.py`](/Users/darth/Projects/stardew-mod-manager/tests/unit/test_app_state_store.py)

## What a Useful External Audit Should Produce

A useful audit response should include:

- architecture risks ordered by severity
- roadmap-order challenges, if any
- whether update-source diagnostics should stay UI-level or move below the UI
- concrete suggestions for simplifying the current UI without breaking workflow clarity
- criteria for when the app is ready for the later UI/UX consolidation phase
- the next 3-5 smallest safe increments, ordered by product value
