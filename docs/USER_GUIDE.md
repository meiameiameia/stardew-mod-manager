# Cinderleaf User Manual

This guide is the detailed, player-friendly walkthrough for the `1.2.0` release line.

If you just want the short version first, start with the main [README](../README.md).

## 1. What Cinderleaf is meant to help with

Cinderleaf is for players who want an easier, more organized mod routine on Windows, whether they only install a few favorites, keep several themed setups, or build and test mods more actively.

At its best, it helps you:

- look at mods before you install them
- let the watcher pick up downloaded zip files for you
- queue and install several mods together
- keep different mod sets through profiles instead of manual folder juggling
- keep backup and recovery tools nearby
- export the parts of your setup you care about before a bigger change
- compare folders without turning compare into a write action
- use sandbox and testing workflows when you want a dedicated trial space, especially for heavier experimentation or mod-author work

The app can work with your real `Mods` folder, a sandbox `Mods` folder, custom profiles, backup bundles, archive history, and recovery/restore workflows. The goal is not to hide what is happening. The goal is to make each step clear before you commit to it.

## 2. First stop: Setup

Open `Setup` first. This is where you tell Cinderleaf where everything lives.

You can configure:

- your game folder
- your real `Mods` folder
- your sandbox `Mods` folder
- your sandbox archive folder
- your real archive folder
- an optional Nexus API key

Best practice:

- keep your paths clear and consistent before you start changing things
- treat the sandbox as an optional but very useful testing area, especially if you experiment a lot or build mods
- keep archive folders configured so rollback stays useful when you need it

`Setup` also includes update status, release-page access, backup/export tools, and restore/import tools.

## 3. Library and SMAPI

`Library` is the everyday view for your installed mods, and it is also where the main launch actions live.

Use it when you want to:

- scan what is currently installed
- browse your installed mods
- check update guidance
- look at source intent and promotion context
- archive or restore the selected mod
- work with real or sandbox profiles

`SMAPI` is the companion tab for SMAPI-specific checks and log review.

Use it when you want to:

- open the SMAPI website
- check the installed SMAPI version
- check the latest SMAPI log
- open the latest SMAPI log file itself
- handle SMAPI-specific troubleshooting details

Use `Library` when you want the main launch actions:

- launch the game normally
- launch with SMAPI
- run a sandbox test launch

Important note:

- scanning and update guidance are read-only
- actual write actions stay explicit and live in the workflow areas where they belong

## 4. Packages

`Packages` is where downloaded zip files come in.

Instead of browsing for one zip at a time, you point Cinderleaf at one or two download folders and let it watch them.

Typical flow:

1. Set your watched download paths.
2. Start intake watch.
3. Let Cinderleaf detect zips that are already there or appear later.
4. Filter the queue by name or status text.
5. Check the packages you want.
6. Choose `Compare against`.
7. Use `Open Install` to send that batch into `Install`.

The queue status helps you understand what Cinderleaf sees, for example:

- not installed in the selected target
- same version in the selected target
- newer than the selected target

`Packages` is still a review step. It does not write anything by itself.

## 5. Install

`Install` is the planning screen before any files are written.

It receives:

- the package batch you selected in `Packages`
- the destination context inherited from that earlier step

Use it to:

- confirm where the install is going
- review replace behavior
- read plan notes and install detail
- see dependency-aware batch planning results
- apply the install only after the plan looks right

One helpful part of the `1.2.0` workflow is batch dependency handling:

- if a needed dependency is already in the same staged batch, the plan can count it
- if that staged dependency is blocked or invalid, it does not count as safe

The plan stays read-only until Cinderleaf says it is ready to execute.

## 6. Profiles

Cinderleaf supports curated real and sandbox profiles.

The basic idea is:

- `Default` mirrors the main configured library
- custom profiles are smaller, curated sets
- new mods added later to the main library do not silently become enabled in older custom profiles
- if something exists in `Default` but not in the active custom profile, it shows as `not in profile`

That makes profiles useful for:

- alternate mod sets
- lighter testing setups
- preserving an older favorite combination while you try newer mods somewhere else
- keeping a cleaner test setup if you make mods, troubleshoot often, or like heavier experimentation

## 7. Compare

`Compare` is there to help you review differences, not make changes.

Use it to:

- compare real and sandbox folders
- focus on meaningful drift instead of noise
- see cases that are only in real, only in sandbox, mismatched, or ambiguous

If you are looking for a button that makes `Compare` sync things automatically, that is not what this workspace is for. It is intentionally read-only.

## 8. Archive and Recovery

`Archive` is where you can inspect archived copies and restore them deliberately.

Use it to:

- browse what has been archived
- inspect restore targets
- clean up older retained copies when it makes sense

`Recovery` is the rollback side of the story. It uses recorded install/recovery history so you can review what happened before you try to undo it.

Use it to:

- inspect recorded install history
- review whether a recovery path looks safe
- execute recovery only when the review says it is ready

These tools are part of what makes bigger experiments less stressful.

## 9. Backup export

`Export backup` lets you choose what goes into a backup bundle instead of forcing one fixed package.

Current export choices include:

- manager state and profiles
- managed mods and config snapshots
- archives
- optional Stardew save files

Restore/import can already bring back:

- bundled mod folders
- supported mod config artifacts
- exported real and sandbox profile catalogs

Stardew save files are still different. They are exportable for backup, but today they still need manual restore steps.

In plain terms:

- export is your wider backup surface
- restore/import can already handle the guided mod/config/profile part of that surface
- save files are still the manual piece

## 10. Restore / import

Use `Inspect backup` and the related restore tools when you want to review a bundle before anything is written.

The expected posture is:

- inspect first
- plan first
- execute only after you have reviewed the result

Restore/import is archive-aware and folder-oriented. It is not meant to be a fine-grained merge tool.

Today that means:

- bundled mods can be restored
- supported mod config artifacts can be restored
- exported real and sandbox profile catalogs can be restored
- Stardew save files are still a manual restore step

## 11. Troubleshooting

If something goes wrong, try to collect:

- your Cinderleaf version
- your Windows version
- which workspace you were using
- the status text or error message the app showed
- the install, archive, or recovery summary if it is relevant

For SMAPI issues in particular:

- check the latest SMAPI log from the `SMAPI` tab
- open the log file if needed
- note whether the issue happened in real `Mods`, sandbox `Mods`, or a profile-backed launch

That makes bug reports much easier to understand and fix.

## 12. A few habits that make life easier

- use the sandbox when you want a dedicated testing space before touching live `Mods`, especially if you build mods or experiment heavily
- keep archive folders configured
- export backups before big cleanup passes, experiments, or moving to another machine
- use profiles for curated sets instead of trying to remember manual folder edits
- treat `Compare` as a review surface
- let `Install` be your last quiet checkpoint before any write happens

## 13. Current boundaries

Right now, it helps to remember:

- downloads are still manual
- `Compare` is still read-only
- restore/import is not a full catch-all restore for every exported artifact
- there is no one-click `sync everything back to real` button
- Windows is the primary supported desktop path
