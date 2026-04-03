import os
import random
import re
import subprocess
import time
import llm
from llm.models import Tool

_HEAD = 60
_TAIL = 40
_INTERNAL_TIMEOUT_SEC = 12.0
_DOC_MAN_SEC = 6.0
_DOC_TLDR_SEC = 14.0
_DOC_MAX_CHARS = 6000
_SUCCESS_TIP_PROB = 0.12

_timeout_last_key: str | None = None
_timeout_same_repeats: int = 0
_doc_emitted: set[tuple[str, str]] = set()

_TIMEOUT_HINTS = [
    "retry: read `man CMD`, `CMD --help`, or `tldr CMD` (cheat sheet) before running again.",
    "retry: long or stuck work: `CMD > /tmp/o.txt 2>&1 &` then `cat /tmp/o.txt` on the next call.",
    "retry: nest your own cap: `timeout 60s CMD` inside the shell string when you know the inner job is bounded.",
    "retry: look for batch, print-only, or no-TTY flags in the tool’s docs—defaults often assume a terminal.",
]

_TIMEOUT_BARE_HINTS = [
    "retry: one argv with no flags often maps to interactive/live mode—try `tldr CMD`, then `CMD --help`, then non-default flags.",
    "retry: a lone binary name is rarely enough; check subcommands and flags that avoid TTY or animation.",
]

_TIMEOUT_REPEAT_HINTS = [
    "retry: this exact shell string already timed out—do not repeat it verbatim; use flags from help/tldr or background+file.",
    "retry: if you already ran `--help` or `tldr`, apply an option from that output instead of the default invocation.",
]

_NONZERO_HINTS = [
    "retry: parse stderr above, then fix flags, paths, or permissions.",
    "retry: `CMD --help`, `man CMD`, and `tldr CMD` document arguments and common patterns.",
]

_EXC_HINTS = [
    "retry: shorten the shell snippet and check `cwd`.",
    "retry: quote paths with spaces; use `command -v CMD` to verify the binary.",
]

_SUCCESS_TIPS = [
    "tip: use `&&` only when the next step must follow success; use `;` for independent steps.",
    "tip: `2>&1` merges stderr into stdout when you need a single stream.",
    "tip: `$( )` captures stdout; quote nested expansions when paths have spaces.",
    "tip: `set -e` at the start of a snippet exits on the first failing command.",
    "tip: `tldr CMD` gives concise examples when `man` is too long—if missing, install the `tldr` client.",
]

BASH_TOOL_DESCRIPTION = """**`command` is the entire shell string** passed to `bash -c`—not “just the program name”. Put the full invocation in one string: flags, pipes, redirects, `&&` / `;`, subshells, etc. Examples: `cbonsai -p`, `git log -1 --oneline`, `make -n target`, `foo > /tmp/x.txt && wc -c /tmp/x.txt`.

To learn a binary quickly, use **`tldr CMD`** (example-focused cheat sheet), **`CMD --help`**, or **`man CMD`**—often in separate bash calls before the real run.

Runs in non-login bash (`--noprofile --norc`; `BASH_ENV`/`ENV` unset). Not a TTY—TUIs, pagers, and stdin waits are common. A **fixed wall-clock limit** applies inside the tool (you cannot set it); if you hit it, reformulate (background `&`, file redirect, then read in a follow-up call).

Use **multiple bash calls**; raise CLI **chain limit** if needed (`--cl 0`).

**Tool support:** The host must give the model tools (`llm models` shows **tools** when supported). On **Ollama**, only tags whose server **capabilities** include **`tools`** work with `-T`—run **`llm ollama models`** (or `ollama show TAG`) to verify; **`completion` without `tools`** means chat works but not this tool.

**`truncate`:** if true (default), long capture is line-collapsed (fixed window); if false, full. The **`--- meta`** line reports exit, time, bytes.

**Hints:** one short **`--- hint:`** on errors (random; **repeat timeouts** and **bare single-token** commands bias the text). On **timeout, non-zero exit, or harness exception**, the tool also tries **`man`** and **`tldr`** on the **first command name** inferred from your string (heuristic) and appends **`--- doc: man … ---` / `--- doc: tldr … ---`** when available—**full text once per name per llm process**; repeats show a one-line **omitted** notice (same shell session / single `llm` run). A successful **`tldr` / `man` / `--help` / `-h` probe does not clear** a timeout streak for the same bare command. Occasional **`--- tip:`** on success."""


def _reset_timeout_streak() -> None:
    global _timeout_last_key, _timeout_same_repeats
    _timeout_last_key = None
    _timeout_same_repeats = 0


def _is_bare_command(s: str) -> bool:
    if not s or "\n" in s:
        return False
    if any(ch in s for ch in ";|&"):
        return False
    parts = s.split()
    return len(parts) == 1


def _is_help_probe(s: str) -> bool:
    t = s.strip().lower()
    if not t:
        return False
    if t.startswith("man ") or t.startswith("info ") or t.startswith("tldr "):
        return True
    if "--help" in t:
        return True
    return bool(re.search(r"(^|\s)-h(\s|$)", t))


def _timeout_hint(command: str) -> str:
    global _timeout_last_key, _timeout_same_repeats
    key = command.strip()
    if key == _timeout_last_key:
        _timeout_same_repeats += 1
    else:
        _timeout_last_key = key
        _timeout_same_repeats = 1
    if _timeout_same_repeats >= 2:
        return random.choice(_TIMEOUT_REPEAT_HINTS)
    if _is_bare_command(key):
        return random.choice(_TIMEOUT_BARE_HINTS)
    return random.choice(_TIMEOUT_HINTS)


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def _truncate_text(text: str, head: int, tail: int) -> tuple[str, bool, int]:
    lines = text.splitlines()
    n = len(lines)
    if head < 1 or tail < 1 or n <= head + tail:
        return text, False, n
    omitted = n - head - tail
    first = "\n".join(lines[:head])
    mid = f"--- … {omitted} lines omitted ---"
    last = "\n".join(lines[-tail:])
    return "\n".join([first, mid, last]), True, n


def _meta_line(
    *,
    exit_code: int,
    time_ms: int,
    capture_b: int,
    body_b: int,
    truncated: bool,
) -> str:
    parts = [f"e={exit_code}", f"t={time_ms}ms", f"b={body_b}b"]
    if truncated:
        parts.append(f"cap={capture_b}b")
        parts.append("trunc")
    return "--- meta " + " ".join(parts) + " ---"


def _maybe_success_tip() -> str | None:
    if random.random() >= _SUCCESS_TIP_PROB:
        return None
    return random.choice(_SUCCESS_TIPS)


def _clean_cmd_token(tok: str) -> str:
    t = tok.strip()
    if t.startswith("./"):
        t = t[2:]
    b = os.path.basename(t)
    if b and re.match(r"^[\w.-]+$", b):
        return b
    return ""


def _doc_target(command: str) -> str | None:
    s = command.strip()
    if not s:
        return None
    for sep in ("&&", "||", "|"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    if ";" in s:
        s = s.split(";", 1)[0].strip()
    while True:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", s)
        if not m:
            break
        s = s[m.end() :].lstrip()
    parts = s.split()
    if not parts:
        return None
    skip = {"sudo", "nice", "nohup", "command", "env", "time", "stdbuf", "runuser", "sg"}
    i = 0
    while i < len(parts) and parts[i] in skip:
        i += 1
    if i >= len(parts):
        return None
    if parts[i] in ("man", "info", "tldr"):
        j = i + 1
        if parts[i] == "man" and j < len(parts) and parts[j].isdigit():
            j += 1
        if j < len(parts):
            return _clean_cmd_token(parts[j]) or None
        return None
    return _clean_cmd_token(parts[i]) or None


def _capture_doc(argv: list[str], timeout: float, env_extra: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        if out:
            text = out
        elif err:
            text = err
        else:
            text = f"(no output, exit {p.returncode})"
    except subprocess.TimeoutExpired:
        return "(timed out)"
    except FileNotFoundError:
        return "(executable not found)"
    except Exception as e:
        return f"({e!s})"
    if len(text) > _DOC_MAX_CHARS:
        return text[:_DOC_MAX_CHARS] + "\n…"
    return text


def _reset_doc_session() -> None:
    global _doc_emitted
    _doc_emitted = set()


def _doc_one(kind: str, name: str, argv: list[str], ttl: float, env_extra: dict[str, str] | None) -> str:
    key = (kind, name.lower())
    if key in _doc_emitted:
        return f"--- doc: {kind} {name} ---\n(omitted—already shown once this llm session)"
    txt = _capture_doc(argv, ttl, env_extra)
    _doc_emitted.add(key)
    return f"--- doc: {kind} {name} ---\n{txt}"


def _doc_appendices(command: str) -> str:
    name = _doc_target(command)
    if not name:
        return ""
    man_part = _doc_one(
        "man",
        name,
        ["man", name],
        _DOC_MAN_SEC,
        {"MANPAGER": "cat", "PAGER": "cat", "MANWIDTH": "100"},
    )
    tldr_part = _doc_one("tldr", name, ["tldr", name], _DOC_TLDR_SEC, None)
    return f"\n{man_part}\n{tldr_part}"


def bash(
    command: str,
    cwd: str | None = None,
    truncate: bool = True,
) -> str:
    """Run `command`; see BASH_TOOL_DESCRIPTION."""
    t0 = time.perf_counter()
    try:
        env = os.environ.copy()
        env.pop("BASH_ENV", None)
        env.pop("ENV", None)
        completed = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", command],
            capture_output=True,
            text=True,
            timeout=_INTERNAL_TIMEOUT_SEC,
            cwd=cwd,
            env=env,
        )
        if not (completed.returncode == 0 and _is_help_probe(command)):
            _reset_timeout_streak()
        t_ms = int((time.perf_counter() - t0) * 1000)
        chunks = []
        if completed.stdout:
            chunks.append(completed.stdout.rstrip("\n"))
        if completed.stderr:
            chunks.append("--- stderr ---\n" + completed.stderr.rstrip("\n"))
        raw_body = "\n".join(chunks)
        capture_b = _utf8_len(raw_body)
        truncated = False
        body = raw_body
        if truncate and raw_body:
            body, truncated, _n = _truncate_text(raw_body, _HEAD, _TAIL)
        elif not raw_body:
            body = ""
        body_b = _utf8_len(body)
        meta = _meta_line(
            exit_code=completed.returncode,
            time_ms=t_ms,
            capture_b=capture_b,
            body_b=body_b,
            truncated=truncated,
        )
        if body:
            base = f"{body}\n{meta}"
        else:
            base = meta
        if completed.returncode != 0:
            doc = _doc_appendices(command)
            return f"{base}{doc}\n--- hint: {random.choice(_NONZERO_HINTS)} ---"
        tip = _maybe_success_tip()
        if tip:
            base = f"{base}\n--- {tip} ---"
        return base
    except subprocess.TimeoutExpired:
        t_ms = int((time.perf_counter() - t0) * 1000)
        h = _timeout_hint(command)
        doc = _doc_appendices(command)
        return (
            f"Error: wall-clock limit exceeded\n--- meta timeout t={t_ms}ms ---{doc}\n"
            f"--- hint: {h} ---"
        )
    except Exception as e:
        t_ms = int((time.perf_counter() - t0) * 1000)
        doc = _doc_appendices(command)
        return (
            f"Error: {e!s}\n--- meta err t={t_ms}ms ---{doc}\n"
            f"--- hint: {random.choice(_EXC_HINTS)} ---"
        )


@llm.hookimpl
def register_tools(register):
    register(Tool.function(bash, description=BASH_TOOL_DESCRIPTION))
