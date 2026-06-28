# 0005 — Spoolman is the system of record; community extra-fields; restore native location on unload

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** spoolman, db

## Context
The bridge maps physical AMS spools to Spoolman and must interoperate with the community
(OpenSpoolMan / BambuSpoolPal) while keeping Spoolman authoritative for filament/spool data.

## Decision
We will keep **Spoolman as the system of record** for filament/spool data. The bridge stores the RFID
UID in the Spoolman extra-field **`tag`** and the current slot in **`active_tray`** (community
convention), and **restores the spool's prior native `location`** on unload. The bridge's SQLite DB
holds only mappings/state/cache.

## Options considered
- **Option A — Spoolman SoR + `tag`/`active_tray` extras (chosen):** interop with existing tools,
  no duplicate source of truth.
- **Option B — bridge-owned spool database:** diverges from Spoolman, breaks interop.

## Consequences
- Field names are a contract (`tag`, `active_tray`); not `bambu_rfid`/`location` for the tag/slot.
- On unload, the spool returns to its previous location (or storage default).

## References
- `docs/api-guideline.md` (extra-fields); `docs/bambu-spoolman-bridge-concept.md` §4.2;
  `docs/database-guideline.md` (Spoolman = SoR); `app/main.py` (`set_active_tray`/`set_location`,
  unload restore).
