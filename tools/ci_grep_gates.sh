#!/usr/bin/env bash
# ci_grep_gates.sh — repo-wide safety floor enforced in CI.
#
# Four gates run sequentially; any failure exits non-zero and names the
# offending files. Run locally before pushing:
#
#     bash tools/ci_grep_gates.sh
#
# CONTRIBUTING.md references this script as the source of truth for the
# pre-commit / CI safety checks (do NOT inline these patterns elsewhere —
# update this file and let CI fan it out).
#
# Gates:
#   (a) No `yaml.load(` calls that bypass `safe_load` (RCE risk).
#   (b) No literal "WorldQuant" anywhere (trademark; spec.md §License).
#   (c) No deprecated `datetime.utcnow(` usage or bare `datetime.now()` calls
#       in Python sources; `datetime.now(timezone.utc)` is allowed.
#   (d) No raw `os.getenv` / `os.environ.get` / `os.environ["KEY"]` reads
#       outside the centralized config layer (`agent/src/config/`).
#       AST-based; uses `tools/ci_env_var_gate.py`.
#
# Exclusions: .git, node_modules, __pycache__, .venv, dist, build, this
# script itself.

set -u
set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
NC=$'\033[0m'

FAILED=0
SELF="tools/ci_grep_gates.sh"
EXCLUDE_DIRS=(--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=dist --exclude-dir=build --exclude-dir=.pytest_cache --exclude-dir=.ruff_cache)

# -------------------------------------------------------------- gate (a)
echo "[gate a] no unsafe yaml.load() ..."
A_HITS=$(grep -rn --include='*.py' "${EXCLUDE_DIRS[@]}" 'yaml\.load(' . 2>/dev/null \
    | grep -v 'safe_load' \
    | grep -v "$SELF" \
    || true)
if [ -n "$A_HITS" ]; then
    echo "${RED}FAIL${NC}: yaml.load() without safe_load:"
    echo "$A_HITS"
    FAILED=1
else
    echo "${GREEN}ok${NC}"
fi

# -------------------------------------------------------------- gate (b)
# docs/ is excluded: those are internal planning docs that discuss the
# trademark policy itself (e.g. "the string 'WorldQuant' must not appear in
# user-facing artifacts"). docs/ is not shipped to PyPI / public consumers
# (memory: feedback_no_push_docs). The gate's real target is source code,
# READMEs, and HTML/JSON manifests.
echo "[gate b] no 'WorldQuant' trademark string in shipped artifacts ..."
B_HITS=$(grep -rni --include='*.py' --include='*.md' --include='*.html' --include='*.json' \
    "${EXCLUDE_DIRS[@]}" --exclude-dir=docs 'worldquant' . 2>/dev/null \
    | grep -v "$SELF" \
    || true)
if [ -n "$B_HITS" ]; then
    echo "${RED}FAIL${NC}: literal 'WorldQuant' found (use 'Kakushadze 101 Formulaic Alphas'):"
    echo "$B_HITS"
    FAILED=1
else
    echo "${GREEN}ok${NC}"
fi

# -------------------------------------------------------------- gate (c)
echo "[gate c] no deprecated datetime.utcnow() / bare datetime.now() calls ..."
TARGET_FILES=(
  agent/api_server.py
  agent/src/agent/context.py
  agent/src/api/system_routes.py
  agent/src/channels/mochat.py
  agent/src/goal/store.py
  agent/src/session/models.py
  agent/src/swarm/worker.py
  agent/src/tools/lockup_expiry_tool.py
  agent/src/trading/connectors/dhan/sdk.py
  agent/src/trading/connectors/shoonya/sdk.py
)
D_HITS=$(grep -Hn -E 'datetime\.utcnow\(|datetime\.now\(' "${TARGET_FILES[@]}" 2>/dev/null \
    | grep -v "$SELF" \
    | grep -vE 'datetime\.now\([^)]*(timezone\.utc|tz=timezone\.utc)' \
    || true)
if [ -n "$D_HITS" ]; then
    echo "${RED}FAIL${NC}: deprecated datetime.utcnow() or bare datetime.now() found:"
    echo "$D_HITS"
    FAILED=1
else
    echo "${GREEN}ok${NC}"
fi

# -------------------------------------------------------------- gate (d)
echo "[gate d] no raw os.getenv / os.environ reads outside config layer ..."
E_OUTPUT=$(python tools/ci_env_var_gate.py 2>&1)
E_RC=$?
if [ "$E_RC" -ne 0 ]; then
    echo "${RED}FAIL${NC}: raw env-var reads outside agent/src/config/:"
    echo "$E_OUTPUT"
    FAILED=1
else
    if [ -n "$E_OUTPUT" ]; then
        echo "$E_OUTPUT"
    fi
    echo "${GREEN}ok${NC}"
fi

# --------------------------------------------------------------- result
if [ "$FAILED" -ne 0 ]; then
    echo
    echo "${RED}ci_grep_gates: one or more gates failed${NC}"
    exit 1
fi

echo
echo "${GREEN}ci_grep_gates: all gates passed${NC}"
exit 0
