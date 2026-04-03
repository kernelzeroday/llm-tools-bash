# llm-tools-bash

Fork of [llm-tools-simpleeval](https://github.com/simonw/llm-tools-simpleeval) that exposes a **`bash` tool** instead of `simple_eval`. Commands run as **non-login** bash with **`--noprofile --norc`** (no `/etc/profile`, `~/.bash_profile`, or `~/.bashrc`), and **`BASH_ENV` / `ENV` are unset** so optional startup scripts are not pulled in—only your normal process environment (e.g. `PATH`) remains. A **timeout**, **optional working directory**, and **stdout/stderr plus exit code** are returned to the model (similar in spirit to tool execution layers in projects like [clawd-code](https://github.com/linwumeng/clawd-code)).

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

## Usage

```bash
llm -T bash "List files in /tmp" --td
```

The tool accepts:

- **`command`** (string): shell snippet passed to `bash --noprofile --norc -c` (non-interactive, no user rc files).
- **`timeout_seconds`** (float, default `30`): seconds before the run is killed.
- **`cwd`** (string, optional): working directory for the subprocess.

Output includes captured stdout, stderr (if any), and a trailing `--- exit code: N ---` line.

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
