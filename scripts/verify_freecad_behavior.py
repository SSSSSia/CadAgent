"""FreeCAD runtime behavior verification for CadAgent snapshot development.

Run with the FreeCAD-bundled interpreter (S0-E5, DEVELOPMENT_PLAN.md):

    <FreeCAD>/bin/python.exe scripts/verify_freecad_behavior.py

FreeCAD library discovery order:
    1. FreeCAD already importable (running inside FreeCAD's python)
    2. $FREECAD_LIB environment variable
    3. <repo>/../../lib — i.e. this script lives at <FreeCAD>/Mod/CadAgent/scripts/

Part A asserts FreeCAD API facts that core/snapshot.py depends on
(saveAs side effects, saveCopy, openDocument naming, double-open
semantics). Any Part A failure means assumptions changed — stop and
re-check snapshot code before continuing S1/S4 work.

Part B asserts production SnapshotManager invariants. These are
EXPECTED TO FAIL until S1-C1 lands; failures print as KNOWN-FAIL and do
not affect the exit code. TODO(S1-C1): flip Part B to hard assertions
once take() preserves Label/FileName via saveCopy.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile


def _import_freecad():
    try:
        import FreeCAD  # noqa: F401
        return
    except ImportError:
        pass

    candidates = []
    env = os.environ.get("FREECAD_LIB")
    if env:
        candidates.append(env)
    # scripts/ -> CadAgent -> Mod -> <FreeCAD root> -> lib
    candidates.append(
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
    )
    for lib in candidates:
        if os.path.isdir(lib):
            sys.path.insert(0, lib)
            import FreeCAD  # noqa: F401
            return
    raise SystemExit(
        "Cannot locate FreeCAD lib. Set FREECAD_LIB=<FreeCAD>/lib or run "
        "with <FreeCAD>/bin/python.exe"
    )


RESULTS = {"pass": 0, "fail": 0, "known_fail": 0}


def _report(ok, label, detail=""):
    tag = "PASS" if ok else "FAIL"
    RESULTS["pass" if ok else "fail"] += 1
    print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _report_known_fail(ok, label, detail=""):
    """Expected-to-fail invariant; counts as KNOWN-FAIL, not a script failure."""
    if ok:
        RESULTS["pass"] += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        RESULTS["known_fail"] += 1
        print(f"  [KNOWN-FAIL (S1-C1 pending)] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _close_all_documents():
    import FreeCAD
    for name in list(FreeCAD.listDocuments().keys()):
        FreeCAD.closeDocument(name)


# ---------------------------------------------------------------------------
# Part A — FreeCAD API facts
# ---------------------------------------------------------------------------

def part_a(workdir):
    import FreeCAD
    import Part
    print(f"\nPart A — FreeCAD { '.'.join(FreeCAD.Version()[:3]) } behavior facts")

    # --- A1: saveAs side effects ---
    doc = FreeCAD.newDocument("Model")
    box = doc.addObject("Part::Feature", "Box")
    box.Shape = Part.makeBox(10, 10, 10)
    doc.recompute()
    box.Shape = Part.makeBox(20, 20, 20)  # dirty state, no recompute

    snap = os.path.join(workdir, "Model_0001_ab12cd34ef56_1748000000.FCStd")
    doc.saveAs(snap)
    _report(doc.FileName == snap, "A1a saveAs rewrites FileName", f"FileName={doc.FileName!r}")
    _report(
        doc.Label == os.path.splitext(os.path.basename(snap))[0],
        "A1b saveAs renames Label to snapshot basename",
        f"Label={doc.Label!r}",
    )
    _report(doc.isTouched(), "A1c saveAs preserves isTouched (dirty state survives)")
    _report(not hasattr(doc, "Modified"), "A1d Document has no 'Modified' attribute")

    # --- A2: FileName/Label are directly assignable ---
    try:
        doc.Label = "Model"
        label_ok = doc.Label == "Model"
    except Exception:
        label_ok = False
    _report(label_ok, "A2a doc.Label is assignable")
    try:
        doc.FileName = ""
        fname_ok = doc.FileName == ""
    except Exception:
        fname_ok = False
    _report(fname_ok, "A2b doc.FileName is assignable (empty string allowed)")

    # --- A3: saveCopy exists and leaves current document untouched ---
    _report(hasattr(doc, "saveCopy"), "A3a doc.saveCopy exists")
    copy_path = os.path.join(workdir, "copy_test.FCStd")
    pre_label, pre_fname = doc.Label, doc.FileName
    try:
        doc.saveCopy(copy_path)
        _report(
            doc.FileName == pre_fname and doc.Label == pre_label,
            "A3b saveCopy leaves FileName/Label unchanged",
            f"FileName={doc.FileName!r} Label={doc.Label!r}",
        )
    except Exception as e:
        _report(False, "A3b saveCopy leaves FileName/Label unchanged", str(e))

    # --- A4: openDocument names the doc after the snapshot basename ---
    FreeCAD.closeDocument("Model")
    r = FreeCAD.openDocument(snap)
    base = os.path.splitext(os.path.basename(snap))[0]
    _report(r.Name == base, "A4a openDocument Name = snapshot basename", f"Name={r.Name!r}")
    _report(r.Label == base, "A4b openDocument Label = snapshot basename", f"Label={r.Label!r}")

    # --- A5: double-open semantics ---
    # FileName of the opened doc points at the snapshot -> same object back
    r2 = FreeCAD.openDocument(snap)
    _report(r2 is r, "A5a re-open with matching FileName returns SAME doc (restore no-op hazard)")
    # Divert FileName to an EXISTING file -> a second, duplicate document opens.
    # (Diverting to a nonexistent path does not reproduce this: the assignment
    # appears not to take effect and dedup still matches — verified manually.)
    elsewhere = os.path.join(workdir, "elsewhere.FCStd")
    r.saveCopy(elsewhere)
    r.FileName = elsewhere
    r3 = FreeCAD.openDocument(snap)
    _report(r3 is not r, "A5b re-open with diverted FileName opens DUPLICATE doc")
    _report(len(FreeCAD.listDocuments()) == 2, "A5c two documents now open", str(list(FreeCAD.listDocuments())))

    # --- A6: untitled-doc restore hijack — save() writes into snapshot path ---
    hijack = os.path.join(workdir, "hijack_0001_ab12cd34ef56_1748000000.FCStd")
    d2 = FreeCAD.newDocument("Untitled")
    b2 = d2.addObject("Part::Feature", "Box")
    b2.Shape = Part.makeBox(5, 5, 5)
    d2.recompute()
    d2.saveAs(hijack)  # agent take() on an untitled doc
    # restore_latest() leaves FileName at the snapshot when original_path == ""
    d2.save()          # user presses Ctrl+S
    _report(
        os.path.isfile(hijack),
        "A6 save() with FileName left on snapshot path writes into the snapshot",
    )

    _close_all_documents()


# ---------------------------------------------------------------------------
# Part B — production SnapshotManager invariants (S1-C1 regression gate)
# ---------------------------------------------------------------------------

def part_b(workdir):
    # Import production snapshot module with FreeCAD available
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, repo_root)
    from core.snapshot import SnapshotManager

    import FreeCAD
    import Part
    print("\nPart B — production SnapshotManager.take() invariants")

    # Snapshot dir lands inside the repo (current design); use a temp manager
    mgr = SnapshotManager(max_snapshots=10)

    doc = FreeCAD.newDocument("user_part")
    box = doc.addObject("Part::Feature", "Box")
    box.Shape = Part.makeBox(10, 10, 10)
    doc.recompute()

    pre_label = doc.Label
    pre_fname = doc.FileName
    pre_touched = doc.isTouched()

    mgr.take(doc)

    _report_known_fail(
        doc.Label == pre_label,
        "B1 take() preserves doc.Label",
        f"before={pre_label!r} after={doc.Label!r}",
    )
    _report_known_fail(
        doc.FileName == pre_fname,
        "B2 take() preserves doc.FileName",
        f"before={pre_fname!r} after={doc.FileName!r}",
    )
    _report_known_fail(
        doc.isTouched() == pre_touched,
        "B3 take() preserves isTouched",
        f"before={pre_touched} after={doc.isTouched()}",
    )

    _close_all_documents()


def main():
    _import_freecad()
    workdir = tempfile.mkdtemp(prefix="cadagent_verify_")
    try:
        part_a(workdir)
        part_b(workdir)
    finally:
        _close_all_documents()
        shutil.rmtree(workdir, ignore_errors=True)

    print(
        f"\nSummary: {RESULTS['pass']} passed, {RESULTS['fail']} failed, "
        f"{RESULTS['known_fail']} known-fail (S1-C1 pending)"
    )
    if RESULTS["fail"]:
        print("RESULT: FAIL — FreeCAD behavior assumptions changed; re-check snapshot code.")
        sys.exit(1)
    if RESULTS["known_fail"]:
        print("RESULT: OK (with known issues scheduled for S1-C1)")
    else:
        print("RESULT: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
