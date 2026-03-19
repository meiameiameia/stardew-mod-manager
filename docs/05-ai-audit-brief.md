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
  - latest verified result in this thread: `468 passed, 1 skipped`
  - UI startup smoke also passes offscreen
- Shipped baseline in this brief: `0.6.0` (includes real-vs-sandbox compare visibility baseline, backup-bundle inspection baseline, and read-only restore/import planning baseline)
- Product posture:
  - local-first
  - safe-by-default
  - reversible where possible
  - sandbox remains the recommended path
  - no scraping, no browser automation, no premium-bypass behavior
  - strongest near-term lane is safe local workflow, dev-loop trust, and migration trust
  - not aiming to become a one-click downloader or broad profile manager in the near term

## Current Product Shape

The app is no longer just a scanner. It now has a coherent local workflow:

1. scan installed mods
2. check update metadata
3. open the selected mod's remote page manually
4. download zip manually
5. intake/inspect one or more selected zips
6. review per-package batch inspection results
7. stage one package into `Plan & Install`
8. build an install plan
9. review/confirm execution
10. record install history
11. derive/review/execute recovery
12. inspect linked recovery history
13. launch Stardew/SMAPI against sandbox Mods only
14. sync selected real Mods into sandbox Mods
15. promote selected sandbox Mods into real Mods through an explicit managed flow
16. compare configured real Mods vs sandbox Mods in a dedicated drift view before sync/promotion decisions

The product is not feature-complete for public release, but it is materially beyond prototype state.

The near-term product direction now explicitly includes a mod-development workflow, not only general end-user mod management.
The current private-testing build includes the first multi-zip intake step, second watcher-path intake convenience, a visibility-first real-vs-sandbox compare baseline, read-only backup-bundle inspection, and read-only restore/import planning, while intentionally stopping short of blind multi-package planning/install behavior, compare-driven write shortcuts, and restore/apply behavior.
It now also includes practical session persistence ergonomics and explicit local backup export, which makes restore/import execution the next honest workflow step.

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
- sandbox dev-loop trust now depends heavily on `AppShellService` path validation and live-write policy

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
- `Packages & Intake` can now inspect multiple selected zips while preserving per-package visibility
- watcher intake can monitor two configured paths into the same detected-packages flow
- `Plan & Install` owns planning/review/execution
- recovery is local to the same workflow surface
- install completion now links back into recovery selection
- sandbox launch/sync/promotion now make the app directly useful for mod-development iteration, not just mod curation

### UI composition progress

The app has already corrected several structural UI mistakes:

- primary controls were moved out of the bottom detail area
- setup/configuration now lives in the main workspace instead of the bottom panel
- the bottom area is now output-only

The UI is still dense, but further generic decomposition is no longer the highest-value track.

## Current Weak Spots

### 1. Backup / restore / migration foundation is only partially established

State is durable and atomic, and the app now has explicit backup export, read-only bundle inspection, and read-only restore/import planning, but restore/apply ergonomics are not yet established.

The next question is:

> What restore/import execution baseline should exist now that export, inspection, and planning already exist?

### 2. Sandbox promotion policy is intentionally conservative

The product now has explicit:

- sandbox-only launch
- selected `real -> sandbox` sync
- selected `sandbox -> real` promotion

The remaining question is not whether the dev loop exists. It is how far to extend ergonomics without weakening trust semantics.

Current behavior is intentionally conservative:

- preview/review before live writes
- archive-aware replace for conflicts
- no blind overwrite
- archive/recovery trust preserved for real writes

The next unresolved product question remains:

> How should the app improve promotion speed and clarity now that preview + archive-aware replace already exists, without making live promotion feel casual or opaque?

### 3. Open-folder and local convenience ergonomics are still light

The app is now strong on explicit workflow semantics, but everyday local movement around Mods, archives, and export bundles still costs more clicks than it should.

The next question is:

> Which explicit open-folder conveniences add real daily value without turning the app into a shell-automation tangle?

### 4. `MainWindow` is still the densest integration point

The app has improved ownership boundaries, but `MainWindow` still carries substantial UI workflow logic and cross-surface coordination.

This is acceptable for now because product-facing workflow completion was correctly prioritized, but it remains a maintenance risk.

### 5. Desktop interaction density is improved, not solved

The app is cleaner than before, but workflow surfaces are still dense. This is now a secondary concern behind sandbox dev-loop trust and live-write clarity.

### 6. Public-release readiness work has barely started

Notably still pending:

- packaging/installer strategy
- code signing strategy
- release docs
- contributor run scripts / simpler launch ergonomics
- CI/release hardening
- migration discipline for public users

### 7. Multi-package planning is intentionally not solved yet

The app can now inspect multiple zip files in one explicit batch, but it does not yet build or execute a true multi-package install plan.

That limitation is intentional:

- per-package inspection is already useful for private testing and download triage
- the current planner remains clearer and safer when staging exactly one package at a time
- pushing straight into batch execution now would create review ambiguity

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

### Recently completed

#### 5. Sandbox Dev Loop Foundation

Already completed or effectively implemented:

- sandbox-only SMAPI dev launch
- selected `real -> sandbox` sync
- selected `sandbox -> real` managed promotion
- promotion preview/review + archive-aware replace conflict handling
- partial-failure safety handling for archive-aware promotion paths

#### 6. Multi-Zip Intake + Second Watcher Path Baseline

Implemented for `0.3.0`/`0.3.1`:

- multi-file zip selection in `Packages & Intake`
- batch inspection with per-package result visibility
- explicit single-package staging from the selected inspected package
- dual watcher paths feeding one intake detection flow
- no blind batch planning/install

Current recommendation:

- use private testing to validate whether batch inspection + single-package staging feels clear enough before expanding planner semantics
- preserve explicit plan review as a non-negotiable constraint for any later multi-package work

#### 7. Real vs Sandbox Compare Baseline

Implemented for `0.4.0`:

- dedicated compare surface for configured real Mods vs sandbox Mods
- baseline drift categories:
  - only in real
  - only in sandbox
  - same version
  - version mismatch
  - ambiguous match
- compare is intentionally visibility-first in this stage (no compare-driven write behavior)

#### 8. Backup Bundle Inspection + Restore/Import Planning Baseline

Implemented for `0.5.0` / `0.6.0`:

- explicit local backup export baseline for migration/recovery groundwork
- explicit read-only inspection of exported backup bundle folders
- manifest/version/item-status visibility before any restore behavior exists
- structural usability reporting for future restore/import work
- explicit read-only restore/import planning against the current local machine
- safe later / needs review / blocked planning visibility
- no restore/apply behavior in this baseline

### Next likely phases (real-world usability first)

#### 9. Open-Folder Conveniences

- add explicit local folder-opening actions where they reduce daily friction
- keep these conveniences narrow and workflow-owned

#### 10. Restore/Import Execution Baseline

- ship the first apply path now that restore/import planning is trustworthy
- preserve explicit, reviewable, safety-first semantics

#### 11. Steam Prelaunch Best-Effort Behavior

- pragmatic Steam-aware launch assistance without promising guaranteed automation

#### 12. Compare Follow-up (deferred after baseline ship)

- possible richer compare ergonomics after safety semantics are explicitly approved
- keep baseline compare visibility trustworthy and avoid implicit write shortcuts

### Later planned phase

#### 14. Information Architecture Follow-up

The UI simplification track is now intentionally paused until sandbox-dev workflow trust work is no longer the main blocker.

#### 15. Visual Feedback and Polish

Icon/taskbar refinement remains a lower-priority polish item compared with session, backup/migration, compare, and Steam prelaunch usability.

This phase should happen after the IA simplification decisions are made, not before.

## Current UX/Product Concerns Worth Challenging

An external model should specifically challenge these points:

### A. Is the updated roadmap still in the right order?

The current recommendation is to prioritize real-world usability and trust ergonomics first:

- open-folder convenience
- restore/import execution
- Steam-aware launch reliability
- then broader polish/refactor work

Question:

> Is it correct to keep restore/import trust work and local workflow convenience ahead of more UI consolidation and polish?

### B. Should live promotion stay conservative longer?

Question:

> How conservative should `sandbox -> real` remain now that preview/archive-aware replace exists, and what safeguards should be added before any faster promotion path is considered?

### C. What should remain global vs tab-local?

The app now has:

- a global status strip
- tab-local workflow surfaces
- selected-row guidance in `Inventory`
- a bottom detailed-output surface

Question:

> Which of these should remain, collapse, or be retired?

### D. What is the next best daily-use ergonomics increment?

Question:

> Given that the intended near-term audience includes mod developers and careful local users, what sequence best balances trust and speed: open-folder conveniences first, restore/import execution second, and broader compare/launch conveniences later?

### E. When should multi-package planning be allowed?

Question:

> What review surface and safety constraints would be required before moving from multi-zip batch inspection to a true multi-package staged plan?

## Explicit Constraints for the External Audit

The external audit should respect these repository/product constraints:

- no database unless there is a concrete product need
- no scraping or browser automation for downloads
- no premium-bypass behavior
- sandbox remains the recommended path until live flows are fully validated
- destructive or live-Mods operations require archive/recovery semantics
- product-facing workflow completion is favored over refactor churn
- real->sandbox and sandbox->real are intentionally asymmetric workflows

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
- whether the sandbox dev-loop track is correctly prioritized
- how preview + archive-aware replace should be introduced without weakening live-write trust
- concrete suggestions for improving sandbox-dev ergonomics without weakening real-Mods safety
- criteria for when the app is ready to resume later UI/UX consolidation work
- the next 3-5 smallest safe increments, ordered by product value
