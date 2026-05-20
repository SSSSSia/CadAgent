"""
doc_analyzer — extract geometry info from a FreeCAD document as text context.
"""
from __future__ import annotations

import FreeCAD
import Part
import math


def _describe_shape(shape) -> str:
    """将一个 TopoShape 转化为人类可读的几何描述文本，供 LLM 作为上下文使用。

    提取的信息包括：包围盒尺寸、体积、圆柱面参数（半径/圆心/轴向）。
    这些信息让 LLM 在 modify/derive/variant 模式下能知道当前模型的精确几何参数。
    """
    lines = []
    bb = shape.BoundBox
    lines.append(
        f"  Bounding box: "
        f"X[{bb.XMin:.1f}~{bb.XMax:.1f}] "
        f"Y[{bb.YMin:.1f}~{bb.YMax:.1f}] "
        f"Z[{bb.ZMin:.1f}~{bb.ZMax:.1f}]"
    )
    dims = (
        f"  Overall: {bb.XLength:.1f} x {bb.YLength:.1f} x {bb.ZLength:.1f} mm"
    )
    lines.append(dims)
    if abs(shape.Volume) > 0.01:
        lines.append(f"  Volume: {shape.Volume:.1f} mm3")

    # 遍历 Solid → Face → Surface，检测圆柱面特征
    cylinders = []
    boxes = []
    for solid in shape.Solids:
        for face in solid.Faces:
            surf = face.Surface
            if hasattr(surf, "Radius"):
                r = surf.Radius
                center = getattr(surf, "Center", None)
                axis = getattr(surf, "Axis", None)
                info = f"R={r:.1f}mm"
                if center:
                    info += f", center=({center.x:.1f},{center.y:.1f},{center.z:.1f})"
                if axis:
                    info += f", axis=({axis.x:.2f},{axis.y:.2f},{axis.z:.2f})"
                # 同一个圆柱体会出现在多个面上（顶面、底面、侧面），
                # 用半径去重，避免向 LLM 传递重复信息浪费 token
                if not any(abs(r - c_r) < 0.1 for c_r, _ in cylinders):
                    cylinders.append((r, info))
            elif hasattr(surf, "Position") and not hasattr(surf, "Radius"):
                pass  # planar face, skip

    if cylinders:
        lines.append("  Detected cylindrical features:")
        for _, info in cylinders:
            lines.append(f"    - Cylinder {info}")

    return "\n".join(lines)


def analyze_document(doc=None) -> str:
    """提取 FreeCAD 文档的几何信息，返回文本描述。

    仅在 modify/derive/variant 模式下调用。输出会填入 LLM System Prompt
    的 {context} 占位符，让 LLM 了解当前模型的尺寸和形状。
    """
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        return "(No active document)"

    lines = [f"Current document: '{doc.Name}', objects:"]

    # 过滤掉没有 Shape 属性或 Shape 为空的对象（如 Origin、Annotation 等）
    for obj in doc.Objects:
        if not hasattr(obj, "Shape") or obj.Shape is None:
            continue
        if obj.Shape.isNull():
            continue

        lines.append(f"- '{obj.Label}' (type: {obj.TypeId})")
        lines.append(_describe_shape(obj.Shape))

    return "\n".join(lines)
