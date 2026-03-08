# Proposed Repository Structure

## Folders

- `docs/`
  - planning artifacts, architecture notes, ADRs later
- `src/sdvmm/`
  - application source package
- `tests/`
  - unit and integration tests
- `scripts/`
  - maintenance and developer utility scripts later
- `fixtures/`
  - sample manifests, archives, and SMAPI logs later
- `artifacts/`
  - local generated outputs later, ignored from version control

## Responsibilities

### `docs/`

- Exists now.
- Holds the PRD, architecture note, stage plan, and repository structure note.
- Later should also hold ADRs and packaging notes.

### `src/sdvmm/`

- Exists now as an empty package root placeholder.
- Later should contain:
  - `app/`
  - `domain/`
  - `services/`
  - `infra/`
  - `ui/`
  - `diagnostics/`

### `tests/`

- Exists now as an empty test root placeholder.
- Later should contain:
  - unit tests for manifest parsing and domain rules
  - integration tests for scan, install staging, rollback, and profile switching

### `scripts/`

- Does not need to exist yet.
- Later may hold developer scripts for fixture generation, packaging, and local QA runs.

### `fixtures/`

- Does not need to exist yet.
- Later should contain sanitized sample mods, sample archives, and SMAPI logs for deterministic tests.

### `artifacts/`

- Should not exist in version control.
- Reserved for local outputs such as snapshots, temporary extraction, or test run outputs.

## What should exist now

- `README.md`
- `.gitignore`
- `docs/`
- `src/sdvmm/`
- `tests/`

## What should exist later

- `pyproject.toml` after stack approval
- `src/sdvmm/app/`
- `src/sdvmm/domain/`
- `src/sdvmm/services/`
- `src/sdvmm/infra/`
- `src/sdvmm/ui/`
- `src/sdvmm/diagnostics/`
- `tests/unit/`
- `tests/integration/`
- `fixtures/`
- `scripts/`
