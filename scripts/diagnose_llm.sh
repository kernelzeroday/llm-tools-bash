#!/usr/bin/env bash
# Quick checks when `llm -T bash ...` prints nothing or exits immediately.
set +e
_llm_merge() {
  python3 -c "
import subprocess, sys
sec = int(sys.argv[1])
cmd = sys.argv[2:]
try:
    r = subprocess.run(cmd, timeout=sec, capture_output=True, text=True)
    sys.stdout.write((r.stdout or '') + (r.stderr or ''))
    raise SystemExit(r.returncode)
except subprocess.TimeoutExpired:
    sys.stderr.write('(timed out after %ds)\n' % sec)
    raise SystemExit(124)
" "$@"
}
echo "== llm executable =="
command -v llm || echo "(llm not on PATH)"
echo ""
echo "== default model (llm models default) =="
llm models default 2>&1
echo ""
echo "== one-line prompt (stdout+stderr merged; 20s cap) =="
out=$(_llm_merge 20 llm -n "Reply with exactly: ok" 2>&1) || true
echo "$out" | head -30
echo ""
if echo "$out" | grep -q "Unknown model"; then
  echo ">> Detected Unknown model: fix with  llm models default <id>   (see: llm models ; ollama list)"
fi
if echo "$out" | grep -qi "needs.*key\|API key\|401\|403"; then
  echo ">> API key / auth issue: configure keys for your provider (llm keys set …)"
fi
echo ""
echo "== optional: echo model + bash tool (8s cap) =="
_llm_merge 8 llm -m echo -n -T bash --td "run: date" 2>&1 | head -25 || echo "(echo+tools failed or timed out — known flaky in some setups)"
echo ""
echo "Done."
