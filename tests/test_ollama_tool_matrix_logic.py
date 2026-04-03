"""Mirrors llm_ollama.register_models capability gating."""


def registration_from_ollama_capabilities(caps: list[str]) -> tuple[bool, bool]:
    """(registered_as_chat, supports_tools)."""
    if "completion" not in caps:
        return False, False
    return True, "tools" in caps


def test_embedding_only_not_registered():
    assert registration_from_ollama_capabilities(["embedding"]) == (False, False)


def test_completion_without_tools():
    assert registration_from_ollama_capabilities(["completion", "vision"]) == (True, False)


def test_completion_with_tools():
    assert registration_from_ollama_capabilities(
        ["completion", "vision", "tools", "thinking"],
    ) == (True, True)


def test_tools_without_completion():
    assert registration_from_ollama_capabilities(["tools"]) == (False, False)
