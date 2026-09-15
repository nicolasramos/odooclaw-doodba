# Updating OdooClaw core in this Doodba project

This repository keeps two upstreams aligned:

| Area            | Source                                            | Update command                    |
| --------------- | ------------------------------------------------- | --------------------------------- |
| Doodba scaffold | `Tecnativa/doodba-copier-template`                | `copier update`                   |
| OdooClaw core   | `nicolasramos/odooclaw`, subdirectory `odooclaw/` | `scripts/update-odooclaw-core.sh` |

## Quick path

1. Start from a clean working tree.
2. Run:

   ```bash
   scripts/update-odooclaw-core.sh
   ```

3. Review the diff before pushing:

   ```bash
   git status --short
   git diff --stat origin/18.0...HEAD
   ```

## Why subtree, not submodule

`odooclaw/` is a `git subtree` because the Doodba deployment should stay self-contained.
That avoids fragile clone flows where Docker, CI, or a teammate forgets to initialize
submodules.

## Sanitized vendoring

The update script sanitizes the upstream split before vendoring it:

- `build/` artifacts are removed.
- Google OAuth client literals are replaced with deployment-provided environment
  variables.

Do not bypass this step. GitHub push protection rejects the raw upstream literals, and
build artifacts do not belong in this deployment repository.

## Important rule

Do not manually copy the OdooClaw core into this repository. Use the update script.
Manual copies hide where changes came from and make future updates harder to review.

Project-specific runtime files can still live in this repo. For example,
`odooclaw/config/config.json` is intentionally preserved here and is not part of the
upstream core subtree.
