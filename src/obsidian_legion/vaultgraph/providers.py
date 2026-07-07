"""Cloud-routed provider chain for VEXPEDIA missions (R5 §5.2).

Each wiki page is one headless LLM run. Providers are tried in order; a
generic failure (non-zero exit / empty stdout) advances to the next provider
FOR THIS MISSION only, while a quota/rate-limit signal on stderr marks the
provider dead for the REST OF THE RUN (dead_providers persists across
run_mission calls). Prompts are large (note excerpts), so they travel via
stdin or a temp file — never argv.

Stdlib only: the live MCP server imports nothing from here, and the nightly
job runs this under the repo .venv. Binary paths are resolved absolutely at
config time (launchd has a minimal PATH and `claude` is a shell alias
invisible to subprocess) — see default_providers().
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

QUOTA_PATTERNS = ("quota", "rate limit", "429", "resource exhausted", "capacity")


@dataclass
class MissionResult:
    text: str
    provider: str
    ok: bool
    quota_exhausted: bool
    error: str


def _default_run_fn(argv, input_text, timeout, env):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        list(argv),
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=full_env,
        check=False,
    )


class ProviderChain:
    def __init__(self, providers: list[dict], run_fn=None) -> None:
        self.providers = list(providers or [])
        self.run_fn = run_fn or _default_run_fn
        self.dead_providers: set[str] = set()
        # Consecutive-timeout counter per provider, persisted across missions
        # within a run: an unauthenticated interactive provider that hangs is
        # retired dead-for-run after 2 back-to-back timeouts (auth-hang budget).
        self._timeout_counts: dict[str, int] = {}

    def preflight(self) -> dict[str, bool]:
        flags: dict[str, bool] = {}
        for provider in self.providers:
            argv = provider.get("argv") or []
            binary = argv[0] if argv else ""
            flags[provider["name"]] = bool(binary) and os.path.exists(binary) and \
                os.access(binary, os.X_OK)
        return flags

    def run_mission(self, prompt: str) -> MissionResult:
        saw_quota = False
        last_error = "no providers configured"
        for provider in self.providers:
            name = provider["name"]
            if name in self.dead_providers:
                continue
            returncode, stdout, stderr, timed_out = self._invoke(provider, prompt)
            # Success = exit 0 with non-empty stdout. stderr is irrelevant then;
            # quota classification applies ONLY to invocations that already failed.
            if returncode == 0 and (stdout or "").strip():
                self._timeout_counts[name] = 0
                return MissionResult(text=stdout, provider=name, ok=True,
                                     quota_exhausted=saw_quota, error="")
            # Auth-hang budget: retire a provider that times out twice in a row.
            # An interactive/unauthenticated provider otherwise burns timeout_s
            # per page for the whole night.
            if timed_out:
                self._timeout_counts[name] = self._timeout_counts.get(name, 0) + 1
                last_error = f"{name}: {stderr}"
                if self._timeout_counts[name] >= 2:
                    self.dead_providers.add(name)
                continue
            # Any non-timeout outcome breaks the consecutive-timeout streak.
            self._timeout_counts[name] = 0
            stderr_lower = (stderr or "").lower()
            if any(pattern in stderr_lower for pattern in QUOTA_PATTERNS):
                self.dead_providers.add(name)
                saw_quota = True
                last_error = f"{name}: quota/rate-limit ({(stderr or '').strip()[:200]})"
                continue
            last_error = f"{name}: exit={returncode}, empty={not (stdout or '').strip()}"
            continue
        return MissionResult(text="", provider="", ok=False,
                             quota_exhausted=saw_quota, error=last_error)

    def _invoke(self, provider: dict, prompt: str):
        argv = list(provider.get("argv") or [])
        prompt_via = provider.get("prompt_via", "stdin")
        timeout = provider.get("timeout_s", 300)
        env = provider.get("env") or {}
        input_text = None
        tmp_path = None
        try:
            if prompt_via == "tempfile":
                handle = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".prompt.txt", delete=False, encoding="utf-8")
                handle.write(prompt)
                handle.close()
                tmp_path = handle.name
                argv = [part.replace("{promptfile}", tmp_path) for part in argv]
            else:
                input_text = prompt
            proc = self.run_fn(argv, input_text, timeout, env)
            return proc.returncode, (proc.stdout or ""), (proc.stderr or ""), False
        except subprocess.TimeoutExpired:
            # Distinguishable marker so run_mission can apply the auth-hang budget.
            return -1, "", f"timeout after {timeout}s", True
        except Exception as exc:  # OSError, etc. -> generic (non-timeout) failure
            return -1, "", f"{type(exc).__name__}: {exc}", False
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def default_providers() -> list[dict]:
    """gemini -> codex -> ollama -> claude, absolute paths via shutil.which.

    Providers whose binary is not on PATH at config time are skipped
    gracefully (None -> omit). Task 12 pins the real absolute paths in the
    launchd EnvironmentVariables/PATH so the nightly job (minimal PATH, no
    shell aliases) still resolves them.
    """
    entries: list[dict] = []

    gemini = shutil.which("gemini")
    if gemini:
        entries.append({
            "name": "gemini", "argv": [gemini, "-p", "@{promptfile}"],
            "prompt_via": "tempfile", "timeout_s": 300, "env": {},
        })

    codex = shutil.which("codex")
    if codex:
        entries.append({
            "name": "codex", "argv": [codex, "exec", "-"],
            "prompt_via": "stdin", "timeout_s": 300, "env": {},
        })

    ollama = shutil.which("ollama")
    if ollama:
        model = os.environ.get("LEGION_OLLAMA_MODEL", "gpt-oss:120b-cloud")
        entries.append({
            "name": "ollama", "argv": [ollama, "run", model],
            "prompt_via": "stdin", "timeout_s": 600, "env": {},
        })

    claude = shutil.which("claude")
    if claude:
        entries.append({
            "name": "claude", "argv": [claude, "-p"],
            "prompt_via": "stdin", "timeout_s": 300, "env": {},
        })

    return entries
