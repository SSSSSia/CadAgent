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
                "Execute CadQuery-style Python code to create or modify 3D geometry. "
                "The 'cq' module is pre-injected — use cq.Workplane chain API. "
                "Use cq_show(result, 'Label') to display shapes in the viewport. "
                "FreeCAD, Part, math are also available. "
                "Variables persist between calls — reuse them directly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "CadQuery-style Python code. "
                            "Use cq.Workplane chain API. "
                            "Use cq_show(result, 'Label') to display. "
                            "FreeCAD, Part, math also available."
                        )
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
            "name": "capture_view",
            "description": (
                "Capture the current FreeCAD 3D viewport as a screenshot and "
                "analyze it using a vision AI model. Use this to visually verify "
                "geometry after creating or modifying shapes, check for visual "
                "issues, or get a description of the current model state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "What to ask the vision model about the screenshot. "
                            "Examples: 'Does this look like a correct flange?', "
                            "'Check if the bolt holes are evenly distributed.'"
                        )
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": (
                "Analyze a user-uploaded image (reference drawing, sketch, photo) "
                "using a vision AI model. Use this when the user provides an image "
                "to reference for modeling. Returns a detailed description of the "
                "image content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Path to the image file to analyze."
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "What to ask the vision model about the image. "
                            "Examples: 'Describe the mechanical part dimensions.', "
                            "'What are the key features of this design?'"
                        )
                    }
                },
                "required": ["image_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_step",
            "description": (
                "Export current FreeCAD document to STEP, IGES, STL, or OBJ file format. "
                "Use to save the final design for manufacturing or exchange with other CAD software. "
                "STEP is recommended for CAD exchange; STL/OBJ for 3D printing. "
                "A quality check runs before export — warnings are included in the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "Output file path. Extension should match format "
                            "(.step/.stp, .iges/.igs, .stl, .obj)."
                        )
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format",
                        "enum": ["step", "iges", "stl", "obj"],
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
