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
                "FreeCAD, Part, math, Gui are pre-imported. "
                "CAD helpers are pre-injected: extract_solid, safe_fuse, safe_cut, "
                "make_hollow_cylinder, make_ring, make_box_handle, ensure_doc. "
                "Variables persist between calls — reuse them directly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "FreeCAD Python code. "
                            "Pre-imported: FreeCAD, Part, math, Gui. "
                            "Pre-injected helpers: extract_solid, safe_fuse, safe_cut, "
                            "make_hollow_cylinder, make_ring, make_box_handle, ensure_doc."
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
