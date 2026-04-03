# llm-tools-bash

Fork of [llm-tools-simpleeval](https://github.com/simonw/llm-tools-simpleeval) that exposes a **`bash` tool** instead of `simple_eval`. Commands run as **non-login** bash with **`--noprofile --norc`** (no `/etc/profile`, `~/.bash_profile`, or `~/.bashrc`), and **`BASH_ENV` / `ENV` are unset** so optional startup scripts are not pulled in—only your normal process environment (e.g. `PATH`) remains. A **fixed internal wall-clock limit** (not exposed to the model), **optional working directory**, **stdout/stderr**, **meta timing/size**, and occasional **tips** are returned (similar in spirit to tool execution layers in projects like [clawd-code](https://github.com/linwumeng/clawd-code)).

**Warning:** This tool runs arbitrary shell commands in your environment. Only use with trusted models and users.

## Installation

Install this plugin in the same environment as [LLM](https://llm.datasette.io/).

```bash
llm install llm-tools-bash
```

Or from a checkout:

```bash
pip install -e '.[test]'
```

### `ModuleNotFoundError: No module named 'llm_tools_bash'`

That means the LLM CLI’s environment does not have this package installed, but a stale or mismatched plugin entry point can still try to load it. **Install `llm` and `llm-tools-bash` in the same tool environment**, for example:

```bash
uv tool install llm --with llm-tools-bash --force
# or with other plugins:
uv tool install llm --with llm-ollama --with llm-openrouter --with llm-tools-bash --force
# from this repo:
uv tool install llm --with . --force
```

Use `--force` when reinstalling so dependencies stay in sync. If you use `pip`/`uv pip` instead, install into the same `site-packages` as `python -m llm` uses.

## Usage

```bash
llm -T bash "List files in /tmp" --td
```

The tool accepts:

- **`command`** (string): **full** shell snippet for `bash --noprofile --norc -c`—program name plus flags, pipes, `&&`, redirects, etc. in one string (not “the binary only”).
- **`cwd`** (string, optional): working directory for the subprocess.
- **`truncate`** (bool, default `true`): if true, long line-oriented capture is collapsed with a fixed window; if false, full capture.

Wall-clock limit is **fixed inside the plugin** (not a parameter). Each run ends with **`--- meta`** (exit, time, byte sizes; `cap`/`trunc` when line-truncation applies). On timeout: **`--- meta timeout`**. Hints vary if you repeat the same timed-out string or use a bare single-token command; a successful **`tldr` / `--help` / `man` / `-h` run does not reset** that streak so the next identical timeout can surface a stronger hint. On **timeout, non-zero exit, or exception**, the harness also runs **`man`** and **`tldr`** against the **first command name** parsed from your `command` string and appends **`--- doc: man … ---` / `--- doc: tldr … ---`** (truncated) when the tools exist. **Full doc text is shown only once per command name per `llm` process**; later errors reuse a short **omitted** line so context is not spammed. Clean successes sometimes append a random **`--- tip:`**—usually omitted.

To change the internal limit, edit `_INTERNAL_TIMEOUT_SEC` in `llm_tools_bash.py` (for maintainers).

### Smoke check (echo model + log file)

```bash
uv sync --extra test
uv run python scripts/run_smoke.py
# optional: LLM_SMOKE_MODEL=gemma4:latest uv run python scripts/run_smoke.py
```

Writes `artifacts/smoke.log`.

### LLM exits immediately or prints nothing (not this plugin)

The bash tool only runs **after** the model chooses to call it. If `llm` returns right away with **no text**, the failure is almost always **model configuration**, not `llm-tools-bash`.

1. **Merge stderr** — errors often go to stderr only:
   ```bash
   llm 'Say hi' 2>&1
   ```
2. **Unknown default model** — you may see `Error: Unknown model: …`. Compare:
   ```bash
   llm models default
   llm models
   ollama list   # if using Ollama
   ```
   Set a valid default, e.g. `llm models default gemma4:latest`.
   **Ollama tags are not interchangeable:** `gemma4:latest` and `gemma4:26b` are different published images (different size, speed, and memory use). Library `latest` for [gemma4](https://ollama.com/library/gemma4) tracks one chosen variant; `26b` is a separate pull (~18 GB vs ~9.6 GB for `latest` at time of writing). If `26b` was never pulled, is still loading, or does not fit in RAM, `llm` can fail, hang, or behave oddly while `gemma4:latest` works because that image is present and loads quickly.
3. **Provider / keys** — OpenAI and others need keys; missing keys can fail with little output unless you use `2>&1`.
4. **Tools support** — the model must support tools (see `llm models` output). While debugging, pass `-m <model>` explicitly.

Diagnostic script (same repo):

```bash
bash scripts/diagnose_llm.sh
```

### Ollama: which models support tool calling?

`llm-tools-bash` does not pick models; **[llm-ollama](https://github.com/simonw/llm-ollama)** registers a chat model only if Ollama reports **`completion`** in **capabilities**, and sets **`supports_tools`** only if **`tools`** is also present (see `llm_ollama`’s `register_models` and `_get_ollama_model_capabilities`).

**Check locally (fast):**

```bash
llm ollama models
```

The **capabilities** column lists what that binary exposes. Examples of patterns you may see:

| Pattern | Chat in `llm`? | `-T bash`? |
|--------|----------------|------------|
| `embedding` only | No (not registered as chat) | No |
| `completion` only | Yes | **No** |
| `completion` + `tools` | Yes | **Yes** (if the model actually emits tool calls) |
| `completion` + `vision` (no `tools`) | Yes | **No** |

Example: some local tags only showed **`completion`** (plus vision, etc.) with **no `tools`**—e.g. **`translategemma:latest`** and **`TheAzazel/gemma3-4b-abliterated:latest`** in one `llm ollama models` run—so `llm` can chat but **`-T` is not available** for those images. Tags that listed **`tools`** (e.g. **`gemma4:latest`**, **`gemma4:26b`**, **`functiongemma:latest`**, many Qwen/OSS pulls) passed the **llm** gate; the model must still **emit** tool calls in practice. Re-run `llm ollama models` after every `ollama pull`—capabilities are per digest.

**Audit script** (prints the same rules plus optional `llm -T bash` smoke tests; smoke needs a working Ollama inference path and can be slow on first load):

```bash
python3 scripts/ollama_tool_matrix.py
python3 scripts/ollama_tool_matrix.py --smoke-llm --smoke-timeout 120 --json-out artifacts/ollama_tool_audit.json
python3 scripts/ollama_tool_matrix.py --smoke-llm --only 'gemma4:latest'
```

**Suggested options for Gemma 4 on Ollama** (defaults often match, but you can lock them explicitly—see [Ollama library](https://ollama.com/library/gemma4)):

```bash
llm -m gemma4:latest -o temperature 1 -o top_p 0.95 -o top_k 64 -T bash "…"
```

Raise **`-o num_ctx …`** if you hit context limits on long transcripts.

## Development

```bash
cd llm-tools-bash
python -m venv venv
source venv/bin/activate
pip install -e '.[test]'
timeout 120 python -m pytest -vv --tb=short --maxfail=1
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
