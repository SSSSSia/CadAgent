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
                "Returns stdout, error traceback (if any), and document state."
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
                    }
                },
                "required": ["code", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_geometry",
            "description": (
                "Analyze current FreeCAD document geometry. Returns bounding boxes, "
                "volumes, detected features (cylinders, boxes), object listing. "
                "Use to verify a design or understand existing geometry before modifying."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "Aspect to focus on",
                        "enum": ["all", "dimensions", "features"],
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_design",
            "description": (
                "Validate current design against user requirements. Checks for "
                "missing features, incorrect dimensions, empty/null shapes, "
                "boolean operation failures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "requirements": {
                        "type": "string",
                        "description": "The user's design requirements to validate against"
                    }
                },
                "required": ["requirements"]
            }
        }
    },
]
