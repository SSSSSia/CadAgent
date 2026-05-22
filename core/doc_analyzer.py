"""
doc_analyzer — extract geometry info from a FreeCAD document as text context.
"""
from __future__ import annotations

import FreeCAD
import Part
import math


def _infer_shape_type(shape) -> str | None:
    """根据拓扑特征推断形状类型。"""
    solids = shape.Solids
    if len(solids) > 1:
        return "Multi-solid assembly"
    if len(shape.Faces) > 20:
        return "Complex boolean result"
    if len(solids) == 1:
        has_cylinder = False
        has_other_curved = False
        all_planar = True
        for face in solids[0].Faces:
            surf = face.Surface
            if hasattr(surf, "Radius"):
                has_cylinder = True
                all_planar = False
            elif hasattr(surf, "geomType") and surf.geomType not in ("Plane",):
                has_other_curved = True
                all_planar = False
        if has_other_curved:
            return None
        if all_planar:
            return "Box"
        if has_cylinder:
            return "Solid cylinder"
    return None


def _detect_planar_faces(shape, min_area: float = 100.0) -> list[str]:
    """检测大的平面特征，按法线方向分组。

    Args:
        shape: TopoShape
        min_area: 最小面积阈值(mm2)，忽略小面
    """
    # 收集所有平面的法线和面积
    plane_groups: list[tuple[tuple, list[float]]] = []
    for solid in shape.Solids:
        for face in solid.Faces:
            if not hasattr(face.Surface, "geomType") or face.Surface.geomType != "Plane":
                continue
            area = face.Area
            if area < min_area:
                continue
            normal = face.normalAt(0, 0)
            n_tuple = (round(normal.x, 2), round(normal.y, 2), round(normal.z, 2))
            # 查找已有的同方向组
            found = False
            for i, (gn, areas) in enumerate(plane_groups):
                # 检查是否平行（方向相同或相反）
                dot = abs(gn[0] * n_tuple[0] + gn[1] * n_tuple[1] + gn[2] * n_tuple[2])
                if dot > 0.99:
                    plane_groups[i][1].append(area)
                    found = True
                    break
            if not found:
                plane_groups.append((n_tuple, [area]))

    result = []
    for normal, areas in plane_groups:
        count = len(areas)
        avg_area = sum(areas) / count
        n_str = f"({normal[0]:.2f},{normal[1]:.2f},{normal[2]:.2f})"
        if count >= 2:
            result.append(f"{count} parallel planes, normal={n_str}, avg area={avg_area:.1f} mm2")
        else:
            result.append(f"1 plane, normal={n_str}, area={avg_area:.1f} mm2")
    return result


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

    # 拓扑统计
    lines.append(
        f"  Faces: {len(shape.Faces)}, "
        f"Edges: {len(shape.Edges)}, "
        f"Vertices: {len(shape.Vertexes)}"
    )

    # 质心
    if hasattr(shape, "CenterOfMass"):
        com = shape.CenterOfMass
        lines.append(f"  Center of mass: ({com.x:.1f}, {com.y:.1f}, {com.z:.1f})")

    # 形状类型推断
    shape_type = _infer_shape_type(shape)
    if shape_type:
        lines.append(f"  Inferred type: {shape_type}")

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

    # 检测大的平面特征（法兰面、底面等）
    planes = _detect_planar_faces(shape)
    if planes:
        lines.append("  Detected planar features:")
        for info in planes:
            lines.append(f"    - {info}")

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
