# ARCHITECT_NOTES.md

Project name: `Cinderleaf / stardew-mod-manager`

Current stage: `READY_FOR_FIRST_INCREMENT`

Last gate decision: `PASSED - bootstrap framework files now preserve the required contracts and AGENTS.md is usable as the project source of truth`

## Known risks

- This is a Windows desktop app, so future UI/path changes still require manual validation in addition to tests.
- Portable packaging and startup/path behavior remain high-coupling surfaces.
- There is still no dedicated architecture document beyond AGENTS/notes, so durable technical decisions must be recorded here consistently.

## Locked decisions

- Architect / Executor / Human three-party workflow is mandatory for this repo.
- Human approval is required before every dispatch.
- `AGENTS.md` is the project-local source of truth for the workflow.
- The exact handoff format and exact gate criteria are locked and must not change without human approval.
- Stabilize before expanding is the default posture for this repo.

## Open questions for human
