"""Code pre-validation and error hints for LLM robustness.

This module has NO FreeCAD imports and is fully testable in isolation.
"""
from __future__ import annotations

import re

_BOOL_OPS = r'(?:cut|fuse|common)'


def pre_validate_code(code: str) -> tuple[bool, str]:
    """Validate code syntax via compile(). Returns (ok, error_msg)."""
    try:
        compile(code, "<agent_code>", "exec")
        return True, ""
    except SyntaxError as e:
        line_info = f"line {e.lineno}" if e.lineno else "unknown line"
        detail = f": {e.msg}" if e.msg else ""
        pointer = ""
        if e.text and e.offset:
            pointer = f"\n  {e.text.rstrip()}\n  {' ' * (e.offset - 1)}^"
        return False, f"SyntaxError at {line_info}{detail}{pointer}"


def error_hint(error: Exception, code: str) -> tuple[str, str | None]:
    """Generate an actionable hint and optional auto-fix code.

    Returns (hint_text, fixed_code_or_None). When fixed_code is not None,
    the caller can attempt to re-execute it automatically.
    """
    hints = []
    e_type = type(error).__name__
    e_str = str(error)
    fixed_code = None

    _MAKE_FNS = ("makeBox", "makeCylinder", "makeCone", "makeSphere", "makeTorus")

    if e_type == "NameError":
        # Check if the undefined name is a bare Part constructor
        for fn in _MAKE_FNS:
            if fn in e_str:
                pat = re.compile(r'(?<!\w)(?<!\.)' + fn + r'\s*\(')
                fixed_code = pat.sub(f'Part.{fn}(', code)
                if fixed_code != code:
                    hints.append(f"Hint: '{fn}' is not a standalone function. Use Part.{fn}(...).")
                else:
                    fixed_code = None
                break
        if not hints:
            hints.append(
                "Hint: A variable is used before being defined. "
                "Pre-imported names: FreeCAD, Part, math, Gui, doc, Vector, App. "
                "Make sure you assign the result of each operation to a variable."
            )

    elif e_type == "AttributeError":
        if "'NoneType'" in e_str:
            # Check if this is a doc/object method on a None variable
            _DOC_METHODS = (
                "addObject", "recompute", "removeObject", "getObjectsByLabel",
                "getObject", "save", "saveAs", "Label", "Objects", "Name",
            )
            attr_match = re.search(r"no attribute '(\w+)'", e_str)
            if attr_match and attr_match.group(1) in _DOC_METHODS:
                hints.append(
                    "Hint: A document variable (likely 'doc') is None — "
                    "no active document exists. "
                    "Create one first: doc = FreeCAD.newDocument('MyModel')"
                )
            else:
                # translate() assignment: shape = shape.translate(...)
                pat_trans = re.compile(r'^(\s*)(\w+)\s*=\s*\2\.translate\s*\(', re.MULTILINE)
                if pat_trans.search(code):
                    fixed_code = pat_trans.sub(r'\1\2.translate(', code)
                    hints.append(
                        "Hint: translate() modifies in-place and returns None. "
                        "Removed the assignment."
                    )
                else:
                    # Boolean op without assignment: body.cut(hole)
                    pat_bool = re.compile(
                        r'^(\s*)(\w+)\.(' + _BOOL_OPS + r')\s*\((.+?)\)\s*$', re.MULTILINE
                    )
                    if pat_bool.search(code):
                        def _fix(m):
                            indent, var, op, args = m.group(1), m.group(2), m.group(3), m.group(4)
                            return f'{indent}{var} = {var}.{op}({args})'
                        fixed_code = pat_bool.sub(_fix, code)
                        hints.append(
                            "Hint: Boolean ops (cut/fuse/common) return NEW shapes. "
                            "Added assignment for the result."
                        )
                    else:
                        hints.append(
                            "Hint: A method returned None instead of a shape. "
                            "translate() modifies in-place (returns None). "
                            "Boolean ops return NEW shapes — assign the result."
                        )
        elif "vector" in e_str.lower() and "freecad" in code.lower():
            pat_vec = re.compile(r'FreeCAD\.vector\s*\(', re.IGNORECASE)
            fixed_code = pat_vec.sub('FreeCAD.Vector(', code)
            if fixed_code != code:
                hints.append("Hint: FreeCAD.Vector has a capital V. Fixed FreeCAD.vector → FreeCAD.Vector.")
            else:
                fixed_code = None
                hints.append(
                    "Hint: Check API names: Part.makeBox, Part.makeCylinder, "
                    "FreeCAD.Vector, doc.addObject, obj.Shape."
                )
        elif "makePipe" in e_str and "has no attribute" in e_str:
            pat_pipe = re.compile(r'(\w+)\.makePipe\s*\((.+)\)')
            m_pipe = pat_pipe.search(code)
            if m_pipe:
                var, profile = m_pipe.group(1), m_pipe.group(2)
                fixed_code = code.replace(
                    m_pipe.group(0),
                    f'Part.Wire([{var}]).makePipe({profile})'
                )
                hints.append(
                    "Hint: makePipe() is a method on Part.Wire, NOT on Part.Edge. "
                    f"Wrapped edge in Wire: Part.Wire([{var}]).makePipe(...). "
                    "Profile must be a Wire: c=Part.Circle(); c.Radius=r; "
                    "profile=Part.Wire([c.toShape()])"
                )
            else:
                hints.append(
                    "Hint: makePipe() requires Part.Wire, not Part.Edge. "
                    "Create wire first: wire=Part.Wire([edge]); pipe=wire.makePipe(profile)."
                )
        else:
            attr_match = re.search(r"no attribute '(\w+)'", e_str)
            type_match = re.search(r"'([^']+)' object", e_str)
            if attr_match and type_match:
                attr = attr_match.group(1)
                obj_type = type_match.group(1)
                hints.append(
                    f"Hint: {obj_type} has no method '{attr}'. "
                    "Check FreeCAD Part API. Common gotchas: "
                    "makePipe/revolve need Wire not Edge, "
                    "makeLoft needs list of Wires."
                )
            else:
                hints.append(
                    "Hint: Check API names: Part.makeBox, Part.makeCylinder, "
                    "FreeCAD.Vector, doc.addObject, obj.Shape."
                )

    elif e_type == "TypeError":
        if "translate" in code:
            # translate called with separate args instead of Vector
            pat_t = re.compile(r'\.translate\s*\(\s*([^)]+)\)')
            m = pat_t.search(code)
            if m and 'Vector' not in m.group(1) and 'FreeCAD' not in m.group(1):
                args = m.group(1).strip()
                fixed_code = pat_t.sub(f'.translate(FreeCAD.Vector({args}))', code)
                hints.append(
                    "Hint: translate() takes a FreeCAD.Vector, not separate x,y,z. "
                    "Wrapped args in Vector()."
                )
            else:
                hints.append(
                    "Hint: translate() takes a FreeCAD.Vector, not separate x,y,z. "
                    "Use shape.translate(FreeCAD.Vector(x, y, z))."
                )

    elif "OCC" in e_type or "BRep" in e_type:
        hints.append(
            "Hint: Boolean operation failed. Try: "
            "(1) ensure shapes overlap by at least 0.1mm, "
            "(2) try a different boolean order."
        )

    return "\n".join(hints), fixed_code
