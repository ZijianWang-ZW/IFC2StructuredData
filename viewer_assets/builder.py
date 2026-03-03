"""Build viewer assets from IFC: model.glb + object_index.json."""

from __future__ import annotations

import gc
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import ifcopenshell
import ifcopenshell.geom as geom
import numpy as np
from pygltflib import GLTF2

from utils.color import (
    build_style_and_colour_indexes,
    clear_color_cache,
    extract_color_from_material,
    is_default_material,
    log_unresolved_summary,
    resolve_colors_for_groups,
)
from utils.parquet2glb import convert_geometry_to_glb

logger = logging.getLogger(__name__)

LOG_PROGRESS_INTERVAL = 1000


def _make_geom_settings() -> Any:
    settings = geom.settings()

    def try_set(key_variants: List[str], value: Any) -> None:
        for key in key_variants:
            try:
                attr = getattr(settings, key, key)
                settings.set(attr, value)
                return
            except Exception:
                continue

    try_set(["USE_WORLD_COORDS", "use-world-coords"], True)
    try_set(["APPLY_DEFAULT_MATERIALS", "apply-default-materials"], True)
    try_set(["INCLUDE_STYLES", "include-styles"], True)
    try_set(["INCLUDE_CURVES", "include-curves"], False)
    try_set(["USE_BREP_DATA", "use-brep-data"], False)
    try_set(["WELD_VERTICES", "weld-vertices"], True)
    try_set(["FASTER_BOOLEANS", "faster-booleans"], True)
    try_set(["no-normals"], True)
    try_set(["MESHER_IS_RELATIVE", "mesher-is-relative"], True)
    try_set(["MESHER_LINEAR_DEFLECTION", "mesher-linear-deflection"], 0.03)
    try_set(["MESHER_ANGULAR_DEFLECTION", "mesher-angular-deflection"], 1.0)
    try_set(["CIRCLE_SEGMENTS", "circle-segments"], 12)

    return settings


def _extract_geometry_data(shape: Any) -> Tuple[List[List[float]], List[List[int]]]:
    verts_raw = np.asarray(shape.geometry.verts, dtype=np.float64)
    faces_raw = np.asarray(shape.geometry.faces, dtype=np.int32)

    verts_reshaped = verts_raw.reshape(-1, 3)
    verts_rounded = np.round(verts_reshaped, decimals=3)
    faces_reshaped = faces_raw.reshape(-1, 3)

    return verts_rounded.tolist(), faces_reshaped.tolist()


def _group_by_value(values: Any) -> Dict[int, List[int]]:
    try:
        arr = np.asarray(values).ravel().astype(np.int64)
        if arr.size == 0:
            return {}
        unique, inverse = np.unique(arr, return_inverse=True)
        return {int(u): np.nonzero(inverse == i)[0].tolist() for i, u in enumerate(unique)}
    except Exception:
        buckets: Dict[int, List[int]] = {}
        for i, val in enumerate(values):
            buckets.setdefault(int(val), []).append(i)
        return buckets


def _extract_material_groups(shape: Any, obj: Any, styled_by_item: Dict, indexed_colour: Dict) -> List[Dict]:
    gid = getattr(shape, "guid", None) or "Unknown"
    try:
        geometry = shape.geometry
        material_ids = getattr(geometry, "material_ids", None)

        if material_ids is not None:
            buckets = _group_by_value(list(material_ids))
            materials_array = getattr(geometry, "materials", None)
            groups = []
            for mid, face_indices in buckets.items():
                if mid < 0:
                    groups.append({"rgba": [0.5, 0.5, 0.5, 1.0], "face_indices": face_indices})
                elif materials_array and mid < len(materials_array):
                    r, g, b, a, _t, name = extract_color_from_material(materials_array[mid])
                    groups.append(
                        {
                            "rgba": [r, g, b, a],
                            "face_indices": face_indices,
                            "material_name": name,
                        }
                    )
                else:
                    groups.append({"rgba": [0.5, 0.5, 0.5, 1.0], "face_indices": face_indices})

            obj_type = obj.is_a() if obj and hasattr(obj, "is_a") else None
            has_defaults = any(
                is_default_material(g.get("material_name", "Default"), g["rgba"], obj_type, 0.0)
                for g in groups
            )
            if has_defaults:
                resolve_colors_for_groups(groups, obj, styled_by_item, indexed_colour, gid)
            return groups
    except Exception:
        pass

    num_faces = len(getattr(shape.geometry, "faces", [])) // 3 if hasattr(shape, "geometry") else 0
    return [{"rgba": [0.5, 0.5, 0.5, 1.0], "face_indices": list(range(num_faces))}]


def extract_object_index_from_glb(glb_path: str) -> Dict[str, Dict[str, Optional[int]]]:
    """Read GLB and build GlobalId -> node/mesh mapping."""
    gltf = GLTF2().load_binary(glb_path)
    index: Dict[str, Dict[str, Optional[int]]] = {}
    for node_idx, node in enumerate(gltf.nodes or []):
        extras = getattr(node, "extras", None)
        if not isinstance(extras, dict):
            continue
        global_id = extras.get("globalId")
        if not global_id:
            continue
        index[str(global_id)] = {
            "node_index": node_idx,
            "mesh_index": getattr(node, "mesh", None),
            "node_name": getattr(node, "name", None),
        }
    return index


def _collect_geometry_data(ifc: Any, elements: List[Any], threads: int) -> Tuple[List[Dict], Dict[str, int]]:
    settings = _make_geom_settings()
    styled_by_item, indexed_colour = build_style_and_colour_indexes(ifc)

    stats = {
        "processed": 0,
        "with_geometry": 0,
        "without_geometry": 0,
        "errors": 0,
    }
    geometry_data: List[Dict[str, Any]] = []

    iterator = geom.iterator(
        settings,
        ifc,
        include=elements,
        num_threads=threads,
        geometry_library="hybrid-cgal-simple-opencascade-cgal",
    )
    if not iterator.initialize():
        raise RuntimeError("Failed to initialize IfcOpenShell geometry iterator")

    try:
        while True:
            try:
                shape = iterator.get()
            except Exception:
                shape = None

            if shape is None:
                if not iterator.next():
                    break
                continue

            gid = getattr(shape, "guid", None) or getattr(shape, "GlobalId", None)
            stats["processed"] += 1
            if stats["processed"] % LOG_PROGRESS_INTERVAL == 0:
                logger.info(
                    "[VIEWER] Processed %s/%s elements...",
                    stats["processed"],
                    len(elements),
                )

            if not gid or not getattr(shape, "geometry", None):
                stats["without_geometry"] += 1
                if not iterator.next():
                    break
                continue

            try:
                try:
                    obj = ifc.by_guid(gid)
                except Exception:
                    obj = None

                groups = _extract_material_groups(shape, obj, styled_by_item, indexed_colour)
                material_groups = [
                    {"rgba": [round(c, 2) for c in group["rgba"]], "face_indices": group["face_indices"]}
                    for group in groups
                ]
                vertices, faces = _extract_geometry_data(shape)
                if vertices and faces:
                    geometry_data.append(
                        {
                            "GlobalId": gid,
                            "vertices": vertices,
                            "faces": faces,
                            "material_groups": material_groups,
                        }
                    )
                    stats["with_geometry"] += 1
                else:
                    stats["without_geometry"] += 1
            except Exception:
                stats["errors"] += 1

            if not iterator.next():
                break
    finally:
        del iterator
        gc.collect()
        log_unresolved_summary()
        clear_color_cache()

    return geometry_data, stats


def build_viewer_assets(
    ifc_file_path: str,
    output_dir: str,
    *,
    threads: int = 4,
) -> Dict[str, Any]:
    """Build `viewer/model.glb` and `viewer/object_index.json`."""
    if not os.path.isfile(ifc_file_path):
        raise FileNotFoundError(f"IFC file not found: {ifc_file_path}")

    start = time.perf_counter()
    ifc = ifcopenshell.open(ifc_file_path)
    elements = list(ifc.by_type("IfcProduct"))
    viewer_dir = os.path.join(output_dir, "viewer")
    os.makedirs(viewer_dir, exist_ok=True)

    logger.info("[VIEWER] Collecting geometry from IFC...")
    geometry_data, stats = _collect_geometry_data(ifc, elements, threads)
    if not geometry_data:
        raise RuntimeError("No geometry extracted from IFC; cannot build viewer assets")

    glb_path = os.path.join(viewer_dir, "model.glb")
    logger.info("[VIEWER] Building GLB: %s", glb_path)
    convert_geometry_to_glb(geometry_data, glb_path)

    object_index = extract_object_index_from_glb(glb_path)
    index_path = os.path.join(viewer_dir, "object_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(object_index, f, indent=2, ensure_ascii=False)

    elapsed = time.perf_counter() - start
    result = {
        "ifc_file": ifc_file_path,
        "output_dir": output_dir,
        "viewer_dir": viewer_dir,
        "model_glb": glb_path,
        "object_index_json": index_path,
        "elements_total": len(elements),
        "geometry_stats": stats,
        "object_index_count": len(object_index),
        "time_seconds": round(elapsed, 3),
    }

    report_path = os.path.join(viewer_dir, "viewer_build_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    result["report_json"] = report_path
    return result
