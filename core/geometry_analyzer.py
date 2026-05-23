"""Pure geometry analysis — shape type inference, face detection, description.

Operates on plain data structures (dataclasses), no FreeCAD dependencies.
FreeCAD-specific extraction happens in core/doc_analyzer.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FaceInfo:
    geom_type: str
    area: float = 0.0
    normal: tuple | None = None
    radius: float | None = None
    center: tuple | None = None
    axis: tuple | None = None


@dataclass
class SolidInfo:
    faces: list[FaceInfo] = field(default_factory=list)


@dataclass
class ShapeInfo:
    bound_box: dict = field(default_factory=dict)  # XMin,XMax,YMin,YMax,ZMin,ZMax
    volume: float = 0.0
    faces: int = 0
    edges: int = 0
    vertices: int = 0
    center_of_mass: tuple | None = None
    solids: list[SolidInfo] = field(default_factory=list)


def infer_shape_type(info: ShapeInfo) -> str | None:
    solids = info.solids
    if len(solids) > 1:
        return "Multi-solid assembly"
    total_faces = sum(len(s.faces) for s in solids)
    if total_faces > 20:
        return "Complex boolean result"
    if len(solids) == 1:
        has_cylinder = False
        has_other_curved = False
        all_planar = True
        for face in solids[0].faces:
            if face.radius is not None:
                has_cylinder = True
                all_planar = False
            elif face.geom_type not in ("Plane",):
                has_other_curved = True
                all_planar = False
        if has_other_curved:
            return None
        if all_planar:
            return "Box"
        if has_cylinder:
            return "Solid cylinder"
    return None


def detect_planar_faces(info: ShapeInfo, min_area: float = 100.0) -> list[str]:
    plane_groups: list[tuple[tuple, list[float]]] = []
    for solid in info.solids:
        for face in solid.faces:
            if face.geom_type != "Plane":
                continue
            area = face.area
            if area < min_area:
                continue
            n_tuple = face.normal or (0.0, 0.0, 0.0)
            found = False
            for i, (gn, areas) in enumerate(plane_groups):
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


def describe_shape(info: ShapeInfo) -> str:
    lines = []
    bb = info.bound_box
    lines.append(
        f"  Bounding box: "
        f"X[{bb.get('XMin', 0):.1f}~{bb.get('XMax', 0):.1f}] "
        f"Y[{bb.get('YMin', 0):.1f}~{bb.get('YMax', 0):.1f}] "
        f"Z[{bb.get('ZMin', 0):.1f}~{bb.get('ZMax', 0):.1f}]"
    )
    x_len = bb.get("XMax", 0) - bb.get("XMin", 0)
    y_len = bb.get("YMax", 0) - bb.get("YMin", 0)
    z_len = bb.get("ZMax", 0) - bb.get("ZMin", 0)
    lines.append(f"  Overall: {x_len:.1f} x {y_len:.1f} x {z_len:.1f} mm")
    if abs(info.volume) > 0.01:
        lines.append(f"  Volume: {info.volume:.1f} mm3")

    lines.append(
        f"  Faces: {info.faces}, "
        f"Edges: {info.edges}, "
        f"Vertices: {info.vertices}"
    )

    if info.center_of_mass:
        com = info.center_of_mass
        lines.append(f"  Center of mass: ({com[0]:.1f}, {com[1]:.1f}, {com[2]:.1f})")

    shape_type = infer_shape_type(info)
    if shape_type:
        lines.append(f"  Inferred type: {shape_type}")

    cylinders = []
    for solid in info.solids:
        for face in solid.faces:
            if face.radius is not None:
                r = face.radius
                info_str = f"R={r:.1f}mm"
                if face.center:
                    info_str += f", center=({face.center[0]:.1f},{face.center[1]:.1f},{face.center[2]:.1f})"
                if face.axis:
                    info_str += f", axis=({face.axis[0]:.2f},{face.axis[1]:.2f},{face.axis[2]:.2f})"
                if not any(abs(r - c_r) < 0.1 for c_r, _ in cylinders):
                    cylinders.append((r, info_str))

    if cylinders:
        lines.append("  Detected cylindrical features:")
        for _, info_str in cylinders:
            lines.append(f"    - Cylinder {info_str}")

    planes = detect_planar_faces(info)
    if planes:
        lines.append("  Detected planar features:")
        for info_str in planes:
            lines.append(f"    - {info_str}")

    return "\n".join(lines)
