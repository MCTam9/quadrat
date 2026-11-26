#!/usr/bin/env bash
# Vercel "ignored build step": exit 0 skips the build, exit 1 builds.
# Skips when every file changed since the last successful deployment is one the app never ships:
# docs, tests, CI config. Anything else, or any doubt (no previous deploy, history too shallow), builds.
set -u
prev="${VERCEL_GIT_PREVIOUS_SHA:-}"
head="${VERCEL_GIT_COMMIT_SHA:-HEAD}"
cd "$(git rev-parse --show-toplevel)" || exit 1
[ -n "$prev" ] && git cat-file -e "$prev^{commit}" 2>/dev/null || { echo "No previous deploy to compare: building."; exit 1; }
changed=$(git diff --name-only "$prev" "$head") || exit 1
deployable=$(printf '%s\n' "$changed" | grep -vE '^(tests/|docs/|\.github/|LICENSE$|\.gitignore$)|\.md$|\.test\.tsx?$' | grep -v '^$')
if [ -z "$deployable" ]; then
  echo "Only docs, tests or CI changed since ${prev:0:7}: skipping build."
  exit 0
fi
echo "Deployable changes since ${prev:0:7}:"; printf '  %s\n' $deployable | head -20
exit 1
