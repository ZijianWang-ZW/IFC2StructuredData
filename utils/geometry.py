"""
Geometry extraction with per-element OBJ + MTL output.

Architecture:
- Processes ALL elements (no instancing/deduplication)
- Uses USE_WORLD_COORDS=True — vertices are in world coordinates (meters)
- Writes individual {guid}.obj + {guid}.mtl files to geometry/ subdirectory
- Returns in-memory geometry data for optional GLB pass
"""

from __future__ import annotations
import gc
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import ifcopenshell.geom as geom

from .color import (
    build_style_and_colour_indexes,
    extract_color_from_material,
    resolve_colors_for_groups,
    log_unresolved_summary,
    is_default_material,
    clear_color_cache,
)

logger = logging.getLogger(__name__)

# Constants
LOG_PROGRESS_INTERVAL = 1000  # Log progress every N elements during geometry processing


def _get_length_unit_scale(ifc_model: Any) -> float:
    """
    Get the scale factor to convert IFC length units to meters.
    geom.iterator always returns coordinates in meters, so we need to match that.
    """
    try:
        import ifcopenshell.util.unit
        return ifcopenshell.util.unit.calculate_unit_scale(ifc_model)
    except Exception:
        return 0.001



def _extract_geometry_data(shape: Any) -> Tuple[List[List[float]], List[List[int]]]:
    """
    Extract vertices and faces from shape geometry.

    Vertices are rounded to 3 decimal places using float64.
    """
    verts_raw = np.asarray(shape.geometry.verts, dtype=np.float64)
    faces_raw = np.asarray(shape.geometry.faces, dtype=np.int32)

    verts_reshaped = verts_raw.reshape(-1, 3)
    verts_rounded = np.round(verts_reshaped, decimals=3)
    faces_reshaped = faces_raw.reshape(-1, 3)

    verts = verts_rounded.tolist()
    faces = faces_reshaped.tolist()

    return verts, faces


def _group_by_value(values: Any) -> Dict[int, List[int]]:
    """Group indices by value using NumPy."""
    try:
        arr = np.asarray(values).ravel().astype(np.int64)
        if arr.size == 0:
            return {}
        unique, inverse = np.unique(arr, return_inverse=True)
        return {int(u): np.nonzero(inverse == i)[0].tolist() for i, u in enumerate(unique)}
    except Exception:
        buckets: Dict[int, List[int]] = {}
        for i, v in enumerate(values):
            buckets.setdefault(int(v), []).append(i)
        return buckets


def _extract_material_groups(shape: Any, obj: Any, styled_by_item: Dict, indexed_colour: Dict) -> List[Dict]:
    """Extract material groups with colors from geometry."""
    gid = getattr(shape, 'guid', None) or 'Unknown'

    try:
        geometry = shape.geometry
        material_ids = getattr(geometry, 'material_ids', None)

        if material_ids is not None:
            buckets = _group_by_value(list(material_ids))
            materials_array = getattr(geometry, 'materials', None)
            groups = []

            for mid, face_indices in buckets.items():
                if mid < 0:
                    groups.append({'rgba': [0.5, 0.5, 0.5, 1.0], 'face_indices': face_indices})
                elif materials_array and mid < len(materials_array):
                    r, g, b, a, _t, name = extract_color_from_material(materials_array[mid])
                    groups.append({'rgba': [r, g, b, a], 'face_indices': face_indices, 'material_name': name})
                else:
                    groups.append({'rgba': [0.5, 0.5, 0.5, 1.0], 'face_indices': face_indices})

            obj_type = obj.is_a() if obj and hasattr(obj, 'is_a') else None
            has_defaults = any(is_default_material(g.get('material_name', 'Default'), g['rgba'], obj_type, 0.0) for g in groups)
            if has_defaults:
                resolve_colors_for_groups(groups, obj, styled_by_item, indexed_colour, gid)

            return groups
    except Exception:
        pass

    num_faces = len(getattr(shape.geometry, 'faces', [])) // 3 if hasattr(shape, 'geometry') else 0
    return [{'rgba': [0.5, 0.5, 0.5, 1.0], 'face_indices': list(range(num_faces))}]


def _make_geom_settings() -> Any:
    """Create geometry iterator settings."""
    settings = geom.settings()

    def try_set(key_variants: List[str], value: Any):
        for key in key_variants:
            try:
                attr = getattr(settings, key, key)
                settings.set(attr, value)
                return
            except Exception:
                continue

    try_set(['USE_WORLD_COORDS', 'use-world-coords'], True)
    try_set(['APPLY_DEFAULT_MATERIALS', 'apply-default-materials'], True)
    try_set(['INCLUDE_STYLES', 'include-styles'], True)
    try_set(['INCLUDE_CURVES', 'include-curves'], False)
    try_set(['USE_BREP_DATA', 'use-brep-data'], False)
    try_set(['WELD_VERTICES', 'weld-vertices'], True)
    try_set(['FASTER_BOOLEANS', 'faster-booleans'], True)
    try_set(['no-normals'], True)
    try_set(['MESHER_IS_RELATIVE', 'mesher-is-relative'], True)
    try_set(['MESHER_LINEAR_DEFLECTION', 'mesher-linear-deflection'], 0.03)
    try_set(['MESHER_ANGULAR_DEFLECTION', 'mesher-angular-deflection'], 1.0)
    try_set(['CIRCLE_SEGMENTS', 'circle-segments'], 12)

    return settings


def _safe_filename(guid: str) -> str:
    """Make a GUID filesystem-safe for case-insensitive filesystems.

    IFC GlobalIds are case-sensitive (Base64 encoding), but macOS/Windows
    filesystems are case-insensitive. We escape uppercase letters:
    'A' -> '_a', '_' -> '__' to guarantee unique filenames.
    """
    out = []
    for ch in guid:
        if ch == '_':
            out.append('__')
        elif ch.isupper():
            out.append('_' + ch.lower())
        else:
            out.append(ch)
    return ''.join(out)


def _write_mtl_file(path: str, material_groups: List[Dict]) -> None:
    """Write a Wavefront MTL file for material groups."""
    with open(path, 'w', encoding='utf-8') as f:
        for i, group in enumerate(material_groups):
            rgba = group.get('rgba', [0.5, 0.5, 0.5, 1.0])
            r, g, b = rgba[0], rgba[1], rgba[2]
            a = rgba[3] if len(rgba) > 3 else 1.0
            mat_name = f"material_{i}"
            f.write(f"newmtl {mat_name}\n")
            f.write(f"Kd {r:.4f} {g:.4f} {b:.4f}\n")
            if a < 0.999:
                f.write(f"d {a:.4f}\n")
            f.write("illum 1\n")
            f.write("\n")


def _write_obj_file(path: str, guid: str, vertices: List[List[float]], faces: List[List[int]], material_groups: List[Dict]) -> None:
    """Write a Wavefront OBJ file for a single element."""
    mtl_filename = os.path.basename(path).replace('.obj', '.mtl')

    with open(path, 'w', encoding='utf-8') as f:
        f.write(f"# IFC Element: {guid}\n")
        f.write(f"mtllib {mtl_filename}\n\n")

        # Write vertices
        for v in vertices:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")

        f.write("\n")

        # Build face-to-group mapping
        face_to_group: Dict[int, int] = {}
        for gi, group in enumerate(material_groups):
            for fi in group.get('face_indices', []):
                face_to_group[fi] = gi

        # Write faces grouped by material
        for gi, group in enumerate(material_groups):
            mat_name = f"material_{gi}"
            f.write(f"usemtl {mat_name}\n")
            for fi in group.get('face_indices', []):
                if fi < len(faces):
                    face = faces[fi]
                    # OBJ faces are 1-indexed
                    f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")
            f.write("\n")


def build_geometry(
    ifc_model: Any,
    elements: Optional[List[Any]] = None,
    output_dir: str = '.',
    *,
    num_threads: int = 4
) -> Tuple[List[str], List[Dict], Dict[str, Any]]:
    """
    Extract geometry and write per-element OBJ + MTL files.

    Uses USE_WORLD_COORDS=True so vertices are already in world coordinates (meters).
    No instancing, no deduplication — every element gets its own geometry files.

    Args:
        ifc_model: Loaded IFC model
        elements: List of IFC elements to process
        output_dir: Base output directory (geometry/ subfolder will be created)
        num_threads: Number of threads for geometry iterator

    Returns:
        - guids_with_geometry: List[str] of GlobalIds that have geometry
        - geometry_memory: List[Dict] with keys {GlobalId, vertices, faces, material_groups}
          for optional GLB pass
        - stats: Dict with processing statistics
    """
    if elements is None:
        elements = list(ifc_model.by_type('IfcProduct'))

    unit_scale = _get_length_unit_scale(ifc_model)
    logger.info(f"[UNITS] Length unit scale: {unit_scale} (to meters)")

    # Create geometry output directory
    geom_dir = os.path.join(output_dir, 'geometry')
    os.makedirs(geom_dir, exist_ok=True)

    # Initialize geometry settings and color indexes
    settings = _make_geom_settings()
    styled_by_item, indexed_colour = build_style_and_colour_indexes(ifc_model)
    logger.info(f"[GEOM] Built color indexes: {len(styled_by_item)} styled items")

    # Initialize iterator with ALL elements
    try:
        it = geom.iterator(
            settings,
            ifc_model,
            include=elements,
            num_threads=num_threads,
            geometry_library="hybrid-cgal-simple-opencascade-cgal"
        )
        if not it.initialize():
            logger.error("[GEOM] Failed to initialize iterator")
            return [], [], {}
    except Exception as e:
        logger.error(f"[GEOM] Iterator error: {e}")
        return [], [], {}

    guids_with_geometry: List[str] = []
    geometry_memory: List[Dict] = []
    stats = {'processed': 0, 'with_geometry': 0, 'without_geometry': 0, 'errors': 0}

    processed = 0
    try:
        while True:
            try:
                s = it.get()
            except Exception:
                s = None

            if s is None:
                if not it.next():
                    break
                continue

            gid = getattr(s, 'guid', None) or getattr(s, 'GlobalId', None)

            processed += 1
            if processed % LOG_PROGRESS_INTERVAL == 0:
                logger.info(f"[GEOM] Processed {processed}/{len(elements)} elements...")

            # No geometry
            if not getattr(s, 'geometry', None):
                stats['without_geometry'] += 1
                if not it.next():
                    break
                continue

            try:
                # Extract materials
                try:
                    obj = ifc_model.by_guid(gid)
                except Exception:
                    obj = None
                groups = _extract_material_groups(s, obj, styled_by_item, indexed_colour)
                material_groups = [
                    {'rgba': [round(c, 2) for c in g['rgba']], 'face_indices': g['face_indices']}
                    for g in groups
                ]

                # Extract geometry data (already world coords in meters)
                verts, faces = _extract_geometry_data(s)

                if verts and faces:
                    # Write OBJ + MTL (use safe filename for case-insensitive FS)
                    safe_name = _safe_filename(gid)
                    obj_path = os.path.join(geom_dir, f"{safe_name}.obj")
                    mtl_path = os.path.join(geom_dir, f"{safe_name}.mtl")
                    _write_obj_file(obj_path, gid, verts, faces, material_groups)
                    _write_mtl_file(mtl_path, material_groups)

                    guids_with_geometry.append(gid)
                    geometry_memory.append({
                        'GlobalId': gid,
                        'vertices': verts,
                        'faces': faces,
                        'material_groups': material_groups,
                    })
                    stats['with_geometry'] += 1
                else:
                    stats['without_geometry'] += 1

            except Exception as e:
                logger.debug(f"[GEOM] Error processing {gid}: {e}")
                stats['errors'] += 1

            if not it.next():
                break
    finally:
        del it
        gc.collect()

    stats['processed'] = processed

    log_unresolved_summary()
    clear_color_cache()

    logger.info(f"[GEOM] Complete: {stats['with_geometry']} elements with geometry, "
                f"{stats['without_geometry']} without, {stats['errors']} errors")

    return guids_with_geometry, geometry_memory, stats
