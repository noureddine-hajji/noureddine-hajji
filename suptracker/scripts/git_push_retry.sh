#!/usr/bin/env bash
# Push the commit a workflow just made, even when another workflow pushed to the same branch in between (audit PR A, 2026-11-24).
#
# On 2026-11-23 the warehouse rebuild was rejected (« fetch first »): the official calendar fetch had pushed to main a few minutes
# earlier, the rebuild never reached main, and main kept a warehouse older than its own open-day files (red team J9 red on main
# and on every PR). Every workflow that commits to the repository now pushes through this script:
#   - fetch the branch, replay our commit(s) on top (rebase), push;
#   - on a rejected push (someone pushed meanwhile), try again, up to ATTEMPTS times with a growing wait;
#   - a real conflict (the same file changed on both sides) aborts the rebase and FAILS: never a force-push, never a merge that
#     hides a conflict. Workflows write disjoint paths, so this only happens if two runs of the same workflow overlap.
#
# Usage: bash scripts/git_push_retry.sh [branch]   (default: the current branch)
set -u
branch="${1:-$(git rev-parse --abbrev-ref HEAD)}"
attempts="${GIT_PUSH_ATTEMPTS:-5}"
for i in $(seq 1 "$attempts"); do
  if ! git fetch --quiet origin "$branch"; then
    echo "fetch failed (attempt $i/$attempts)"
  elif ! git rebase --quiet "origin/$branch"; then
    git rebase --abort 2>/dev/null || true
    echo "::error::our commit conflicts with what was pushed to $branch meanwhile: not pushed (no force-push)"
    exit 1
  elif git push --quiet origin "HEAD:$branch"; then
    echo "pushed to $branch (attempt $i/$attempts)"
    exit 0
  else
    echo "push rejected (attempt $i/$attempts): another workflow pushed meanwhile, trying again"
  fi
  sleep $(( i * ${GIT_PUSH_WAIT:-5} ))
done
echo "::error::could not push to $branch after $attempts attempts"
exit 1
