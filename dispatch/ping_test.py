#!/usr/bin/env python3
"""PING all dispatch targets — test that each provider responds."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scripts.common import ping_all_providers

def main():
    print("🏓 PING/PONG Test — Multi-LLM Dispatch")
    print("=" * 50)

    results = ping_all_providers()

    all_ok = True
    for provider, result in results.items():
        status = "✅ PONG" if result.get("ok") else "❌ FAIL"
        print(f"\n{provider.upper():>8}: {status}")
        if result.get("ok"):
            response = result.get("response", "")
            elapsed = result.get("elapsed", "?")
            print(f"          Response: {response}")
            print(f"          Time: {elapsed}s")
        else:
            print(f"          Error: {result.get('error', 'unknown')}")
            all_ok = False

    print("\n" + "=" * 50)
    online = sum(1 for r in results.values() if r.get("ok"))
    print(f"Result: {online}/{len(results)} providers online")

    if all_ok:
        print("🎯 All systems operational. Ready for dispatch!")
    else:
        print("⚠️  Some providers unavailable. Failback chain will skip them.")

    return 0 if all_ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
