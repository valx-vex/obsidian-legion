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

# The elected Ollama-cloud model (D4); overridable via LEGION_OLLAMA_MODEL.
DEFAULT_WIKI_MODEL = "minimax-m3:cloud"

# HTTP statuses meaning "this cloud provider is done for the whole run": a
# lapsed subscription or a rate limit fails every page, so retire once. The
# http _invoke maps these to a stderr string containing 'quota', which the
# existing QUOTA_PATTERNS substring check then retires run-wide.
QUOTA_STATUS_CODES = (401, 402, 403, 429)


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
    def __init__(self, providers: list[dict], run_fn=None, http_client=None) -> None:
        self.providers = list(providers or [])
        self.run_fn = run_fn or _default_run_fn
        # Injected httpx.Client for tests (built with httpx.MockTransport). When
        # None, _invoke_http / _preflight_http build a per-call client and close
        # it; the injected one is left open for the caller/test to manage.
        self._http_client = http_client
        self.dead_providers: set[str] = set()
        # Consecutive-timeout counter per provider, persisted across missions
        # within a run: an unauthenticated interactive provider that hangs is
        # retired dead-for-run after 2 back-to-back timeouts (auth-hang budget).
        self._timeout_counts: dict[str, int] = {}

    def preflight(self) -> dict[str, bool]:
        flags: dict[str, bool] = {}
        for provider in self.providers:
            if provider.get("kind") == "http":
                flags[provider["name"]] = self._preflight_http(provider)
                continue
            argv = provider.get("argv") or []
            binary = argv[0] if argv else ""
            flags[provider["name"]] = bool(binary) and os.path.exists(binary) and \
                os.access(binary, os.X_OK)
        return flags

    def _preflight_http(self, provider: dict) -> bool:
        # Both probes are purely local (spec §4.1): a lapsed cloud subscription
        # is NOT detected here — only at the first /api/chat, which then retires
        # the provider run-wide. Any exception -> not ready.
        import httpx

        url = str(provider.get("url", "http://localhost:11434")).rstrip("/")
        model = provider.get("model", "")
        client = self._http_client or httpx.Client(timeout=5)
        owns = self._http_client is None
        try:
            version = client.get(f"{url}/api/version", timeout=5)
            if version.status_code != 200:
                return False
            tags = client.get(f"{url}/api/tags", timeout=5)
            if tags.status_code != 200:
                return False
            names = [m.get("name") for m in tags.json().get("models", [])]
            return model in names
        except Exception:
            return False
        finally:
            if owns:
                client.close()

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
        if provider.get("kind") == "http":
            return self._invoke_http(provider, prompt)
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

    def _invoke_http(self, provider: dict, prompt: str):
        import httpx

        url = str(provider.get("url", "http://localhost:11434")).rstrip("/")
        model = provider.get("model", "")
        timeout = provider.get("timeout_s", 600)
        client = self._http_client or httpx.Client(timeout=timeout)
        owns = self._http_client is None
        try:
            resp = client.post(
                f"{url}/api/chat",
                json={"model": model,
                      "messages": [{"role": "user", "content": prompt}],
                      "stream": False},
            )
            status = resp.status_code
            if status == 200:
                # message.thinking is NEVER read — reasoning is discarded by
                # construction (spec §4.1); the sanitizer is defense-in-depth.
                return (0, resp.json()["message"]["content"] or "", "", False)
            if status in QUOTA_STATUS_CODES:
                # 'quota' in the text makes QUOTA_PATTERNS retire it run-wide.
                return (-1, "", f"http {status}: quota/auth", False)
            return (-1, "", f"http {status}: {resp.text[:200]}", False)
        except httpx.TimeoutException:
            return (-1, "", f"timeout after {timeout}s", True)
        except Exception as exc:
            return (-1, "", f"{type(exc).__name__}: {exc}", False)
        finally:
            if owns:
                client.close()


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
        model = os.environ.get("LEGION_OLLAMA_MODEL", DEFAULT_WIKI_MODEL)
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


def wiki_providers() -> list[dict]:
    """VEXPEDIA wiki chain: ollama-over-HTTP first, then the CLI fallbacks.

    The elected Ollama-cloud model IS the author (spec §4.2); gemini/codex/
    claude are resilience fallbacks only. Reuses default_providers() for the
    CLI entries (absent binaries skipped) and drops its ollama CLI entry — the
    HTTP entry supersedes it here.
    """
    url = os.environ.get("LEGION_OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("LEGION_OLLAMA_MODEL", DEFAULT_WIKI_MODEL)
    entries: list[dict] = [{
        "name": "ollama", "kind": "http", "url": url,
        "model": model, "timeout_s": 600,
    }]
    entries += [e for e in default_providers() if e["name"] != "ollama"]
    return entries
