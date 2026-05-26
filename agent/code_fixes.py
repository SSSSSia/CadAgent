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

    # Fix 4: Bare makeBox/makeCylinder/... without Part. prefix
    pat4 = re.compile(r'(?<!\w)(?<!\.)(makeBox|makeCylinder|makeCone|makeSphere|makeTorus)\s*\(')
    new_code = pat4.sub(r'Part.\1(', code)
    if new_code != code:
        fixes.append("Added missing 'Part.' prefix to primitive constructor(s)")
        code = new_code

    # Fix 5: FreeCAD.vector (lowercase v) → FreeCAD.Vector
    pat5 = re.compile(r'FreeCAD\.vector\s*\(', re.IGNORECASE)
    new_code = pat5.sub('FreeCAD.Vector(', code)
    if new_code != code:
        fixes.append("Fixed FreeCAD.vector → FreeCAD.Vector (case-sensitive)")
        code = new_code

    # Fix 6: doc.addObject(...) without assignment → _obj_N = doc.addObject(...)
    _addobj_counter = 0
    pat6 = re.compile(r'^(\s*)(doc\.addObject\s*\()', re.MULTILINE)

    def _fix_addobj(m):
        nonlocal _addobj_counter
        indent, call = m.group(1), m.group(2)
        # Check if already assigned: look for 'var =' pattern before the call on same line
        line_start = m.start()
        prefix = code[:line_start]
        last_newline = prefix.rfind('\n')
        preceding = prefix[last_newline + 1:] if last_newline >= 0 else prefix
        # Only consider it "already assigned" if the line starts with a variable assignment
        # like "obj = doc.addObject(...)" — not just any '=' on the preceding part
        if re.match(r'\s*\w+\s*=\s*$', preceding):
            return m.group(0)  # already has assignment
        _addobj_counter += 1
        fixes.append(f"Assigned doc.addObject() result to _obj_{_addobj_counter}")
        return f'{indent}_obj_{_addobj_counter} = {call}'
    new_code = pat6.sub(_fix_addobj, code)
    if new_code != code:
        code = new_code

    # Fix 7: Residual markdown fences after strip_markdown
    if code.strip().startswith('```') or code.strip().endswith('```'):
        from core.text_utils import strip_markdown
        stripped = strip_markdown(code)
        if stripped != code:
            fixes.append("Removed residual markdown code fences")
            code = stripped

    # Fix 8: Multi-arg boolean ops like body.cut(a, b) → body.cut(a).cut(b)
    pat8 = re.compile(
        r'(\w+)\s*=\s*(\w+)\.(cut|fuse|common)\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)'
    )
    def _fix_multi_bool(m):
        lhs, base, op, a, b = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        fixes.append(f"Split {base}.{op}({a}, {b}) → chained {op} calls (boolean ops take one arg)")
        return f'{lhs} = {base}.{op}({a}).{op}({b})'
    new_code = pat8.sub(_fix_multi_bool, code)
    if new_code != code:
        code = new_code

    # Fix 9: shape.Placement = ... on Part.Shape (NOT on DocumentObject)
    # Only remove when the variable looks like a Part shape (lowercase or known shape names),
    # not when it's a DocumentObject (like obj, body, etc. assigned from doc.addObject)
    pat9 = re.compile(r'^(\s*)(\w+)\.Placement\s*=\s*(.+)$', re.MULTILINE)

    def _fix_placement(m):
        indent, var, value = m.group(1), m.group(2), m.group(3)
        # Skip if variable name looks like a DocumentObject (short, common names)
        _doc_obj_names = {'obj', 'body', 'part', 'shape', 'box', 'cyl', 'hole'}
        if var.lower() in _doc_obj_names:
            return m.group(0)  # likely a DocumentObject, keep Placement
        # If value contains FreeCAD.Placement, it's likely intentional
        if 'FreeCAD.Placement' in value or 'Placement(' in value:
            return m.group(0)  # intentional Placement assignment, keep
        fixes.append(f"Removed {var}.Placement assignment (Part shapes use translate(), not Placement)")
        return ''
    new_code = pat9.sub(_fix_placement, code)
    if new_code != code:
        code = new_code

    return code, fixes


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
