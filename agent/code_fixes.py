"""Code pre-validation, auto-fix, and error hints for weak model robustness.

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


def auto_fix_code(code: str) -> tuple[str, list[str]]:
    """Detect and fix common FreeCAD API mistakes.

    Returns (fixed_code, list_of_fix_descriptions).
    """
    fixes = []

    # Fix 1: shape = shape.translate(...) -> shape.translate(...)
    pat = re.compile(r'^(\s*)(\w+)\s*=\s*\2\.translate\s*\(', re.MULTILINE)
    new_code = pat.sub(r'\1\2.translate(', code)
    if new_code != code:
        fixes.append("Removed assignment from translate() (modifies in-place, returns None)")
        code = new_code

    # Fix 2: body.cut(hole) without assignment -> body = body.cut(hole)
    pat2 = re.compile(
        r'^(\s*)(\w+)\.(' + _BOOL_OPS + r')\s*\((.+?)\)\s*$',
        re.MULTILINE,
    )
    def _fix_bool(m):
        indent, var, op, args = m.group(1), m.group(2), m.group(3), m.group(4)
        fixes.append(f"{var}.{op}({args}) -> {var} = {var}.{op}({args}) (boolean ops return new shapes)")
        return f'{indent}{var} = {var}.{op}({args})'
    new_code = pat2.sub(_fix_bool, code)
    if new_code != code:
        code = new_code

    # Fix 3: Missing doc.recompute() at the end
    if 'addObject' in code and 'recompute()' not in code:
        code = code.rstrip() + '\ndoc.recompute()\n'
        fixes.append("Added missing doc.recompute() at the end")

    return code, fixes


def error_hint(error: Exception, code: str) -> str:
    """Generate an actionable hint based on the error type and context."""
    hints = []
    e_type = type(error).__name__
    e_str = str(error)

    if e_type == "NameError":
        hints.append(
            "Hint: A variable is used before being defined. "
            "Pre-imported names: FreeCAD, Part, math, Gui, doc, Vector, App. "
            "Make sure you assign the result of each operation to a variable."
        )
    elif e_type == "AttributeError":
        if "'NoneType'" in e_str:
            hints.append(
                "Hint: A method returned None instead of a shape. "
                "translate() modifies in-place (returns None). "
                "Boolean ops (cut/fuse/common) return NEW shapes — assign the result."
            )
        else:
            hints.append(
                "Hint: Check API names: Part.makeBox, Part.makeCylinder, "
                "FreeCAD.Vector, doc.addObject, obj.Shape."
            )
    elif e_type == "TypeError":
        if "translate" in code:
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

    return "\n".join(hints)
