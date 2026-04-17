#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from common import (
    LOG_DIR,
    classify_prompt,
    dispatch_to_codex,
    dispatch_to_gemini,
    load_dispatch_policy,
    ollama_chat,
    submit_n8n_job,
    write_jsonl,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-LLM dispatcher for Obsidian Legion")
    parser.add_argument("prompt", nargs="+", help="Prompt to dispatch")
    parser.add_argument("--route", choices=["auto", "claude", "ollama", "gemini", "codex", "n8n"], default="auto")
    parser.add_argument("--cwd", default=None, help="Working directory for CLI-backed workers")
    parser.add_argument("--workflow", default="dispatch-default", help="n8n workflow name for phase 2 testing")
    parser.add_argument("--ollama-model", default=None)
    parser.add_argument("--system", default="")
    parser.add_argument("--output-schema", default=None)
    args = parser.parse_args()

    prompt = " ".join(args.prompt)
    classification = classify_prompt(prompt)
    selected_route = args.route if args.route != "auto" else classification["route_hint"]
    policy = load_dispatch_policy()

    if selected_route == "ollama":
        result = ollama_chat(prompt, model=args.ollama_model, system=args.system)
    elif selected_route == "gemini":
        result = dispatch_to_gemini(prompt, cwd=args.cwd)
    elif selected_route == "codex":
        result = dispatch_to_codex(prompt, cwd=args.cwd, output_schema=args.output_schema)
    elif selected_route == "n8n":
        result = submit_n8n_job(args.workflow, {"prompt": prompt, "cwd": args.cwd, "classification": classification})
    else:
        result = {
            "ok": True,
            "worker": "claude",
            "content": "Route resolved to Claude. This dispatcher does not proxy Claude automatically.",
        }

    write_jsonl(
        LOG_DIR / "dispatch_runs.jsonl",
        {
            "prompt_excerpt": prompt[:300],
            "route_requested": args.route,
            "route_selected": selected_route,
            "classification": classification,
            "policy_path": policy.get("path"),
            "result_ok": result.get("ok", False),
            "worker": result.get("worker"),
            "stderr": result.get("stderr", ""),
        },
    )

    print(
        json.dumps(
            {
                "policy_path": policy.get("path"),
                "route_selected": selected_route,
                "classification": classification,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
