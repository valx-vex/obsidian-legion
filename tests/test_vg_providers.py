import json
import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from obsidian_legion.vaultgraph import providers
from obsidian_legion.vaultgraph.providers import MissionResult, ProviderChain


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class FakeRunner:
    """Records calls; returns scripted procs keyed by provider binary name."""

    def __init__(self, script):
        # script: {binary_name: [proc, proc, ...]} consumed in order (last repeats)
        self.script = script
        self.calls = []

    def __call__(self, argv, input_text, timeout, env):
        self.calls.append({"argv": list(argv), "input": input_text,
                           "timeout": timeout, "env": dict(env or {})})
        name = os.path.basename(argv[0])
        queue = self.script.get(name, [_proc(returncode=1, stderr="no script")])
        return queue[0] if len(queue) == 1 else queue.pop(0)


def _provider(name, binary, prompt_via="stdin", argv_extra=None, timeout_s=300):
    argv = [binary] + (argv_extra or [])
    return {"name": name, "argv": argv, "prompt_via": prompt_via,
            "timeout_s": timeout_s, "env": {}}


def test_stdin_success_returns_first_provider():
    runner = FakeRunner({"aa": [_proc(stdout="PAGE BODY")]})
    chain = ProviderChain([_provider("first", "/bin/aa"),
                           _provider("second", "/bin/bb")], run_fn=runner)
    result = chain.run_mission("hello")
    assert isinstance(result, MissionResult)
    assert result.ok is True and result.provider == "first"
    assert result.text == "PAGE BODY"
    assert runner.calls[0]["input"] == "hello"      # stdin carries the prompt
    assert len(runner.calls) == 1                     # second never tried


def test_tempfile_substitutes_promptfile_placeholder(tmp_path):
    seen = {}

    def runner(argv, input_text, timeout, env):
        seen["argv"] = list(argv)
        seen["input"] = input_text
        # the temp file must exist and contain the prompt at call time
        # (argv[-1] is gemini's `@<abspath>` include sigil; strip the `@`
        # to reach the real filesystem path)
        path = argv[-1].removeprefix("@")
        seen["contents"] = open(path, encoding="utf-8").read()
        return _proc(stdout="OK")

    chain = ProviderChain(
        [_provider("gemini", "/bin/gemini", prompt_via="tempfile",
                   argv_extra=["-p", "@{promptfile}"])],
        run_fn=runner)
    result = chain.run_mission("GROUNDING TEXT")
    assert result.ok is True
    assert "{promptfile}" not in " ".join(seen["argv"])   # placeholder resolved
    assert seen["argv"][-1].startswith("@/")               # @<abspath>
    assert seen["input"] is None                            # tempfile => no stdin
    assert seen["contents"] == "GROUNDING TEXT"


def test_nonzero_exit_advances_to_next_provider():
    runner = FakeRunner({"aa": [_proc(returncode=2, stderr="boom")],
                         "bb": [_proc(stdout="RECOVERED")]})
    chain = ProviderChain([_provider("first", "/bin/aa"),
                           _provider("second", "/bin/bb")], run_fn=runner)
    result = chain.run_mission("q")
    assert result.ok is True and result.provider == "second"
    assert "first" not in chain.dead_providers            # generic failure != dead


def test_empty_stdout_advances_to_next_provider():
    runner = FakeRunner({"aa": [_proc(stdout="   \n")],
                         "bb": [_proc(stdout="REAL")]})
    chain = ProviderChain([_provider("first", "/bin/aa"),
                           _provider("second", "/bin/bb")], run_fn=runner)
    result = chain.run_mission("q")
    assert result.provider == "second" and result.text == "REAL"


def test_quota_marks_provider_dead_for_rest_of_run():
    runner = FakeRunner({"aa": [_proc(returncode=1, stderr="Error: RESOURCE_EXHAUSTED quota")],
                         "bb": [_proc(stdout="B1"), _proc(stdout="B2")]})
    chain = ProviderChain([_provider("first", "/bin/aa"),
                           _provider("second", "/bin/bb")], run_fn=runner)
    first = chain.run_mission("m1")
    assert first.provider == "second" and first.quota_exhausted is True
    assert "first" in chain.dead_providers
    # second mission: dead provider is skipped entirely (not re-invoked)
    second = chain.run_mission("m2")
    assert second.provider == "second"
    aa_calls = [c for c in runner.calls if os.path.basename(c["argv"][0]) == "aa"]
    assert len(aa_calls) == 1                              # never retried after quota


def test_quota_noise_on_success_is_ignored():
    # exit 0 + non-empty stdout is a success; stderr quota noise is irrelevant
    runner = FakeRunner({"aa": [_proc(returncode=0, stdout="valid page",
                                      stderr="warning: nearing capacity 429")]})
    chain = ProviderChain([_provider("first", "/bin/aa"),
                           _provider("second", "/bin/bb")], run_fn=runner)
    result = chain.run_mission("q")
    assert result.ok is True and result.text == "valid page"
    assert result.provider == "first"
    assert "first" not in chain.dead_providers          # not marked dead on success
    # a subsequent mission still uses that provider first
    second = chain.run_mission("q2")
    assert second.provider == "first"


def test_quota_pattern_match_is_case_insensitive():
    runner = FakeRunner({"aa": [_proc(returncode=1, stderr="429 Too Many Requests")],
                         "bb": [_proc(stdout="B")]})
    chain = ProviderChain([_provider("first", "/bin/aa"),
                           _provider("second", "/bin/bb")], run_fn=runner)
    chain.run_mission("q")
    assert "first" in chain.dead_providers


def test_all_dead_returns_not_ok():
    runner = FakeRunner({"aa": [_proc(returncode=1, stderr="rate limit hit")],
                         "bb": [_proc(returncode=1, stderr="capacity exceeded")]})
    chain = ProviderChain([_provider("first", "/bin/aa"),
                           _provider("second", "/bin/bb")], run_fn=runner)
    result = chain.run_mission("q")
    assert result.ok is False and result.text == "" and result.provider == ""
    assert result.quota_exhausted is True
    assert chain.dead_providers == {"first", "second"}


def test_preflight_checks_exists_and_executable(tmp_path):
    good = tmp_path / "runme"
    good.write_text("#!/bin/sh\n")
    good.chmod(good.stat().st_mode | stat.S_IXUSR)
    chain = ProviderChain([
        {"name": "real", "argv": [str(good)], "prompt_via": "stdin", "timeout_s": 1, "env": {}},
        {"name": "missing", "argv": [str(tmp_path / "nope")], "prompt_via": "stdin",
         "timeout_s": 1, "env": {}},
    ])
    flags = chain.preflight()
    assert flags == {"real": True, "missing": False}


def test_two_consecutive_timeouts_retire_provider():
    # Auth-hang budget: an interactive/unauthenticated provider that hangs must
    # be retired dead-for-run after 2 back-to-back timeouts, not burn timeout_s
    # per page all night.
    calls = []

    def timeout_runner(argv, input_text, timeout, env):
        calls.append(os.path.basename(argv[0]))
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

    chain = ProviderChain([_provider("hang", "/bin/hang")], run_fn=timeout_runner)

    first = chain.run_mission("m1")
    assert first.ok is False
    assert "hang" not in chain.dead_providers            # one timeout != dead
    assert "timeout after" in first.error                # precise classification

    chain.run_mission("m2")
    assert "hang" in chain.dead_providers                # second consecutive -> dead

    third = chain.run_mission("m3")
    assert third.ok is False
    assert len(calls) == 2                               # dead provider never re-invoked


def test_generic_failure_between_timeouts_resets_streak():
    # A non-timeout failure breaks the consecutive-timeout streak: the provider
    # is NOT retired on the next lone timeout.
    scripted = {"hang": [None, _proc(returncode=1, stderr="boom"), None]}

    def runner(argv, input_text, timeout, env):
        name = os.path.basename(argv[0])
        item = scripted[name].pop(0)
        if item is None:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)
        return item

    chain = ProviderChain([_provider("hang", "/bin/hang")], run_fn=runner)
    chain.run_mission("m1")                              # timeout -> count 1
    chain.run_mission("m2")                              # generic failure -> reset
    chain.run_mission("m3")                              # timeout -> count 1 again
    assert "hang" not in chain.dead_providers


def test_default_providers_uses_absolute_paths_and_skips_absent(monkeypatch):
    calls = []

    def fake_which(binary):
        calls.append(binary)
        return f"/opt/homebrew/bin/{binary}" if binary in ("gemini", "codex") else None

    monkeypatch.setattr(providers.shutil, "which", fake_which)
    entries = providers.default_providers()
    names = [e["name"] for e in entries]
    assert names == ["gemini", "codex"]                   # ollama/claude absent -> skipped
    for entry in entries:
        assert os.path.isabs(entry["argv"][0])            # shell-independent absolute path
    assert {"gemini", "codex", "ollama", "claude"} <= set(calls)  # all four probed


# --- HTTP provider (kind == "http"), driven by httpx.MockTransport --------

def _http_provider(name="ollama", url="http://fake", model="m:cloud", timeout_s=600):
    return {"name": name, "kind": "http", "url": url, "model": model,
            "timeout_s": timeout_s}


def test_http_success_returns_content_only():
    # The API separates message.content from message.thinking; the chain must
    # return content and NEVER leak the reasoning field.
    def handler(request):
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "m:cloud"
        assert payload["stream"] is False
        assert payload["messages"] == [{"role": "user", "content": "write the page"}]
        return httpx.Response(200, json={"message": {"content": "PAGE BODY",
                                                     "thinking": "SECRET REASONING"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    chain = ProviderChain([_http_provider()], http_client=client)
    result = chain.run_mission("write the page")
    assert result.ok is True and result.provider == "ollama"
    assert result.text == "PAGE BODY"
    assert "SECRET" not in result.text
    assert "thinking" not in result.text.lower()


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_http_quota_status_retires_provider_and_advances(status):
    def handler(request):
        return httpx.Response(status, text="denied")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    runner = FakeRunner({"bb": [_proc(stdout="FALLBACK")]})
    chain = ProviderChain([_http_provider(),
                           _provider("second", "/bin/bb")],
                          run_fn=runner, http_client=client)
    result = chain.run_mission("q")
    assert result.provider == "second" and result.text == "FALLBACK"
    assert "ollama" in chain.dead_providers            # retired run-wide
    assert result.quota_exhausted is True


def test_http_non_quota_error_advances_without_retiring():
    def handler(request):
        return httpx.Response(500, text="internal boom")   # no quota vocabulary

    client = httpx.Client(transport=httpx.MockTransport(handler))
    runner = FakeRunner({"bb": [_proc(stdout="RECOVERED")]})
    chain = ProviderChain([_http_provider(),
                           _provider("second", "/bin/bb")],
                          run_fn=runner, http_client=client)
    result = chain.run_mission("q")
    assert result.provider == "second" and result.text == "RECOVERED"
    assert "ollama" not in chain.dead_providers        # generic failure != dead


def test_http_timeout_feeds_consecutive_timeout_retirement():
    def handler(request):
        raise httpx.ConnectTimeout("slow")             # subclass of TimeoutException

    client = httpx.Client(transport=httpx.MockTransport(handler))
    chain = ProviderChain([_http_provider()], http_client=client)
    first = chain.run_mission("m1")
    assert first.ok is False
    assert "ollama" not in chain.dead_providers        # one timeout != dead
    assert "timeout after" in first.error
    chain.run_mission("m2")
    assert "ollama" in chain.dead_providers            # second consecutive -> dead


# --- HTTP preflight -------------------------------------------------------

def _preflight_handler(version_status=200, model_names=("m:cloud",)):
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(version_status, json={"version": "0.1.0"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n}
                                                        for n in model_names]})
        return httpx.Response(404, text="nope")
    return handler


def test_preflight_http_true_when_version_ok_and_model_present():
    client = httpx.Client(transport=httpx.MockTransport(
        _preflight_handler(model_names=("m:cloud", "other:cloud"))))
    chain = ProviderChain([_http_provider(model="m:cloud")], http_client=client)
    assert chain.preflight() == {"ollama": True}


def test_preflight_http_false_when_model_missing():
    client = httpx.Client(transport=httpx.MockTransport(
        _preflight_handler(model_names=("other:cloud",))))
    chain = ProviderChain([_http_provider(model="m:cloud")], http_client=client)
    assert chain.preflight() == {"ollama": False}


def test_preflight_http_false_on_connection_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    chain = ProviderChain([_http_provider()], http_client=client)
    assert chain.preflight() == {"ollama": False}


# --- wiki_providers ordering + env overrides ------------------------------

def test_wiki_providers_ollama_http_first_then_cli(monkeypatch):
    monkeypatch.delenv("LEGION_OLLAMA_URL", raising=False)
    monkeypatch.delenv("LEGION_OLLAMA_MODEL", raising=False)

    def fake_which(binary):
        return (f"/opt/homebrew/bin/{binary}"
                if binary in ("gemini", "codex", "claude") else None)

    monkeypatch.setattr(providers.shutil, "which", fake_which)
    entries = providers.wiki_providers()
    head = entries[0]
    assert head["name"] == "ollama" and head["kind"] == "http"
    assert head["url"] == "http://localhost:11434"
    assert head["model"] == providers.DEFAULT_WIKI_MODEL
    assert head["timeout_s"] == 600
    assert [e["name"] for e in entries[1:]] == ["gemini", "codex", "claude"]
    # exactly ONE ollama entry (the CLI ollama from default_providers is dropped)
    assert sum(1 for e in entries if e["name"] == "ollama") == 1


def test_wiki_providers_env_overrides(monkeypatch):
    monkeypatch.setenv("LEGION_OLLAMA_URL", "http://box:9999")
    monkeypatch.setenv("LEGION_OLLAMA_MODEL", "custom:cloud")
    monkeypatch.setattr(providers.shutil, "which", lambda b: None)  # no CLI binaries
    entries = providers.wiki_providers()
    assert entries == [{"name": "ollama", "kind": "http", "url": "http://box:9999",
                        "model": "custom:cloud", "timeout_s": 600}]


def test_default_providers_ollama_uses_default_wiki_model(monkeypatch):
    monkeypatch.delenv("LEGION_OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(providers.shutil, "which",
                        lambda binary: f"/opt/homebrew/bin/{binary}")   # all present
    entries = providers.default_providers()
    ollama = next(e for e in entries if e["name"] == "ollama")
    assert providers.DEFAULT_WIKI_MODEL in ollama["argv"]
    assert "gpt-oss:120b-cloud" not in ollama["argv"]
    assert providers.DEFAULT_WIKI_MODEL == "minimax-m3:cloud"
