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
                    },
                    "document": {
                        "type": "string",
                        "description": "Optional target document name. Defaults to FreeCAD.ActiveDocument. Use for cross-document operations."
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
                    },
                    "document": {
                        "type": "string",
                        "description": "Optional target document name. Defaults to FreeCAD.ActiveDocument."
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
                    },
                    "document": {
                        "type": "string",
                        "description": "Optional target document name. Defaults to FreeCAD.ActiveDocument."
                    }
                },
                "required": ["requirements"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last",
            "description": (
                "Undo the last execute_code operation by restoring the FreeCAD "
                "document to its state before that code ran. Use when code produces "
                "incorrect geometry or causes errors. Can be called multiple times "
                "for multi-step undo."
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
                "Use to save geometry for manufacturing or exchange with other CAD software."
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
    {
        "type": "function",
        "function": {
            "name": "measure_distance",
            "description": (
                "Measure distance or angle between two geometric elements in the current document. "
                "Elements can be object labels (e.g. 'Body') or point coordinates (e.g. 'point:x,y,z'). "
                "Use to verify clearances, check mating gaps, or confirm dimensions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "element1": {
                        "type": "string",
                        "description": "First element: object label (e.g. 'Housing') or point as 'point:x,y,z'"
                    },
                    "element2": {
                        "type": "string",
                        "description": "Second element: same format as element1"
                    },
                    "measure_type": {
                        "type": "string",
                        "description": "Type of measurement",
                        "enum": ["distance", "angle"],
                    },
                    "document": {
                        "type": "string",
                        "description": "Optional target document name. Defaults to FreeCAD.ActiveDocument."
                    }
                },
                "required": ["element1", "element2"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_materials",
            "description": (
                "List common engineering materials with density, yield strength, and elastic modulus. "
                "Use to look up material properties for weight estimation or structural analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter",
                        "enum": ["steel", "aluminum", "titanium", "copper", "plastic", "all"],
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": (
                "Capture the current FreeCAD 3D viewport as a PNG image. "
                "Use to save a visual record of the current design state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "save_path": {
                        "type": "string",
                        "description": "File path to save the screenshot (PNG). Auto-generated in temp dir if omitted."
                    },
                    "width": {
                        "type": "integer",
                        "description": "Image width in pixels (100-4096, default 800)",
                    },
                    "height": {
                        "type": "integer",
                        "description": "Image height in pixels (100-4096, default 600)",
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": (
                "List all open FreeCAD documents with their names, object counts, "
                "and shape counts. Use before assembly operations to identify available "
                "documents and parts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "include_geometry": {
                        "type": "boolean",
                        "description": "Whether to include geometry summary for each document (default: false)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_assembly",
            "description": (
                "Create a new FreeCAD document as an assembly container, "
                "copy parts from existing documents, and position them using Placement. "
                "Use to combine multiple parts into an assembly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the new assembly document"
                    },
                    "parts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_document": {
                                    "type": "string",
                                    "description": "Name of source document to copy from"
                                },
                                "object_label": {
                                    "type": "string",
                                    "description": "Label of object to copy"
                                },
                                "position": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "[x, y, z] position in mm"
                                },
                                "rotation": {
                                    "type": "object",
                                    "description": "Rotation: axis [x,y,z] and angle in degrees",
                                    "properties": {
                                        "axis": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "description": "Rotation axis [x, y, z]"
                                        },
                                        "angle_deg": {
                                            "type": "number",
                                            "description": "Rotation angle in degrees"
                                        }
                                    }
                                }
                            },
                            "required": ["source_document", "object_label", "position"]
                        },
                        "description": "List of parts to place in the assembly"
                    }
                },
                "required": ["name"]
            }
        }
    },
]
