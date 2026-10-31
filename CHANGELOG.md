# Changelog

## v1.0.0 (2026-10-31)

First stable release. This version concludes the S0–S7 hardening plan
(70 catalogued issues from a full code & functional review — all resolved,
documented, or triaged to the roadmap).

### Data Integrity & Snapshots
- Snapshot stacks are now per-document: consecutive undo rolls back the
  correct document in multi-document workflows, with no duplicate documents.
- Lifecycle invariant enforced: a snapshot file exists on disk **iff** it is
  in a stack (restore deletes on success, pushes back on failure).
- `saveCopy`-based snapshots preserve `FileName`/`Label`/`isTouched`; untitled
  documents no longer get hijacked into saving over a snapshot file.
- Auto-fix retry failures no longer silently consume an undo level.
- Restore no longer forces the camera to isometric (fitAll only).

### Data Location & Migration
- User data moved out of the install directory to
  `<FreeCAD user data>/CadAgent/{sessions,snapshots,uploads,log}`
  (override: `CADAGENT_DATA_DIR`; existing data migrates automatically once).
- Log rotates at 5 MB with 3 backups.

### CQ Semantics (CadQuery alignment)
- `extrude(H)` rises from the workplane (z=0 → +H), **not** centered;
  `both=True` extrudes the full height symmetrically (z=-H → +H) for all
  sketch types.
- `Workplane("XZ"/"YZ")` fails honestly with reorientation guidance instead
  of silently building on XY; `origin=(x,y,z)` and `.workplane(offset=N)`
  are now honored.
- `cq_show` only manages objects it created (`cqobj_` Name prefix) —
  user objects with the same Label are never overwritten.

### Quality Gate & Self-Correction
- Structured topology issues with conservative fail on unknown codes;
  zero/tiny-volume detection; assembly-mode auto-downgrade for legitimate
  multi-part designs.
- Auto-fix results carry honest OK:/FAIL: first lines; all fixed code passes
  a compile gate before retry; shared `import cadquery` fixer no longer
  corrupts aliased imports.

### Agent Loop & Context
- Pi-inspired five-section compaction checkpoints and hybrid token
  estimation calibrated by provider usage.
- Steering queue: input sent mid-run is injected at the next LLM call
  boundary; stop no longer fakes success.
- Session store validates session ids (12-hex) before any filesystem access.

### UI Stability
- Per-turn state reset fixes the ReAct display wipe; steering input box;
  IME-composition-safe Enter; thread registry prevents Qt fatal destroys;
  link clicks restricted to http/https; safe HTML rendering (escaped cells,
  randomized sentinels); status bar shows the live parameter table.

### Security
- `SANDBOX_BUILTINS` renamed and documented as **not** a security boundary;
  Security Notes section added to both READMEs.

### Hygiene
- Dead code removed (~470 lines): unused LLM client functions, legacy
  single-shot prompts, controller dead fields, half-wired reasoning
  pipeline, duplicate InitGui activation blocks.
- AGENT/REACT prompts assembled from shared section constants
  (byte-identical to the previous text, drift-guarded by tests).

### Tests
- 576 → **693** unit tests plus a 30-check real-FreeCAD behavior regression
  script (`scripts/verify_freecad_behavior.py`).
