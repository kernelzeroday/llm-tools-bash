import json
import tempfile
import pytest
import llm
import llm_tools_bash
from llm_tools_bash import BASH_TOOL_DESCRIPTION, bash, _truncate_text


@pytest.fixture(autouse=True)
def _reset_doc_session_autouse():
    llm_tools_bash._reset_doc_session()
    yield


def test_bash_tool_description():
    assert "bash -c" in BASH_TOOL_DESCRIPTION.lower()
    assert "entire shell" in BASH_TOOL_DESCRIPTION.lower()
    assert "tldr" in BASH_TOOL_DESCRIPTION.lower()
    assert "doc: man" in BASH_TOOL_DESCRIPTION.lower()
    assert "omitted" in BASH_TOOL_DESCRIPTION.lower()
    assert "truncate" in BASH_TOOL_DESCRIPTION.lower()
    assert "fixed wall-clock" in BASH_TOOL_DESCRIPTION.lower()
    assert "--cl" in BASH_TOOL_DESCRIPTION
    assert "llm ollama models" in BASH_TOOL_DESCRIPTION


def test_truncate_text_inserts_banner():
    lines = [str(i) for i in range(10)]
    text = "\n".join(lines)
    out, did, nlines = _truncate_text(text, head=3, tail=2)
    assert did is True
    assert nlines == 10
    assert "omitted" in out
    assert "0\n1\n2" in out
    assert "8\n9" in out


def test_truncate_text_short_unchanged():
    text = "a\nb\nc"
    out, did, nlines = _truncate_text(text, head=2, tail=2)
    assert out == text
    assert did is False
    assert nlines == 3


def test_bash_truncates_many_lines(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 1.0)
    cmd = "for i in $(seq 1 120); do echo line$i; done"
    out = bash(cmd, truncate=True)
    assert "line1" in out
    assert "line120" in out
    assert "omitted" in out
    assert "--- meta" in out
    assert "trunc" in out
    assert "e=0" in out
    assert "--- hint:" not in out


def test_bash_no_truncate_full(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 1.0)
    cmd = "for i in $(seq 1 50); do echo line$i; done"
    out = bash(cmd, truncate=False)
    assert "omitted" not in out
    assert out.count("line") == 50
    assert "e=0" in out
    assert " cap=" not in out


def test_bash_direct_ok(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 1.0)
    out = bash("printf '%s' 'ok'")
    assert "ok" in out
    assert "e=0" in out
    assert "--- meta" in out


def test_bash_success_tip_when_random_low(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 0.0)
    monkeypatch.setattr("random.choice", lambda seq: seq[0])
    out = bash("true")
    assert "--- tip:" in out


def test_bash_success_tip_skipped_when_random_high(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 1.0)
    out = bash("true")
    assert "--- tip:" not in out


def test_bash_timeout_meta_and_hint(monkeypatch):
    monkeypatch.setattr(llm_tools_bash, "_INTERNAL_TIMEOUT_SEC", 0.15)
    out = bash("sleep 60")
    assert "wall-clock" in out.lower()
    assert "--- meta timeout" in out
    assert "--- hint:" in out
    assert "retry:" in out


def test_bash_direct_cwd(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 1.0)
    with tempfile.TemporaryDirectory() as tmp:
        out = bash("basename \"$PWD\"", cwd=tmp)
    assert tmp.rstrip("/").split("/")[-1] in out or tmp.split("/")[-1] in out


def test_bash_echo(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 1.0)
    model = llm.get_model("echo")
    chain_response = model.chain(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "bash",
                        "arguments": {
                            "command": "printf '%s' 'hello'",
                        },
                    }
                ]
            }
        ),
        tools=[bash],
    )
    responses = list(chain_response.responses())
    tool_results = json.loads(responses[-1].text())["tool_results"]
    out = tool_results[0]["output"]
    assert "hello" in out
    assert "e=0" in out


def test_bash_stderr_nonzero():
    model = llm.get_model("echo")
    chain_response = model.chain(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "bash",
                        "arguments": {"command": "echo err >&2; exit 7"},
                    }
                ]
            }
        ),
        tools=[bash],
    )
    responses = list(chain_response.responses())
    tool_results = json.loads(responses[-1].text())["tool_results"]
    out = tool_results[0]["output"]
    assert "err" in out
    assert "e=7" in out
    assert "--- hint:" in out
    assert "retry:" in out


def test_bash_nonzero_direct():
    out = bash("exit 3")
    assert "e=3" in out
    assert "--- hint:" in out


def test_meta_reports_timing(monkeypatch):
    monkeypatch.setattr("random.random", lambda: 1.0)
    out = bash("true")
    assert "t=" in out and "ms" in out


def test_hint_pools_single_line():
    import llm_tools_bash as m
    for pool in (
        m._TIMEOUT_HINTS,
        m._TIMEOUT_BARE_HINTS,
        m._TIMEOUT_REPEAT_HINTS,
        m._NONZERO_HINTS,
        m._EXC_HINTS,
        m._SUCCESS_TIPS,
    ):
        for h in pool:
            assert "\n" not in h


def test_is_bare_command():
    from llm_tools_bash import _is_bare_command
    assert _is_bare_command("cbonsai") is True
    assert _is_bare_command("cbonsai -p") is False
    assert _is_bare_command("echo x") is False


def test_doc_target():
    from llm_tools_bash import _doc_target
    assert _doc_target("cbonsai -p") == "cbonsai"
    assert _doc_target("sudo git status") == "git"
    assert _doc_target("man ls") == "ls"
    assert _doc_target("man 3 printf") == "printf"
    assert _doc_target("tldr tar") == "tar"
    assert _doc_target("ls && rm -f x") == "ls"
    assert _doc_target("") is None


def test_doc_appendices_calls_man_tldr(monkeypatch):
    from subprocess import CompletedProcess

    def fake_run(*args, **kwargs):
        argv = args[0]
        return CompletedProcess(argv, 0, stdout=f"stub:{argv[0]}:{argv[1]}\n", stderr="")

    monkeypatch.setattr(llm_tools_bash.subprocess, "run", fake_run)
    from llm_tools_bash import _doc_appendices

    s = _doc_appendices("foo -x")
    assert "--- doc: man foo ---" in s
    assert "--- doc: tldr foo ---" in s
    assert "stub:man:foo" in s
    assert "stub:tldr:foo" in s


def test_doc_session_dedupes_no_second_subprocess(monkeypatch):
    from subprocess import CompletedProcess

    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        argv = args[0]
        calls.append(list(argv))
        return CompletedProcess(argv, 0, stdout="doc\n", stderr="")

    monkeypatch.setattr(llm_tools_bash.subprocess, "run", fake_run)
    from llm_tools_bash import _doc_appendices

    _doc_appendices("cbonsai")
    assert len(calls) == 2
    _doc_appendices("cbonsai -p")
    assert len(calls) == 2
    out = _doc_appendices("cbonsai")
    assert "omitted" in out.lower()
    assert len(calls) == 2


def test_is_help_probe():
    from llm_tools_bash import _is_help_probe
    assert _is_help_probe("cbonsai --help") is True
    assert _is_help_probe("cbonsai -h") is True
    assert _is_help_probe("man cbonsai") is True
    assert _is_help_probe("tldr cbonsai") is True
    assert _is_help_probe("cbonsai -p") is False
    assert _is_help_probe("python3 -c 'print(1)'") is False


def test_timeout_hint_bare_then_repeat():
    import llm_tools_bash as m
    m._reset_timeout_streak()
    first = m._timeout_hint("cbonsai")
    second = m._timeout_hint("cbonsai")
    assert "argv" in first.lower() or "lone" in first.lower()
    assert "verbatim" in second.lower() or "exact" in second.lower() or "already ran" in second.lower()


def test_timeout_streak_resets_after_success(monkeypatch):
    monkeypatch.setattr(llm_tools_bash, "_INTERNAL_TIMEOUT_SEC", 0.1)
    llm_tools_bash._reset_timeout_streak()
    bash("sleep 2")
    bash("true")
    out = bash("sleep 2")
    assert "exact shell string already" not in out


def test_help_probe_success_does_not_reset_timeout_streak(monkeypatch):
    monkeypatch.setattr(llm_tools_bash, "_INTERNAL_TIMEOUT_SEC", 0.1)
    llm_tools_bash._reset_timeout_streak()
    bash("sleep 2")
    bash("python3 --help")
    out = bash("sleep 2")
    lo = out.lower()
    assert (
        "verbatim" in lo
        or "exact" in lo
        or "already ran" in lo
        or "default invocation" in lo
    )


def test_timeout_second_identical_nonbare_is_repeat(monkeypatch):
    monkeypatch.setattr(llm_tools_bash, "_INTERNAL_TIMEOUT_SEC", 0.1)
    llm_tools_bash._reset_timeout_streak()
    bash("sleep 2")
    out2 = bash("sleep 2")
    lo = out2.lower()
    assert (
        "verbatim" in lo
        or "exact" in lo
        or "already ran" in lo
        or "default invocation" in lo
    )
