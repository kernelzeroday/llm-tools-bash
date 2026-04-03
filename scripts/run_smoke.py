#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    import llm
    from llm_tools_bash import BASH_TOOL_DESCRIPTION, bash
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    log_path = artifacts / "smoke.log"
    buf = []

    def log(msg: str) -> None:
        buf.append(msg)
        print(msg)

    log("=== llm-tools-bash smoke ===")
    log("")
    log("=== direct bash: 200 lines; expect middle truncated ===")
    cmd = "for i in $(seq 1 200); do echo L$i; done"
    out = bash(cmd)
    log(out)
    log("")
    log("=== direct bash: same command, truncate=False ===")
    out_full = bash(cmd, truncate=False)
    log(f"char_len={len(out_full)} cap_in_meta={('cap=' in out_full)}")
    log("")
    log("=== echo model + bash tool (date) ===")
    model = llm.get_model("echo")
    chain = model.chain(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "bash",
                        "arguments": {"command": "date"},
                    }
                ]
            }
        ),
        tools=[bash],
    )
    log(list(chain.responses())[-1].text())
    log("")
    log("=== echo model + long output (default truncation in tool result) ===")
    chain2 = model.chain(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "bash",
                        "arguments": {"command": cmd},
                    }
                ]
            }
        ),
        tools=[bash],
    )
    log(list(chain2.responses())[-1].text()[:3500])
    log("... [preview cut] ...")
    log("")
    log("=== BASH_TOOL_DESCRIPTION (first 600 chars) ===")
    log(BASH_TOOL_DESCRIPTION[:600])
    log("")
    optional = os.environ.get("LLM_SMOKE_MODEL")
    if optional:
        log(f"=== optional LLM_SMOKE_MODEL={optional!r} (subprocess, may require ollama running) ===")
        import subprocess

        try:
            cp = subprocess.run(
                [
                    "llm",
                    "-m",
                    optional,
                    "-T",
                    "bash",
                    "--td",
                    "--cl",
                    "15",
                    "-n",
                    "Run date using the bash tool once.",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=180,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            log(cp.stdout)
            log(cp.stderr)
            log(f"returncode={cp.returncode}")
        except Exception as e:
            log(f"optional subprocess failed: {e!s}")
    else:
        log("=== set LLM_SMOKE_MODEL=gemma4:latest to append a live llm CLI subprocess check ===")
    log_path.write_text("\n".join(buf), encoding="utf-8")
    log("")
    log(f"wrote {log_path}")


if __name__ == "__main__":
    main()
