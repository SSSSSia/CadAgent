"""Assembly planning without FreeCAD."""
from __future__ import annotations

from agent.assembly import assemble_with, normalize_link, require_saved_source


def test_unsaved_source_is_rejected():
    class Doc:
        Name = "Shaft"
        FileName = ""

    class Obj:
        Document = Doc()

    try:
        require_saved_source(Obj())
        assert False, "an unsaved document cannot be linked"
    except ValueError as exc:
        assert "not saved" in str(exc)


def test_normalize_link_defaults_and_names():
    link = normalize_link({"document": "Shaft", "label": "Body", "z": "12"})
    assert link["document"] == "Shaft"
    assert link["object"] == "Body"
    assert link["z"] == 12.0
    assert link["yaw"] == 0.0


def test_normalize_link_rejects_a_bad_angle():
    try:
        normalize_link({"document": "A", "object": "B", "yaw": "north"})
        assert False, "yaw must be numeric"
    except ValueError as exc:
        assert "yaw" in str(exc)


def test_assemble_with_places_links_and_reports_missing_parts():
    placed = []

    def lookup(document, obj):
        if document == "Missing":
            return None
        return {"document": document, "object": obj}

    def open_assembly(name):
        return {"name": name}

    def add_link(document, link_name, source, pose):
        placed.append((document["name"], link_name, source, pose))

    asm, names = assemble_with(
        "Gearbox",
        [
            {"document": "Shaft", "object": "Axle", "z": 10, "yaw": 90},
            {"document": "Housing", "object": "Case 1", "x": 3},
        ],
        lookup, open_assembly, add_link,
    )
    assert asm == "Gearbox"
    assert names == ["Link_Axle_1", "Link_Case_1_2"]
    assert placed[0][3] == (0.0, 0.0, 10.0, 90.0, 0.0, 0.0)
    try:
        assemble_with(
            "Gearbox",
            [{"document": "Missing", "object": "Nope"}],
            lookup, open_assembly, add_link,
        )
        assert False, "a missing source must fail"
    except ValueError as exc:
        assert "Missing" in str(exc)
