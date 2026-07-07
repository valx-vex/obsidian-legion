import os
import stat
import sys
from types import SimpleNamespace

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
