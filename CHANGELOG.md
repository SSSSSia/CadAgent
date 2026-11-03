# Changelog

## v1.3.0 (2026-11-03)

`Workplane("XZ")` and `Workplane("YZ")` now build geometry on those planes.
A sketch extrudes along the CadQuery normal: XY +Z, XZ −Y, YZ +X. `origin`
stays in global coordinates, and `.workplane(offset)` moves along that normal.
Holes, shell, and the default revolve axis use the same frame.

- **Planes**: box, cylinder, cone, sphere, torus, and extrude are oriented
  with the plane. Unknown names such as `"front"` still raise.
- **Streaming**: LLM reads no longer mark the socket timed-out, so a slow
  first byte does not abort the turn. Stop still closes the socket.
- **Chat**: a failed tool is one line in the panel. Expected execute
  failures are not FreeCAD `PrintError` popups.
- **Vessels**: a labeled cup or bowl that is only an open tube does not
  pass as finished. `.loft()`, `.faces()`, and `.cutThruAll()` are rejected
  before execution.
- Tests: 776 (mock suite). The FreeCAD behavior script is 44 checks,
  including the new plane orientation cases, and passed on FreeCAD 1.1.1.

## v1.2.0 (2026-11-03)

Modeling primitives and the engineering pass. CadQuery-style code can now
array holes, revolve a closed profile, shell a plain box or cylinder, and
fillet or chamfer selected edges. Stopping a turn no longer waits out the
full network timeout, and the panel follows Chinese when FreeCAD (or
`CADAGENT_LANG`) does.

- **Workplane**: `polarArray` / `rarray`, `hole` / `cboreHole`, `revolve`
  (with `moveTo` / `lineTo` / `threePointArc` / `close`), `shell` limited to
  a plain box or cylinder, and `fillet` / `chamfer` with an edge selector.
- **Parameters**: a column-0 `NAME = number` anywhere in a segment is
  extracted. Successful code history keeps the newest 50 segments
  (`MAX_CODE_HISTORY`) and says so when a rebuild drops older ones.
- **Stop**: LLM reads use one-second socket slices. Stop keeps the partial
  reply and marks the turn interrupted.
- **UI language**: `ui/strings.py` (`en` / `zh`), `CADAGENT_LANG` overrides
  the FreeCAD language preference.
- **CI**: GitHub Actions runs compileall, ruff (E/W/F, line length 100, no
  import sorting), and the mock pytest suite. The FreeCAD behavior script
  stays a local gate.
- Tests: 758 (mock suite, no FreeCAD).

## v1.1.0 (2026-10-31)

Parametric regeneration (ROADMAP 12.2): the parameter contract is now a
closed loop — edit values in the UI and the model rebuilds deterministically,
without an LLM call.

- **Code history**: every successfully executed `execute_code` segment is
  recorded (with its target document) and persisted with the session,
  replacing the never-populated `parametric_code` placeholder.
- **Rebuild engine** (`rebuild_with_params`): snapshots all involved
  documents first (rebuild is undoable; failures roll everything back),
  removes only cq_show-owned objects (user geometry untouched), replays the
  history with the new parameter values, and runs the CAD quality gate.
  Cross-segment variable continuity is preserved.
- **ƒ(x) button + parameter dialog**: editable table of the extracted
  parameters; invalid values are rejected in-dialog; running agent blocks
  rebuild with a clear message.
- Regression gate: the real-FreeCAD verification script gained Part D
  (build → rebuild OD 40→60 → undo → user object survives), now 35 checks.
- Tests: 693 → 714.

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
