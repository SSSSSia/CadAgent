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
    cone_half_angle: float | None = None


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
    shape_type: str = ""         # "Solid", "Compound", "Shell", etc.
    solid_count: int = 0         # number of disconnected solids


def infer_shape_type(info: ShapeInfo) -> str | None:
    solids = info.solids
    if len(solids) > 1:
        return "Multi-solid assembly"
    total_faces = sum(len(s.faces) for s in solids)
    if total_faces > 20:
        return "Complex boolean result"
    if len(solids) == 1:
        has_cylinder = False
        has_cone = False
        has_sphere = False
        has_helix = False
        all_planar = True
        for face in solids[0].faces:
            gt = face.geom_type
            if gt == "Cylinder":
                has_cylinder = True
                all_planar = False
            elif gt == "Cone":
                has_cone = True
                all_planar = False
            elif gt == "Sphere":
                has_sphere = True
                all_planar = False
            elif gt == "Helix":
                has_helix = True
                all_planar = False
            elif gt not in ("Plane",):
                all_planar = False
        if all_planar:
            return "Box"
        if has_helix:
            return "Threaded part"
        if has_cone and not has_cylinder and not has_sphere:
            return "Cone/frustum"
        if has_sphere and not has_cylinder and not has_cone:
            return "Sphere"
        if has_cylinder and not has_cone and not has_sphere:
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


def detect_conical_faces(info: ShapeInfo) -> list[str]:
    result = []
    seen: list[tuple[float, float]] = []
    for solid in info.solids:
        for face in solid.faces:
            if face.geom_type != "Cone":
                continue
            r = face.radius
            angle = face.cone_half_angle
            info_str = ""
            if r is not None:
                info_str += f"R={r:.1f}mm"
            if angle is not None:
                info_str += f", half-angle={angle:.1f}deg"
            if face.axis:
                info_str += f", axis=({face.axis[0]:.2f},{face.axis[1]:.2f},{face.axis[2]:.2f})"
            if face.center:
                info_str += f", apex=({face.center[0]:.1f},{face.center[1]:.1f},{face.center[2]:.1f})"
            key = (round(r, 1) if r else 0, round(angle, 1) if angle else 0)
            if key not in seen:
                seen.append(key)
                result.append(info_str)
    return result


def detect_spherical_faces(info: ShapeInfo) -> list[str]:
    result = []
    seen_radii: list[float] = []
    for solid in info.solids:
        for face in solid.faces:
            if face.geom_type != "Sphere":
                continue
            r = face.radius
            info_str = f"R={r:.1f}mm" if r is not None else "R=?"
            if face.center:
                info_str += f", center=({face.center[0]:.1f},{face.center[1]:.1f},{face.center[2]:.1f})"
            if r is not None and not any(abs(r - sr) < 0.1 for sr in seen_radii):
                seen_radii.append(r)
                result.append(info_str)
    return result


def detect_helical_faces(info: ShapeInfo) -> list[str]:
    count = 0
    for solid in info.solids:
        for face in solid.faces:
            if face.geom_type == "Helix":
                count += 1
    if count == 0:
        return []
    return [f"{count} helical face(s) detected — likely thread feature"]


def _check_circular_pattern(
    centers: list[tuple], tolerance: float
) -> tuple[float, int] | None:
    if len(centers) < 3:
        return None
    n = len(centers)
    cx = sum(c[0] for c in centers) / n
    cy = sum(c[1] for c in centers) / n
    cz = sum(c[2] for c in centers) / n
    dists = [((c[0]-cx)**2 + (c[1]-cy)**2 + (c[2]-cz)**2) ** 0.5 for c in centers]
    avg_dist = sum(dists) / n
    if avg_dist < tolerance:
        return None
    if all(abs(d - avg_dist) < tolerance for d in dists):
        return (avg_dist, n)
    return None


def _check_linear_pattern(
    centers: list[tuple], tolerance: float
) -> tuple[float, int] | None:
    if len(centers) < 2:
        return None
    c0, c1 = centers[0], centers[-1]
    dx, dy, dz = c1[0]-c0[0], c1[1]-c0[1], c1[2]-c0[2]
    line_len = (dx*dx + dy*dy + dz*dz) ** 0.5
    if line_len < tolerance:
        return None
    ux, uy, uz = dx/line_len, dy/line_len, dz/line_len
    projections = []
    for c in centers:
        vx, vy, vz = c[0]-c0[0], c[1]-c0[1], c[2]-c0[2]
        t = vx*ux + vy*uy + vz*uz
        px, py, pz = c0[0]+t*ux, c0[1]+t*uy, c0[2]+t*uz
        perp = ((c[0]-px)**2 + (c[1]-py)**2 + (c[2]-pz)**2) ** 0.5
        if perp > tolerance:
            return None
        projections.append(t)
    projections.sort()
    spacings = [projections[i+1] - projections[i] for i in range(len(projections)-1)]
    avg_spacing = sum(spacings) / len(spacings)
    if avg_spacing < tolerance:
        return None
    if all(abs(s - avg_spacing) < tolerance for s in spacings):
        return (avg_spacing, len(centers))
    return None


def detect_hole_patterns(
    info: ShapeInfo,
    radius_tolerance: float = 0.1,
    position_tolerance: float = 1.0,
) -> list[str]:
    cylinders: list[tuple[float, tuple, tuple]] = []
    for solid in info.solids:
        for face in solid.faces:
            if face.geom_type == "Cylinder" and face.center and face.radius:
                cylinders.append((face.radius, face.center, face.axis or (0, 0, 1)))
    if len(cylinders) < 2:
        return []
    groups: list[list[tuple[float, tuple, tuple]]] = []
    for cyl in cylinders:
        placed = False
        for group in groups:
            if abs(cyl[0] - group[0][0]) < radius_tolerance:
                group.append(cyl)
                placed = True
                break
        if not placed:
            groups.append([cyl])
    result = []
    for group in groups:
        if len(group) < 2:
            continue
        r = group[0][0]
        centers = [c[1] for c in group]
        circle_result = _check_circular_pattern(centers, position_tolerance)
        if circle_result:
            pattern_r, count = circle_result
            result.append(
                f"Circular hole pattern: {count} holes, R={r:.1f}mm, "
                f"PCD={pattern_r * 2:.1f}mm"
            )
            continue
        linear_result = _check_linear_pattern(centers, position_tolerance)
        if linear_result:
            spacing, count = linear_result
            result.append(
                f"Linear hole pattern: {count} holes, R={r:.1f}mm, "
                f"spacing={spacing:.1f}mm"
            )
            continue
        result.append(f"{len(group)} cylinders of same radius R={r:.1f}mm (no pattern detected)")
    return result


def detect_symmetry(
    info: ShapeInfo,
    tolerance: float = 1.0,
    area_tolerance: float = 1.0,
) -> list[str]:
    com = info.center_of_mass
    if com is None:
        return []
    face_list: list[dict] = []
    for solid in info.solids:
        for face in solid.faces:
            if face.center is None:
                continue
            face_list.append({
                "geom_type": face.geom_type,
                "radius": face.radius,
                "center": face.center,
                "area": face.area,
                "matched": False,
            })
    if len(face_list) < 2:
        return []
    result = []
    planes = [("YZ", 0), ("XZ", 1), ("XY", 2)]
    for plane_name, axis_idx in planes:
        for fl in face_list:
            fl["matched"] = False
        symmetric_count = 0
        for i, fa in enumerate(face_list):
            if fa["matched"]:
                continue
            # Check if face lies on the symmetry plane (self-symmetric)
            on_plane = abs(fa["center"][axis_idx] - com[axis_idx]) < tolerance
            if on_plane:
                fa["matched"] = True
                symmetric_count += 1
                continue
            mirrored = list(fa["center"])
            mirrored[axis_idx] = 2 * com[axis_idx] - mirrored[axis_idx]
            mirrored_t = tuple(mirrored)
            for j, fb in enumerate(face_list):
                if j == i or fb["matched"]:
                    continue
                if fa["geom_type"] != fb["geom_type"]:
                    continue
                if fa["radius"] is not None and fb["radius"] is not None:
                    if abs(fa["radius"] - fb["radius"]) > 0.1:
                        continue
                if abs(fa["area"] - fb["area"]) > area_tolerance:
                    continue
                dist = sum(
                    (mirrored_t[k] - fb["center"][k]) ** 2 for k in range(3)
                ) ** 0.5
                if dist < tolerance:
                    fa["matched"] = True
                    fb["matched"] = True
                    symmetric_count += 2
                    break
        total = len(face_list)
        ratio = symmetric_count / total if total > 0 else 0
        if ratio > 0.8:
            result.append(
                f"Symmetric about {plane_name} plane "
                f"({symmetric_count}/{total} faces matched)"
            )
    return result


def detect_wall_thickness(
    info: ShapeInfo,
    max_thickness_ratio: float = 0.15,
    min_area: float = 50.0,
) -> list[str]:
    bb = info.bound_box
    max_dim = max(
        bb.get("XMax", 0) - bb.get("XMin", 0),
        bb.get("YMax", 0) - bb.get("YMin", 0),
        bb.get("ZMax", 0) - bb.get("ZMin", 0),
        1.0,
    )
    planes_info: list[tuple[tuple, tuple, float]] = []
    for solid in info.solids:
        for face in solid.faces:
            if face.geom_type != "Plane" or face.normal is None:
                continue
            if face.area < min_area or face.center is None:
                continue
            planes_info.append((face.normal, face.center, face.area))
    result = []
    seen_thicknesses: list[float] = []
    for i in range(len(planes_info)):
        ni, ci, _ = planes_info[i]
        for j in range(i + 1, len(planes_info)):
            nj, cj, _ = planes_info[j]
            dot = abs(ni[0]*nj[0] + ni[1]*nj[1] + ni[2]*nj[2])
            if dot < 0.99:
                continue
            dist = abs(
                (cj[0]-ci[0])*ni[0] + (cj[1]-ci[1])*ni[1] + (cj[2]-ci[2])*ni[2]
            )
            if dist < 0.1:
                continue
            ratio = dist / max_dim
            if ratio < max_thickness_ratio:
                if not any(abs(dist - st) < 0.5 for st in seen_thicknesses):
                    seen_thicknesses.append(dist)
                    result.append(
                        f"Thin wall: {dist:.1f}mm thick "
                        f"(normal=({ni[0]:.2f},{ni[1]:.2f},{ni[2]:.2f}))"
                    )
    return result


def detect_topology_issues(info: ShapeInfo) -> list[str]:
    """Detect topology problems like disconnected solids."""
    issues = []
    if info.solid_count == 0:
        issues.append(
            "No solid components — shape is not a valid solid. "
            "Fix: check that boolean inputs overlap. "
            "For hollow objects: inner must be fully inside outer."
        )
    elif info.solid_count > 1:
        issues.append(
            f"{info.solid_count} disconnected solids — parts not fused. "
            f"Fix: translate to create at least 0.5mm overlap, then fuse(). "
            f"Example: handle.translate(Vector(-1, 0, 0)); result = body.fuse(handle)"
        )
    if info.shape_type == "Compound":
        issues.append(
            "Shape is a Compound (not a Solid) — boolean operation created a wrapper. "
            "Fix: if len(result.Solids) == 1: result = result.Solids[0]"
        )
    return issues


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

    topo_issues = detect_topology_issues(info)
    if topo_issues:
        lines.append("  Topology warnings:")
        for issue in topo_issues:
            lines.append(f"    - {issue}")
    elif info.solid_count == 1:
        lines.append("  Topology: single manifold solid (OK)")

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

    cones = detect_conical_faces(info)
    if cones:
        lines.append("  Detected conical features:")
        for desc in cones:
            lines.append(f"    - Cone {desc}")

    spheres = detect_spherical_faces(info)
    if spheres:
        lines.append("  Detected spherical features:")
        for desc in spheres:
            lines.append(f"    - Sphere {desc}")

    helices = detect_helical_faces(info)
    if helices:
        lines.append("  Detected thread features:")
        for desc in helices:
            lines.append(f"    - {desc}")

    holes = detect_hole_patterns(info)
    if holes:
        lines.append("  Detected hole patterns:")
        for desc in holes:
            lines.append(f"    - {desc}")

    sym = detect_symmetry(info)
    if sym:
        lines.append("  Symmetry:")
        for desc in sym:
            lines.append(f"    - {desc}")

    walls = detect_wall_thickness(info)
    if walls:
        lines.append("  Thin-wall structures:")
        for desc in walls:
            lines.append(f"    - {desc}")

    return "\n".join(lines)
