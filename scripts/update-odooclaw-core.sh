#!/usr/bin/env bash
set -euo pipefail

# Update the vendored OdooClaw core subtree from upstream.
#
# The upstream repository root contains more than the Go core. This Doodba
# repository vendors only upstream `odooclaw/` at local `./odooclaw`, so the
# update flow splits that directory first, sanitizes files that must not be
# vendored, then pulls the sanitized split as a subtree.

REMOTE_NAME="${ODOOCLAW_CORE_REMOTE:-odooclaw-core}"
REMOTE_URL="${ODOOCLAW_CORE_URL:-https://github.com/nicolasramos/odooclaw.git}"
REMOTE_BRANCH="${ODOOCLAW_CORE_BRANCH:-main}"
SPLIT_BRANCH="${ODOOCLAW_CORE_SPLIT_BRANCH:-nr/odooclaw-core-dir-sanitized-for-doodba}"
PREFIX="odooclaw"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree has local modifications. Commit or stash them before updating OdooClaw core." >&2
  exit 1
fi

if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "Working tree has untracked files. Commit, ignore, or stash them before updating OdooClaw core." >&2
  git ls-files --others --exclude-standard >&2
  exit 1
fi

if ! git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  git remote add "$REMOTE_NAME" "$REMOTE_URL"
fi

git fetch "$REMOTE_NAME" "$REMOTE_BRANCH"
git branch -D "$SPLIT_BRANCH" >/dev/null 2>&1 || true

git subtree split \
  --prefix="$PREFIX" \
  -b "$SPLIT_BRANCH" \
  "$REMOTE_NAME/$REMOTE_BRANCH"

# Sanitize the split before vendoring it into Doodba. Do not bypass this:
# GitHub push protection rejects OAuth literals, and build artifacts do not
# belong in this deployment repository.
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --tree-filter '
rm -rf build
python3 - <<"PY"
from pathlib import Path
import re

path = Path("pkg/auth/oauth.go")
if path.exists():
    text = path.read_text()
    text = text.replace(
        "// Client credentials are the same ones used by OpenCode/pi-ai for Cloud Code Assist access.\\n",
        "// Client credentials must be provided by deployment configuration.\\n",
    )
    text = re.sub(
        r"\t// These are the same client credentials used by the OpenCode antigravity plugin\.\n"
        r"\tclientID := decodeBase64\(\n\t\t\"[^\"]+\",\n\t\)\n"
        r"\tclientSecret := decodeBase64\(\"[^\"]+\"\)",
        "\tclientID := os.Getenv(\"ODOOCLAW_GOOGLE_OAUTH_CLIENT_ID\")\n"
        "\tclientSecret := os.Getenv(\"ODOOCLAW_GOOGLE_OAUTH_CLIENT_SECRET\")",
        text,
    )
    path.write_text(text)
PY
' -- "$SPLIT_BRANCH"

git subtree pull \
  --prefix="$PREFIX" \
  . "$SPLIT_BRANCH" \
  --squash \
  -m "chore: update OdooClaw core subtree"

cat <<MSG

OdooClaw core subtree updated.

Review before pushing:
  git status --short
  git log --oneline -n 5

Preserved project-specific files, such as odooclaw/config/config.json, should remain local to this Doodba repo.
MSG
