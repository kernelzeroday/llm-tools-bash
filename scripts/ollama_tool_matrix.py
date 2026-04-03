"""Query Ollama for each local model's capabilities and optionally smoke-test llm + bash tool."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass


@dataclass
class Row:
    name: str
    size: int
    capabilities: list[str]
    llm_registers: bool
    llm_supports_tools: bool


def _api_tags() -> list[dict]:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags") as r:
        return json.load(r)["models"]


def _api_show(name: str) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/show",
        data=json.dumps({"name": name}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def _llm_same_as_plugin(caps: list[str]) -> tuple[bool, bool]:
    """Mirror llm_ollama.register_models: skip if no completion; supports_tools iff 'tools' in caps."""
    if "completion" not in caps:
        return False, False
    return True, "tools" in caps


def _smoke_llm(model: str, timeout: int) -> tuple[str, int]:
    prompt = (
        "You MUST invoke the bash tool exactly once. Use command "
        "string: printf OKTOOLS\\n"
    )
    cmd = [
        "llm",
        "-m",
        model,
        "-n",
        "--no-stream",
        "--cl",
        "8",
        "-T",
        "bash",
        "--td",
        prompt,
    ]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (p.stdout or "") + (p.stderr or "")
        return out, p.returncode
    except subprocess.TimeoutExpired:
        return "(timeout)", 124


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--smoke-llm",
        action="store_true",
        help="Run llm -T bash per model that advertises tools (slow).",
    )
    ap.add_argument(
        "--smoke-timeout",
        type=int,
        default=90,
        help="Seconds per llm smoke (default 90).",
    )
    ap.add_argument(
        "--json-out",
        type=str,
        default="",
        help="Write machine-readable results to this path.",
    )
    ap.add_argument(
        "--only",
        type=str,
        default="",
        help="If set, only smoke-test models whose name matches this regex.",
    )
    args = ap.parse_args()
    only_re = re.compile(args.only) if args.only else None
    tags = _api_tags()
    rows: list[Row] = []
    smoke_results: list[dict] = []
    for m in sorted(tags, key=lambda x: x["name"]):
        name = m["name"]
        size = m.get("size", 0)
        try:
            show = _api_show(name)
            caps = list(show.get("capabilities") or [])
        except Exception as e:
            caps = [f"(error:{e})"]
            reg, st = False, False
        else:
            reg, st = _llm_same_as_plugin(caps)
        rows.append(
            Row(
                name=name,
                size=size,
                capabilities=caps,
                llm_registers=reg,
                llm_supports_tools=st,
            ),
        )
    print("Ollama model capabilities (from /api/show); llm_ollama registers if completion ∈ caps; supports_tools if tools ∈ caps.\n")
    wn = max(len(r.name) for r in rows)
    print(f"{'model':<{wn}}  {'GB':>6}  {'llm':>5}  {'tools':>5}  capabilities")
    for r in rows:
        gb = r.size / (1024**3) if r.size else 0.0
        cstr = ",".join(r.capabilities) if r.capabilities else ""
        print(
            f"{r.name:<{wn}}  {gb:6.1f}  {str(r.llm_registers):>5}  {str(r.llm_supports_tools):>5}  {cstr}",
        )
    if args.smoke_llm:
        print("\n--- llm smoke: -T bash, expect Tool call: bash and OKTOOLS in output ---\n")
        for r in rows:
            if not r.llm_supports_tools:
                smoke_results.append(
                    {"model": r.name, "skipped": "no tools capability"},
                )
                continue
            if only_re is not None and not only_re.search(r.name):
                smoke_results.append(
                    {"model": r.name, "skipped": "filtered by --only"},
                )
                continue
            out, code = _smoke_llm(r.name, args.smoke_timeout)
            ok_tool = "Tool call:" in out and "bash" in out
            ok_echo = "OKTOOLS" in out
            status = "PASS" if ok_tool and ok_echo else "FAIL"
            if code == 124:
                status = "TIMEOUT"
            smoke_results.append(
                {
                    "model": r.name,
                    "exit": code,
                    "status": status,
                    "saw_tool_call": ok_tool,
                    "saw_OKTOOLS": ok_echo,
                    "head": out[:800],
                },
            )
            print(f"{r.name}: {status} (exit {code}) tool_call={ok_tool} OKTOOLS={ok_echo}")
            if status != "PASS":
                print(out[:1200])
                print("---")
    payload = {
        "rows": [
            {
                "name": r.name,
                "size": r.size,
                "capabilities": r.capabilities,
                "llm_registers": r.llm_registers,
                "llm_supports_tools": r.llm_supports_tools,
            }
            for r in rows
        ],
        "smoke": smoke_results,
    }
    if args.json_out:
        path = args.json_out
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
