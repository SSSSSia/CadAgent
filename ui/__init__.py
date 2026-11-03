"""CadAgent UI package.

Submodules are imported directly (`ui.panel`, `ui.strings`). `AgentPanel` is
resolved lazily so importing `ui.strings` does not load FreeCAD.
"""


def __getattr__(name):
    if name == "AgentPanel":
        from ui.panel import AgentPanel
        return AgentPanel
    raise AttributeError(f"module 'ui' has no attribute {name!r}")
