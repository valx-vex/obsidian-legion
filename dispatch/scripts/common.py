#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


BUNDLE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = BUNDLE_DIR / "router" / "dispatch-matrix.yaml"
LOG_DIR = Path(os.environ.get("DISPATCH_LOG_DIR", str(BUNDLE_DIR / ".logs"))).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
ROUTE_HINT_FILE = LOG_DIR / "route_hint.json"

# Maximum timeout for any subprocess dispatch (seconds).
MAX_TIMEOUT = 60


def now_ts() -> float:
    return time.time()


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return (BUNDLE_DIR / path).resolve()


def write_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_jsonish_stdin() -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {"raw": ""}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {"raw": raw, "value": data}
    except Exception:
        return {"raw": raw}


def persist_route_hint(hint: Dict[str, Any]) -> None:
    write_json(ROUTE_HINT_FILE, hint)


def load_route_hint() -> Dict[str, Any]:
    if not ROUTE_HINT_FILE.exists():
        return {}
    try:
        return json.loads(ROUTE_HINT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_scalar(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered.isdigit():
        return int(lowered)
    try:
        return float(lowered)
    except ValueError:
        pass
    return value.strip()


def _parse_simple_policy(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {"routes": {}}
    in_routes = False
    current_route: Optional[str] = None
    current_list: Optional[str] = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        if raw_line.startswith("routes:"):
            in_routes = True
            current_route = None
            current_list = None
            continue

        if not in_routes:
            if ":" in raw_line:
                key, value = raw_line.split(":", 1)
                data[key.strip()] = _parse_scalar(value)
            continue

        route_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", raw_line)
        if route_match:
            current_route = route_match.group(1)
            data["routes"][current_route] = {}
            current_list = None
            continue

        if current_route is None:
            continue

        list_match = re.match(r"^    ([A-Za-z0-9_-]+):\s*$", raw_line)
        if list_match:
            current_list = list_match.group(1)
            data["routes"][current_route][current_list] = []
            continue

        item_match = re.match(r"^      - (.+)$", raw_line)
        if item_match and current_list:
            data["routes"][current_route][current_list].append(item_match.group(1).strip())
            continue

        scalar_match = re.match(r"^    ([A-Za-z0-9_-]+):\s*(.+)$", raw_line)
        if scalar_match:
            key = scalar_match.group(1).strip()
            value = scalar_match.group(2).strip()
            data["routes"][current_route][key] = _parse_scalar(value)
            current_list = None

    return data


def load_dispatch_policy() -> Dict[str, Any]:
    configured = os.environ.get("DISPATCH_POLICY_PATH", str(DEFAULT_POLICY_PATH))
    path = resolve_path(configured)
    if not path.exists():
        return {"path": str(path), "version": None, "mode": "missing", "pilot_phase": None, "routes": {}}

    text = path.read_text(encoding="utf-8")
    parsed: Dict[str, Any]
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text) or {}
    except Exception:
        parsed = _parse_simple_policy(text)

    if not isinstance(parsed, dict):
        parsed = {"routes": {}}

    parsed.setdefault("routes", {})
    parsed["path"] = str(path)
    return parsed


TASK_CAPABILITY_MAP = {
    "summary": ["summarization", "rewriting", "wiki_normalization", "low_risk_transforms"],
    "research": ["repo_research", "long_context_analysis", "broad_document_questions"],
    "code": ["bounded_implementation", "patch_generation", "refactor_attempts"],
    "complex": ["architecture", "acceptance_review", "risky_refactors", "ambiguous_debugging"],
}

# Minimum confidence score to route to a non-Claude worker.
CONFIDENCE_THRESHOLD = float(os.environ.get("DISPATCH_CONFIDENCE_THRESHOLD", "0.35"))

# Minimum keyword length to consider during classification.
MIN_KEYWORD_LENGTH = 2


def _route_from_policy(task_type: str, policy: Dict[str, Any]) -> Optional[str]:
    wanted = set(TASK_CAPABILITY_MAP.get(task_type, []))
    for route_name, route_data in policy.get("routes", {}).items():
        if route_name == "n8n" and not route_data.get("pilot_enabled", False):
            continue
        use_for = set(route_data.get("use_for", []) or [])
        if wanted & use_for:
            return route_name
    return None


def _fallback_route(task_type: str) -> str:
    if task_type == "summary":
        return os.environ.get("ROUTE_DEFAULT_SIMPLE", "ollama")
    if task_type == "research":
        return os.environ.get("ROUTE_DEFAULT_RESEARCH", "gemini")
    if task_type == "code":
        return os.environ.get("ROUTE_DEFAULT_CODE", "codex")
    return os.environ.get("ROUTE_DEFAULT_COMPLEX", "claude")


def classify_prompt(prompt: str) -> Dict[str, Any]:
    text = prompt.lower().strip()
    score = 0.0
    signals: List[str] = []

    def match_any(words: Iterable[str]) -> bool:
        # Bug fix: skip keywords shorter than MIN_KEYWORD_LENGTH to avoid
        # false-positive substring matches on single characters.
        return any(
            word in text
            for word in words
            if len(word) >= MIN_KEYWORD_LENGTH
        )

    if match_any(["architecture", "tradeoff", "design", "risky", "root cause", "ambiguous", "acceptance review"]):
        score += 0.7
        signals.append("complex_keywords")
    if match_any(["implement", "patch", "refactor", "write code", "fix bug", "test", "update code"]):
        score += 0.55
        signals.append("code_keywords")
    if match_any(["research", "investigate", "analyze repo", "repo-wide", "compare", "scan", "find all", "long context"]):
        score += 0.45
        signals.append("research_keywords")
    if match_any(["summarize", "rewrite", "draft", "format", "clean up", "normalize", "wiki"]):
        score -= 0.4
        signals.append("summary_keywords")
    if len(prompt) > 1800:
        score += 0.35
        signals.append("long_prompt")
    if len(re.findall(r"```", prompt)) >= 2:
        score += 0.2
        signals.append("multi_block_prompt")

    if match_any(["summarize", "rewrite", "draft", "normalize", "wiki", "paraphrase", "format"]):
        task_type = "summary"
    elif match_any(["research", "investigate", "analyze", "repo-wide", "find all", "compare", "scan", "long context"]):
        task_type = "research"
    elif match_any(["implement", "patch", "refactor", "write code", "fix", "test", "modify code"]):
        task_type = "code"
    elif score >= 0.75:
        task_type = "complex"
    else:
        task_type = "complex" if score >= 0.5 else "summary"

    complexity_score = round(max(0.0, min(1.0, score + 0.5)), 3)

    policy = load_dispatch_policy()
    route_hint = _route_from_policy(task_type, policy) or _fallback_route(task_type)

    # Bug fix: if confidence is below threshold, fall back to Claude
    # instead of routing to a cheaper worker that may produce poor results.
    if complexity_score < CONFIDENCE_THRESHOLD and route_hint != "claude":
        route_hint = "claude"
        signals.append("below_confidence_threshold")

    return {
        "route_hint": route_hint,
        "task_type": task_type,
        "complexity_score": complexity_score,
        "policy_path": policy.get("path"),
        "signals": signals,
    }


def build_shadow_context(classification: Dict[str, Any]) -> str:
    return (
        "[Dispatch shadow hint] "
        f"suggested_route={classification['route_hint']} "
        f"task_type={classification['task_type']} "
        f"complexity_score={classification['complexity_score']} "
        f"policy={classification.get('policy_path', '')}. "
        "This is review-bundle logic and should not be treated as live enforcement."
    )


def run_command(
    argv: List[str],
    cwd: Optional[str] = None,
    input_text: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    # Enforce ceiling so callers cannot exceed MAX_TIMEOUT.
    timeout = min(timeout, MAX_TIMEOUT)
    started = now_ts()
    try:
        proc = subprocess.run(
            argv,
            input=input_text,
            text=True,
            capture_output=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed_s": round(now_ts() - started, 3),
            "argv": argv,
            "cwd": cwd,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": f"Command not found: {argv[0]}",
            "elapsed_s": round(now_ts() - started, 3),
            "argv": argv,
            "cwd": cwd,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "returncode": 124,
            "stdout": stdout,
            "stderr": stderr + f"\nTimed out after {timeout}s",
            "elapsed_s": round(now_ts() - started, 3),
            "argv": argv,
            "cwd": cwd,
        }


def parse_json_maybe(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def http_probe(url: str, timeout: int = 3) -> Dict[str, Any]:
    started = now_ts()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(300).decode("utf-8", "replace")
            return {
                "ok": True,
                "url": url,
                "status": response.status,
                "content_type": response.headers.get_content_type(),
                "body_preview": body.replace("\n", " ")[:300],
                "elapsed_s": round(now_ts() - started, 3),
            }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "url": url,
            "error": repr(exc),
            "elapsed_s": round(now_ts() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "error": repr(exc),
            "elapsed_s": round(now_ts() - started, 3),
        }


def ollama_chat(prompt: str, model: Optional[str] = None, system: str = "") -> Dict[str, Any]:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = model or os.environ.get("OLLAMA_MODEL_DEFAULT", "llama3.2:3b")
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            *([{"role": "system", "content": system}] if system else []),
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = now_ts()
    try:
        with urllib.request.urlopen(request, timeout=MAX_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "ok": True,
            "worker": "ollama",
            "model": model,
            "content": content,
            "raw": body,
            "elapsed_s": round(now_ts() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "worker": "ollama",
            "model": model,
            "content": "",
            "error": str(exc),
            "elapsed_s": round(now_ts() - started, 3),
        }


def dispatch_to_gemini(prompt: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    gemini_bin = os.environ.get("GEMINI_CLI_BIN", "gemini")
    result = run_command([gemini_bin, "-p", prompt, "--output-format", "json"], cwd=cwd, timeout=MAX_TIMEOUT)
    return {
        "ok": result["ok"],
        "worker": "gemini",
        "content": result["stdout"].strip(),
        "parsed": parse_json_maybe(result["stdout"]),
        "stderr": result["stderr"],
        "meta": result,
    }


def dispatch_to_codex(prompt: str, cwd: Optional[str] = None, output_schema: Optional[str] = None) -> Dict[str, Any]:
    codex_bin = os.environ.get("CODEX_CLI_BIN", "codex")
    argv = [codex_bin, "exec"]
    if output_schema:
        argv.extend(["--output-schema", output_schema])
    result = run_command(argv, cwd=cwd, input_text=prompt, timeout=MAX_TIMEOUT)
    return {
        "ok": result["ok"],
        "worker": "codex",
        "content": result["stdout"].strip(),
        "stderr": result["stderr"],
        "meta": result,
    }


def submit_n8n_job(workflow: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = os.environ.get("N8N_WEBHOOK_URL", "").strip()
    if not url:
        return {"ok": False, "worker": "n8n", "error": "N8N_WEBHOOK_URL is not set"}

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("N8N_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url,
        data=json.dumps({"workflow": workflow, "payload": payload}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = now_ts()
    try:
        with urllib.request.urlopen(request, timeout=MAX_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
        return {
            "ok": True,
            "worker": "n8n",
            "content": parse_json_maybe(raw) or {"raw": raw},
            "elapsed_s": round(now_ts() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "worker": "n8n",
            "error": str(exc),
            "elapsed_s": round(now_ts() - started, 3),
        }


# --- Failback Chain ---

FAILBACK_ORDER = ["ollama", "codex", "gemini", "claude"]


def dispatch_with_failback(prompt: str, cwd: str | None = None) -> dict[str, Any]:
    """Try each provider in order until one succeeds."""
    dispatchers = {
        "ollama": lambda: ollama_chat(prompt),
        "codex": lambda: dispatch_to_codex(prompt, cwd=cwd),
        "gemini": lambda: dispatch_to_gemini(prompt, cwd=cwd),
        "claude": lambda: {"ok": True, "worker": "claude", "content": "(kept by Claude — no dispatch)"},
    }
    errors: list[str] = []
    for provider in FAILBACK_ORDER:
        fn = dispatchers.get(provider)
        if fn is None:
            continue
        result = fn()
        if result.get("ok"):
            result["failback_tried"] = errors
            write_jsonl(LOG_DIR / "dispatch_runs.jsonl", {
                "ts": now_ts(), "prompt_len": len(prompt),
                "winner": provider, "tried": errors,
            })
            return result
        errors.append(f"{provider}: {result.get('error', 'unknown')}")
    return {"ok": False, "worker": "none", "errors": errors, "content": ""}


# --- PING/PONG Test ---


def ping_all_providers() -> dict[str, Any]:
    """Test all dispatch targets with a simple hello prompt."""
    test_prompt = "Say hello in exactly one sentence."
    results: dict[str, Any] = {}

    # Ollama
    try:
        r = ollama_chat(test_prompt)
        results["ollama"] = {"ok": r["ok"], "response": r.get("content", "")[:100], "elapsed": r.get("elapsed_s")}
    except Exception as e:
        results["ollama"] = {"ok": False, "error": str(e)}

    # Codex
    try:
        r = dispatch_to_codex(test_prompt)
        results["codex"] = {"ok": r["ok"], "response": r.get("content", "")[:100]}
    except Exception as e:
        results["codex"] = {"ok": False, "error": str(e)}

    # Gemini
    try:
        r = dispatch_to_gemini(test_prompt)
        results["gemini"] = {"ok": r["ok"], "response": r.get("content", "")[:100]}
    except Exception as e:
        results["gemini"] = {"ok": False, "error": str(e)}

    return results
