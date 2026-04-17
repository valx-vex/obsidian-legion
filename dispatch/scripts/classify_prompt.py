#!/usr/bin/env python3
from __future__ import annotations

import json
import os

from common import LOG_DIR, build_shadow_context, classify_prompt, parse_jsonish_stdin, persist_route_hint, write_jsonl


def main() -> int:
    payload = parse_jsonish_stdin()
    prompt = payload.get("prompt") or payload.get("raw") or json.dumps(payload, ensure_ascii=False)
    classification = classify_prompt(prompt)
    event = {
        "event": "UserPromptSubmit",
        "prompt_excerpt": prompt[:400],
        **classification,
    }

    persist_route_hint(event)
    write_jsonl(LOG_DIR / "route_decisions.jsonl", event)

    if os.environ.get("DISPATCH_USERPROMPT_CONTEXT", "true").lower() != "true":
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": build_shadow_context(classification),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
