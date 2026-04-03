import os
import subprocess
import llm


def bash(command: str, timeout_seconds: float = 30.0, cwd: str | None = None) -> str:
    try:
        env = os.environ.copy()
        env.pop("BASH_ENV", None)
        env.pop("ENV", None)
        completed = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
            env=env,
        )
        chunks = []
        if completed.stdout:
            chunks.append(completed.stdout.rstrip("\n"))
        if completed.stderr:
            chunks.append("--- stderr ---\n" + completed.stderr.rstrip("\n"))
        chunks.append(f"--- exit code: {completed.returncode} ---")
        return "\n".join(chunks)
    except subprocess.TimeoutExpired:
        return f"Error: command exceeded timeout of {timeout_seconds} seconds"
    except Exception as e:
        return f"Error: {e!s}"


@llm.hookimpl
def register_tools(register):
    register(bash)
