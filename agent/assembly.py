"""Build an assembly document from App::Link placements.

The planning functions are pure. ``assemble_links`` is the FreeCAD
execution layer injected into ``execute_code``.
"""
from __future__ import annotations

import os
import re

_NUMBER_KEYS = ("x", "y", "z", "yaw", "pitch", "roll")


def normalize_link(spec: dict) -> dict:
    """Return a canonical link spec. Angles are degrees."""
    if not isinstance(spec, dict):
        raise ValueError("each link must be a dict with document and object")
    document = str(spec.get("document") or "").strip()
    obj = str(spec.get("object") or spec.get("label") or "").strip()
    if not document or not obj:
        raise ValueError("each link needs 'document' and 'object'")
    out = {"document": document, "object": obj}
    for key in _NUMBER_KEYS:
        raw = spec.get(key, 0)
        try:
            out[key] = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"link {key} must be a number, got {raw!r}") from exc
    return out


def normalize_links(specs) -> list[dict]:
    if not isinstance(specs, (list, tuple)) or not specs:
        raise ValueError("links must be a non-empty list")
    return [normalize_link(spec) for spec in specs]


def link_object_name(source_name: str, index: int) -> str:
    """FreeCAD object names cannot contain spaces or punctuation."""
    safe = re.sub(r"\W+", "_", source_name).strip("_") or "Part"
    return f"Link_{safe}_{index}"


def assemble_with(name, specs, lookup_object, open_assembly, add_link):
    """Place each source object as a link. Callables hide FreeCAD.

    ``lookup_object(document, object)`` returns the source or None.
    ``open_assembly(name)`` returns the assembly document.
    ``add_link(document, link_name, source, pose)`` writes one link.
    ``pose`` is ``(x, y, z, yaw, pitch, roll)`` in millimetres and degrees.
    """
    links = normalize_links(specs)
    asm_name = str(name or "").strip() or "Assembly"
    document = open_assembly(asm_name)
    created = []
    for index, link in enumerate(links, start=1):
        source = lookup_object(link["document"], link["object"])
        if source is None:
            raise ValueError(
                f"object {link['object']!r} was not found in document "
                f"{link['document']!r}"
            )
        link_name = link_object_name(link["object"], index)
        pose = (
            link["x"], link["y"], link["z"],
            link["yaw"], link["pitch"], link["roll"],
        )
        add_link(document, link_name, source, pose)
        created.append(link_name)
    return asm_name, created


def require_saved_source(source) -> None:
    """FreeCAD refuses App::Link when the source document has never been saved."""
    document = getattr(source, "Document", None)
    file_name = getattr(document, "FileName", "") if document is not None else ""
    if file_name:
        return
    doc_name = getattr(document, "Name", "") or "document"
    raise ValueError(
        f"document {doc_name!r} is not saved. FreeCAD can only link a saved "
        "document. Save it, then call assemble_links again."
    )


def assemble_links(name, specs):
    """Create or reuse an assembly document and return it.

    Each item of *specs* is ``{"document", "object", "x", "y", "z",
    "yaw", "pitch", "roll"}``. The source object stays in its own document.
    """
    import FreeCAD

    def lookup(document_name, object_name):
        try:
            document = FreeCAD.getDocument(document_name)
        except Exception:
            return None
        found = document.getObject(object_name)
        if found is not None:
            return found
        for candidate in getattr(document, "Objects", []) or []:
            if getattr(candidate, "Label", "") == object_name:
                return candidate
        return None

    def open_assembly(asm_name):
        try:
            document = FreeCAD.getDocument(asm_name)
        except Exception:
            document = FreeCAD.newDocument(asm_name)
        if not document.FileName:
            from core.paths import data_root
            folder = os.path.join(data_root(), "assemblies")
            os.makedirs(folder, exist_ok=True)
            label = document.Label
            safe = re.sub(r"\W+", "_", asm_name).strip("_") or "Assembly"
            document.saveAs(os.path.join(folder, f"{safe}.FCStd"))
            document.Label = label
        return document

    def add_link(document, link_name, source, pose):
        require_saved_source(source)
        link = document.getObject(link_name)
        if link is None:
            link = document.addObject("App::Link", link_name)
        link.LinkedObject = source
        x, y, z, yaw, pitch, roll = pose
        link.Placement = FreeCAD.Placement(
            FreeCAD.Vector(x, y, z),
            FreeCAD.Rotation(yaw, pitch, roll),
        )
        link.Label = link_name

    asm_name, _created = assemble_with(
        name, specs, lookup, open_assembly, add_link,
    )
    document = FreeCAD.getDocument(asm_name)
    document.recompute()
    return document
