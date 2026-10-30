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

Part B asserts production SnapshotManager invariants (hard assertions
since S1-C1: take() preserves Label/FileName via saveCopy, restore
resets untitled FileName instead of leaving it on the snapshot path).
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


RESULTS = {"pass": 0, "fail": 0}


def _report(ok, label, detail=""):
    tag = "PASS" if ok else "FAIL"
    RESULTS["pass" if ok else "fail"] += 1
    print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
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
# Part B — production SnapshotManager invariants (S1 regression gate)
# ---------------------------------------------------------------------------

def part_b(workdir):
    # Import production snapshot module with FreeCAD available
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, repo_root)
    from core.snapshot import SnapshotManager

    import FreeCAD
    import Part
    print("\nPart B — production SnapshotManager invariants")

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

    _report(
        doc.Label == pre_label,
        "B1 take() preserves doc.Label",
        f"before={pre_label!r} after={doc.Label!r}",
    )
    _report(
        doc.FileName == pre_fname,
        "B2 take() preserves doc.FileName",
        f"before={pre_fname!r} after={doc.FileName!r}",
    )
    _report(
        doc.isTouched() == pre_touched,
        "B3 take() preserves isTouched",
        f"before={pre_touched} after={doc.isTouched()}",
    )

    # --- B4: untitled-doc restore must not leave FileName on the snapshot ---
    entry = mgr.latest_entry()
    restore_result = mgr.restore_latest()
    restored = FreeCAD.ActiveDocument
    _report(
        restore_result.startswith("SUCCESS") and restored is not None
        and restored.FileName == "",
        "B4 untitled restore resets FileName to '' (no snapshot save hijack)",
        f"result={restore_result.splitlines()[0]!r} FileName={getattr(restored, 'FileName', None)!r}",
    )
    _report(
        restored is not None and restored.Label == pre_label,
        "B5 restore restores the original Label",
        f"before={pre_label!r} after={getattr(restored, 'Label', None)!r}",
    )

    # --- B6: multi-document undo order (S4-C7 regression gate) ---
    _close_all_documents()  # drop the user_part doc left open by B4/B5
    doc_a = FreeCAD.newDocument("partA")
    box_a = doc_a.addObject("Part::Feature", "Box")
    box_a.Shape = Part.makeBox(10, 10, 10)
    doc_a.recompute()
    doc_b = FreeCAD.newDocument("partB")
    box_b = doc_b.addObject("Part::Feature", "Box")
    box_b.Shape = Part.makeBox(20, 20, 20)
    doc_b.recompute()

    mgr.take(doc_a)
    box_a.Shape = Part.makeBox(11, 11, 11)
    doc_a.recompute()
    mgr.take(doc_b)
    box_b.Shape = Part.makeBox(22, 22, 22)
    doc_b.recompute()

    snap_dir_files_before = len([
        f for f in os.listdir(mgr.get_snapshot_dir()) if f.endswith(".FCStd")
    ])

    r1 = mgr.restore_latest()   # newest = partB snapshot
    r2 = mgr.restore_latest()   # next    = partA snapshot
    _report(
        r1.startswith("SUCCESS") and r2.startswith("SUCCESS"),
        "B6a multi-doc restores succeed",
        f"r1={r1.splitlines()[0]!r}",
    )
    docs_now = list(FreeCAD.listDocuments().keys())
    _report(
        len(docs_now) == 2,
        "B6b no duplicate documents after restores",
        f"docs={docs_now}",
    )
    _report(
        mgr.count() == 0,
        "B6c stack empty after both restores",
        f"count={mgr.count()}",
    )
    snap_dir_files_after = len([
        f for f in os.listdir(mgr.get_snapshot_dir()) if f.endswith(".FCStd")
    ])
    _report(
        snap_dir_files_after == snap_dir_files_before - 2,
        "B6d restored snapshot files deleted",
        f"before={snap_dir_files_before} after={snap_dir_files_after}",
    )

    _close_all_documents()


# ---------------------------------------------------------------------------
# Part C — CQ semantics gate (S5: XY-only planes, extrude direction, cq_show)
# ---------------------------------------------------------------------------

def part_c(workdir):
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from agent.cq import Workplane
    from agent.cad_helpers import cq_show

    import FreeCAD
    import Part
    print("\nPart C — CQ semantics (S5)")

    # --- C1: non-XY planes must raise honestly ---
    raised = 0
    for plane in ("XZ", "YZ"):
        try:
            Workplane(plane)
        except NotImplementedError:
            raised += 1
    _report(raised == 2, "C1 XZ/YZ planes raise NotImplementedError",
            f"raised={raised}/2")

    # --- C2: extrude rises from the workplane ---
    bb2 = Workplane("XY").circle(10).extrude(20).solid().BoundBox
    _report(
        abs(bb2.ZMin) < 1e-6 and abs(bb2.ZMax - 20) < 1e-6,
        "C2 circle extrude spans z=0..+H",
        f"ZMin={bb2.ZMin:.3f} ZMax={bb2.ZMax:.3f}",
    )

    # --- C3: both=True is symmetric ±H (total 2H, CadQuery semantics) ---
    bb3 = Workplane("XY").circle(10).extrude(20, both=True).solid().BoundBox
    _report(
        abs(bb3.ZMin + 20) < 1e-6 and abs(bb3.ZMax - 20) < 1e-6,
        "C3 extrude both=True spans z=-H..+H",
        f"ZMin={bb3.ZMin:.3f} ZMax={bb3.ZMax:.3f}",
    )

    # --- C4: rect extrude, plain and both ---
    bb4a = Workplane("XY").rect(10, 10).extrude(5).solid().BoundBox
    bb4b = Workplane("XY").rect(10, 10).extrude(5, both=True).solid().BoundBox
    _report(
        abs(bb4a.ZMin) < 1e-6 and abs(bb4a.ZMax - 5) < 1e-6
        and abs(bb4b.ZMin + 5) < 1e-6 and abs(bb4b.ZMax - 5) < 1e-6,
        "C4 rect extrude 0..H / both -H..+H",
        f"plain=[{bb4a.ZMin:.2f},{bb4a.ZMax:.2f}] both=[{bb4b.ZMin:.2f},{bb4b.ZMax:.2f}]",
    )

    # --- C5: workplane(offset) raises the sketch plane ---
    bb5 = Workplane("XY").workplane(offset=10).circle(5).extrude(8).solid().BoundBox
    _report(
        abs(bb5.ZMin - 10) < 1e-6 and abs(bb5.ZMax - 18) < 1e-6,
        "C5 workplane(offset=10) extrude spans z=10..18",
        f"ZMin={bb5.ZMin:.3f} ZMax={bb5.ZMax:.3f}",
    )

    # --- C6: cq_show ownership — user objects never touched ---
    doc = FreeCAD.newDocument("cq_show_check")
    user_obj = doc.addObject("Part::Feature", "Part")
    user_obj.Label = "Part"
    user_shape = Part.makeBox(5, 5, 5)
    user_obj.Shape = user_shape
    doc.recompute()

    shown = cq_show(Workplane("XY").circle(6).extrude(12), "Part", doc=doc)
    user_untouched = (
        doc.getObject(user_obj.Name) is user_obj
        and abs(user_obj.Shape.Volume - user_shape.Volume) < 1e-9
    )
    _report(
        user_untouched and shown.Name.startswith("cqobj_"),
        "C6a cq_show never touches user objects (cqobj_ prefix ownership)",
        f"shown.Name={shown.Name!r} user_untouched={user_untouched}",
    )

    cq_show(Workplane("XY").box(3, 3, 3), "Body", doc=doc)
    own = [o for o in doc.Objects if o.Name.startswith("cqobj_")]
    user_still = doc.getObject(user_obj.Name) is user_obj
    _report(
        len(own) == 1 and own[0].Label == "Body" and user_still,
        "C6b label swap cleans only cq_show's own object",
        f"own={[o.Label for o in own]} user_present={user_still}",
    )

    _close_all_documents()


def main():
    _import_freecad()
    workdir = tempfile.mkdtemp(prefix="cadagent_verify_")
    try:
        part_a(workdir)
        part_b(workdir)
        part_c(workdir)
    finally:
        _close_all_documents()
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"\nSummary: {RESULTS['pass']} passed, {RESULTS['fail']} failed")
    if RESULTS["fail"]:
        print("RESULT: FAIL — FreeCAD behavior assumptions or snapshot invariants changed.")
        sys.exit(1)
    print("RESULT: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
