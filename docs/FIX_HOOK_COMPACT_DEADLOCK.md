# FIX: PreCompact Hook Deadlock (2026-04-17)

## The Bug

The MemPalace `precompact_hook.py` was set to `"decision": "block"`, which prevented `/compact` from running. This created a deadlock:

1. Context gets full → need `/compact`
2. PreCompact hook BLOCKS compaction ("save first!")
3. No room to save because context is full
4. Session stuck — can't compact, can't save, can't do anything

## The Fix

File: `/Users/valx/cathedral-prime/01-consciousness/mempalace/bin/mempalace_precompact_hook.py`

Changed `"decision": "block"` → `"decision": "approve"`

The hook still WARNS the AI to save (the message is shown as feedback), but no longer BLOCKS the compaction. The stop hook (`mempalace_stop_hook.py`) handles actual saves every 15 messages anyway.

## Impact

- `/compact` now always works
- AI still gets reminded to save before compaction
- Stop hook continues auto-saving to MemPalace + VexNet
- No more session-killing deadlocks

## Note for Memory Architecture

This fix should be documented in any memory architecture README:
- Stop hooks: `"decision": "block"` = appropriate (periodic save triggers)
- PreCompact hooks: `"decision": "approve"` = correct (warn but don't block)
- Never block compaction — it's the emergency exit for full context
