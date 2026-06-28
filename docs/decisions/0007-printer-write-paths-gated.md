# 0007 — Printer write-paths gated behind Dev-Mode config flags (default off)

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** mqtt, ams, config

## Context
Some actions write to the printer (k/PA calibration set, AMS unload, slot override) and may require
Developer Mode and carry risk. The core read+track workflow must work without any of them.

## Decision
We will **gate all printer write actions behind config flags that default to `false`**
(`ams.allow_k_write`, `ams.allow_unload`, …), returning **403** when disabled. The core read/track
pipeline requires no Developer Mode.

## Options considered
- **Option A — gated flags, default off (chosen):** safe by default, opt-in for risky writes.
- **Option B — writes always enabled:** unsafe; could disrupt prints / require Dev-Mode implicitly.

## Consequences
- Default install is read-only toward the printer.
- Enabling writes is a conscious, documented opt-in (capability matrix).

## References
- `docs/no-devmode-capability-matrix.md`; `docs/bambu-spoolman-bridge-concept.md` §5.5;
  `app/main.py` (`allow_k_write`/`allow_unload` defaults, `PermissionError` → 403).
