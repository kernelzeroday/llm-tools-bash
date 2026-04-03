import json
import tempfile
import llm
from llm_tools_bash import bash


def test_bash_direct_ok():
    out = bash("printf '%s' 'ok'", timeout_seconds=5.0)
    assert "ok" in out
    assert "exit code: 0" in out


def test_bash_direct_cwd():
    with tempfile.TemporaryDirectory() as tmp:
        out = bash("basename \"$PWD\"", cwd=tmp, timeout_seconds=5.0)
    assert tmp.rstrip("/").split("/")[-1] in out or tmp.split("/")[-1] in out


def test_bash_echo():
    model = llm.get_model("echo")
    chain_response = model.chain(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "bash",
                        "arguments": {
                            "command": "printf '%s' 'hello'",
                            "timeout_seconds": 5.0,
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
    assert "exit code: 0" in out


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
    assert "exit code: 7" in out
