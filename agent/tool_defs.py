"""
Tool definitions — JSON Schema for LLM tool calling.

定义 Agent 可用的工具列表，作为 OpenAI-compatible API 的 tools 参数传入。
"""


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": (
                "Execute FreeCAD Python code to create or modify 3D geometry. "
                "FreeCAD, Part, math, FreeCADGui (as Gui) are pre-imported. "
                "Variables persist between calls — reuse them directly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "FreeCAD Python code. Modules pre-imported: FreeCAD, Part, math, Gui."
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what this code does"
                    },
                    "document": {
                        "type": "string",
                        "description": "Optional target document name. Defaults to FreeCAD.ActiveDocument."
                    }
                },
                "required": ["code", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last",
            "description": (
                "Undo the last execute_code operation by restoring the document snapshot. "
                "Use when code produces incorrect geometry or causes errors."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_step",
            "description": (
                "Export current FreeCAD document to STEP or IGES file format. "
                "Use to save the final design for manufacturing or exchange with other CAD software."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Output file path. Extension should match format (.step/.stp or .iges/.igs)."
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format",
                        "enum": ["step", "iges"],
                    },
                    "document": {
                        "type": "string",
                        "description": "Optional target document name. Defaults to FreeCAD.ActiveDocument."
                    }
                },
                "required": ["filename"]
            }
        }
    },
]
