#!/usr/bin/env bash
# M9.0 baseline: run the small and hard benchmark suites against the Ornith llama-server and save the
# results in docs/. Refuses to start when the server or the machine is not in the reference setup, so the
# numbers stay comparable with M7. Usage: scripts/m9_baseline.sh [small_reps] [hard_reps]
set -euo pipefail

SMALL_REPS="${1:-3}"
HARD_REPS="${2:-3}"
BASE_URL="${ZC_BASE_URL:-http://127.0.0.1:8080/v1}"
MODEL="${ZC_MODEL:-ornith-1.5-9b-q5-k-m}"
LABEL="${ZC_LABEL:-ornith-1.5-9b-q5-k-m}"
ROOT="${BASE_URL%/v1}"
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then RUN=(uv run python); else RUN=(.venv/bin/python); fi

fail() { echo "preflight failed: $*" >&2; exit 1; }

curl -fsS -m 5 "$ROOT/health" >/dev/null || fail "no llama-server answering at $ROOT (start it with the command in README.md, 'Start Ornith')"
python3 - "$ROOT" "$MODEL" <<'PY' || exit 1
import json, sys, urllib.request
root, model = sys.argv[1], sys.argv[2]
props = json.load(urllib.request.urlopen(root + "/props", timeout=5))
alias = props.get("model_alias") or props.get("model_path")
n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
slots = props.get("total_slots")
problems = []
if alias != model:
    problems.append(f"alias is {alias!r}, expected {model!r}")
if n_ctx != 8192:
    problems.append(f"n_ctx is {n_ctx}, expected 8192 (the M7 configuration)")
if slots != 1:
    problems.append(f"total_slots is {slots}, expected 1 (-np 1)")
if problems:
    sys.exit("preflight failed: " + "; ".join(problems))
print(f"server ok: alias={alias} n_ctx={n_ctx} slots={slots}")
PY

avail_mb=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
[ "$avail_mb" -ge 1500 ] || fail "only ${avail_mb} MB of RAM available; close other programs first"
echo "ram available: ${avail_mb} MB"

stamp="$(date +%Y%m%d)"
echo "== small suite x${SMALL_REPS}"
"${RUN[@]}" scripts/m7_bench.py --suite small --label "$LABEL" --model "$MODEL" --base-url "$BASE_URL" \
  --repetitions "$SMALL_REPS" --streaming --output "docs/m9-baseline-${LABEL}-small-${stamp}.json" || true
echo "== hard suite x${HARD_REPS}"
"${RUN[@]}" scripts/m7_bench.py --suite hard --label "$LABEL" --model "$MODEL" --base-url "$BASE_URL" \
  --repetitions "$HARD_REPS" --streaming --output "docs/m9-baseline-${LABEL}-hard-${stamp}.json" || true
echo "done: docs/m9-baseline-${LABEL}-{small,hard}-${stamp}.json"
