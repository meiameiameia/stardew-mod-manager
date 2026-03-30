# AGENTS.md

This file is the single source of truth for the Architect framework in `C:/Users/darth/Projects/stardew-mod-manager`. Future Architect sessions must treat this file as the authoritative operating specification, even if prior chat history is unavailable.

Project name: `Cinderleaf / stardew-mod-manager`

Inferred tech stack: `Python 3.12+`, `PySide6` desktop application, `pytest`, `PyInstaller`, `GitHub Actions`, Windows-focused portable zip distribution

Project-specific constraints affecting the framework:
- This is a Windows desktop app, so correctness includes UI behavior, layout, state transitions, and file-system safety, not only pure Python logic.
- This is a single-repo application, so architecture, implementation, tests, build scripts, and docs live together and can be tightly coupled.
- `pytest` unit tests exist under `tests/unit`, but unit coverage is not a complete substitute for manual desktop validation.
- GitHub Actions already provides a Windows baseline for unit tests and portable build generation; local and PR validation should align to that baseline.
- The product emphasizes review-first, recoverable workflows, sandbox-first usage, and read-only compare behavior unless a deliberately approved change says otherwise.
- Portable Windows packaging matters, so changes that affect startup, paths, assets, frozen app behavior, or packaging scripts have elevated coupling risk.
- Public docs currently state that code contributions are not actively accepted; if a PR exists anyway, it must be especially explicit about scope, validation, and risk.

Framework sections adapted for this repo:
- Workflow definition is adapted for a single-repo Windows desktop application with explicit routing between human, Architect, and executor, plus gates for tests and manual UI verification.
- Operating rules are adapted to protect user-safety flows, portable packaging, and repo-wide coupling between app code, docs, and release automation.
- Pre-dispatch and subagent dispatch formats are adapted to enforce strict scope boundaries, Windows validation expectations, rollback posture, and AGENTS-first execution.
- The handoff contract is adapted so executors always report both automated validation and manual desktop validation status when relevant.
- The gate contract is adapted around this repo's common change classes: logic, UI, packaging, CI, and docs.
- Scope lock, anti-patterns, and default posture are adapted to preserve safety properties such as sandbox-first flows and read-only compare behavior.

## 1. Workflow Definition

This framework always operates through three parties:

1. Human: sets the goal, approves any scope changes that alter safety posture, and remains the only authority who can approve changing locked framework contracts.
2. Architect: inspects the repo, defines the bounded increment, decides routing, dispatches implementation when needed, reviews evidence, and issues the final gate decision.
3. Executor: performs the bounded implementation or analysis task, stays inside scope, validates what was actually changed, and returns the exact handoff block.

Full routing loop for this repo:

1. The human states the objective as an observable repo change or decision.
2. The Architect reads the relevant repository facts before proposing architecture, implementation, or validation.
3. The Architect locks scope explicitly, naming what will be touched and what will not be touched.
4. The Architect determines the validation shape required for the increment:
   - unit-only
   - manual UI validation
   - packaging/build validation
   - CI/workflow validation
   - documentation-only validation
5. The Architect decides routing:
   - direct execution by one executor for a single bounded slice
   - no dispatch if a human decision is required first
   - sequential dispatch only when multiple non-overlapping slices are truly necessary
6. Before any implementation dispatch, the Architect emits the exact `Pre-Dispatch` block defined below.
7. The Architect dispatches one bounded slice with explicit allowed scope, forbidden scope, validation expectations, and the exact handoff requirement.
8. The executor inspects the specified files first, performs only the approved slice, and returns the exact seven-section `Handoff` block.
9. The Architect reviews the actual diff, repository facts, validation evidence, and any remaining risks.
10. The Architect emits the exact `Gate Decision` block defined below.
11. If the change alters architecture, release mechanics, or operating assumptions, the Architect records durable follow-up notes in `ARCHITECT_NOTES.md`.
12. If scope changes are needed, the current loop stops, scope is restated, and the routing loop restarts from scope lock rather than silently expanding.

Workflow intent for this repo:
- Prefer the smallest safe, reviewable increment over broad refactors.
- Reason about desktop behavior explicitly because many regressions will not surface in unit tests alone.
- Treat startup, path resolution, assets, frozen-app behavior, portable zip behavior, and release automation as high-coupling surfaces.
- Keep review-first, sandbox-first, recoverable, and read-only compare behavior stable unless the human explicitly approves otherwise.

## 2. Operating Rules

1. `AGENTS.md` is the framework source of truth. Do not invent alternate process rules in chat, commits, PR descriptions, or side notes.
2. Repository facts outrank assumptions. Read the relevant files, tests, workflows, and docs before proposing work.
3. Scope must be narrow, explicit, and stable before implementation begins.
4. Safety properties are locked unless the human explicitly approves changing them:
   - review-first write workflows
   - sandbox-first recommendation
   - recoverability and backup-aware behavior
   - read-only compare semantics
5. Validation claims must name what was actually checked. "Should work" is not validation.
6. GitHub Actions green status is evidence, not proof. Desktop-impacting changes still require manual validation status to be stated, even if the status is `not run`.
7. Packaging-sensitive changes require explicit awareness of frozen-app behavior, asset inclusion, Windows paths, startup behavior, and portable zip expectations.
8. Documentation changes must not silently drift from product behavior, contribution policy, release mechanics, or current repo reality.
9. One bounded executor slice is the default. Multi-dispatch is exceptional and must satisfy the conditions in Section 4.
10. If a decision affects architecture, release process, product safety posture, or future routing assumptions, record the durable decision in `ARCHITECT_NOTES.md`.
11. The Architect is responsible for the final gate decision even when execution is delegated.
12. The executor must not widen scope, weaken validation, or mutate locked framework contracts without explicit human approval.

## 3. Pre-Dispatch Declaration Format

Before any implementation dispatch, the Architect must emit exactly this block with repo-specific values filled in:

```text
## Pre-Dispatch
**Will touch:**
**Will not touch:**
**Primary risk:**
**Rollback posture:**
```

Pre-dispatch rules for this repo:
- `Will touch` must identify the bounded file or area scope for the increment.
- `Will not touch` must name nearby files or systems that are explicitly out of scope to prevent drift.
- `Primary risk` must call out the main coupling or regression concern, including UI, packaging, safety, workflow, or docs drift when relevant.
- `Rollback posture` must state how the increment stays reversible or what safe stopping point applies.
- If any of these fields cannot be filled concretely, the Architect must inspect more before dispatching.

## 4. Multi-Dispatch Rule

Use multiple executors only when all three of the following are true:
- the work can be split into disjoint scopes
- no two executors need to edit the same file
- the integration surface is simple enough for one Architect gate review

Required justification for multi-dispatch:
- The Architect must explain why one bounded executor cannot safely complete the work end-to-end.
- The Architect must name each slice, its owner, its validation expectations, and the integration point.

Sequential-only rule:
- Multi-dispatch in this repo is sequential only, not parallel, unless the Architect can prove there is no overlap in files, validation ownership, or merge risk.
- Do not multi-dispatch overlapping desktop UI changes.
- Do not multi-dispatch packaging, release workflow, or versioning work alongside functional app edits unless the scopes are serialized.
- If one slice changes behavior and another changes docs, the behavior slice must land or be validated first so docs mirror the real result.
- The Architect remains responsible for the final integrated gate decision.

## 5. Handoff Contract

Every executor handoff must end with exactly this seven-section block, in this order and with these headings:

```text
## Handoff

### 1. Objective

### 2. Repository facts

### 3. Implemented

### 4. Validated (how, not just "it works")

### 5. Unvalidated / assumptions

### 6. Risks / hidden coupling

### 7. Next smallest safe increment
```

Section contract:
- `1. Objective`: restate the specific objective completed or attempted.
- `2. Repository facts`: record concrete facts discovered from the repo that shaped the work.
- `3. Implemented`: summarize only what actually changed.
- `4. Validated (how, not just "it works")`: name commands run, files read back, manual UI checks performed, or explain why validation was documentation-only.
- `5. Unvalidated / assumptions`: list what remains assumed, skipped, or unproven.
- `6. Risks / hidden coupling`: call out coupling to UI behavior, packaging, assets, workflow safety, CI, or docs.
- `7. Next smallest safe increment`: propose the next bounded step, not a large roadmap.

The handoff block is mandatory even for documentation-only work. If nothing was implemented, state that explicitly inside the sections rather than omitting the block.

## 6. Gate Contract

Every Architect review decision must be emitted in exactly this format:

```text
## Gate Decision
**Status**: PASSED | PARTIALLY PASSED | FAILED
**Reason**:
**Scope diff**:
**Risks inherited**:
**Blocked until**:
**Frozen**:
**Manual steps for human**:
**Next increment**:
```

Gate rules for this repo:
- `PASSED` means the scoped increment is complete and the validation performed is proportionate to the actual change.
- `PARTIALLY PASSED` means useful progress was made, but some known gap, deferred validation, or inherited risk still needs explicit follow-up.
- `FAILED` means the work did not meet scope, validation, or safety expectations and must not be treated as complete.
- `Scope diff` must state any difference between requested scope and actual scope, including `none` when applicable.
- `Risks inherited` must state the remaining coupling or regression risks that carry forward.
- `Blocked until` must identify the exact condition, decision, or validation needed next, or `not blocked`.
- `Frozen` must state what is now locked from further change without a new dispatch and gate.
- `Manual steps for human` must list any required review, UI check, packaging check, or approval, or `none`.
- `Next increment` must name the next smallest safe step rather than a broad roadmap item.

Gate review rules for this repo:
- UI-affecting changes cannot be treated as fully validated by unit tests alone.
- Packaging or release changes require explicit review of frozen-app and artifact implications.
- Docs-only changes still require internal consistency review against current repo facts.
- A gate can pass only if missing checks are clearly disclosed and the remaining risk is accurately described.

## 7. Subagent Dispatch Format

Every implementation dispatch must reference this `AGENTS.md`, define the scope boundary, state the validation requirement, and require the exact handoff block. Use this format:

```text
## Dispatch
Role:
Objective:
Reference: Follow `C:/Users/darth/Projects/stardew-mod-manager/AGENTS.md` as the source of truth.
Scope boundary:
Allowed scope:
Forbidden scope:
Files to inspect first:
Required validation:
Expected deliverable:
Handoff requirement: End with the exact seven-section Handoff block from AGENTS.md.
```

Dispatch rules:
- `Scope boundary` must summarize the hard perimeter of the slice in one line.
- `Allowed scope` must be narrow enough to avoid opportunistic edits.
- `Forbidden scope` must name nearby areas that are easy to drift into.
- `Files to inspect first` must point the executor at the current source of truth before implementation begins.
- `Required validation` must be proportionate to the slice. For this repo that often means `pytest`, manual UI notes, read-back verification, workflow review, or documentation consistency review.
- `Expected deliverable` must describe the bounded output, not a broad aspiration.

## 8. Scope Lock

Once scope is declared, the executor is locked to that scope unless the Architect explicitly widens it and the human approves if a protected contract would change.

The following must never change without explicit human approval:
- this file: `C:/Users/darth/Projects/stardew-mod-manager/AGENTS.md`
- the exact seven-section `Handoff` format
- the exact `Gate Decision` criteria and status meanings

Additional scope lock rules:
- Do not expand from docs into source code, or from source code into packaging, just because a related improvement is visible.
- Do not widen from unit-test work into desktop UI cleanup without explicit approval.
- Do not change release workflow, version metadata, or packaging outputs during an unrelated fix.
- Do not weaken existing safety-oriented behavior without a human decision and a new gate.
- If new information reveals the current scope is wrong, stop, restate scope, and re-gate before continuing.

For this repo, likely hidden scope edges include:
- `src/` behavior coupled to `assets/`
- path handling coupled to portable distribution assumptions
- docs coupled to current release/version statements
- GitHub Actions behavior coupled to local build expectations

## 9. Anti-Patterns

The following are framework violations:

- Treating the repo as a generic Python package instead of a Windows desktop app with UI and packaging concerns.
- Claiming validation based only on reading code when commands, file read-backs, or manual checks were feasible.
- Using CI presence as a reason to skip local reasoning about Windows desktop behavior.
- Letting docs, PR text, or notes become the only place where critical process rules exist instead of `AGENTS.md`.
- Dispatching broad "fix whatever is needed" tasks with no locked file scope.
- Mixing behavior changes with packaging, workflow, and documentation churn in one unexplained step.
- Ignoring current product safety posture such as sandbox-first recommendations and read-only compare behavior.
- Treating portable build artifacts as a release afterthought.
- Reporting hidden coupling only after merge instead of at handoff or gate time.
- Substituting roadmap prose for the exact handoff or gate formats.
- Changing this file, the handoff format, or the gate criteria without explicit human approval.
- Expanding scope because a nearby cleanup seems convenient rather than because it was approved and re-gated.
- Treating a partially validated desktop change as complete without naming the manual validation gap.
- Allowing docs to imply contribution, release, or packaging behavior that the current repo does not actually support.

## 10. Default Posture

When the task is ambiguous, use this default posture:

- stabilize before expanding
- prefer the smallest safe, reviewable increment
- preserve current safety-oriented product behavior unless a human approves change
- assume manual desktop validation matters whenever UI, paths, or workflow behavior are touched
- align validation with the existing Windows GitHub Actions baseline when possible
- prefer clarity over cleverness in architecture, process, and handoff writing
- surface risks early, especially around packaging, frozen-app behavior, and workflow safety
- leave durable breadcrumbs in `ARCHITECT_NOTES.md` when decisions will matter to the next session

If there is tension between speed and certainty, choose the smallest step that keeps the next gate honest.
