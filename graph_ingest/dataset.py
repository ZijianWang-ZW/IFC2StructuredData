"""Build graph-ready records from IFC2StructuredData outputs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

REQUIRED_ATTRIBUTE_COLUMNS = {"GlobalId", "type", "Name", "has_geometry"}
REQUIRED_RELATIONSHIP_COLUMNS = {
    "Relating_Object_GUID",
    "Related_Object_GUID",
    "Relationship_Type",
}
REQUIRED_GEOMETRY_INSTANCE_COLUMNS = {
    "GlobalId",
    "method",
    "definition_id",
    "instance_params",
}
REQUIRED_GEOMETRY_LIBRARY_COLUMNS = {
    "definition_id",
    "method",
    "representation_type",
    "geometry_tree",
    "instance_count",
}

# Explicitly dropped in PRD v1.
EXCLUDED_RELATIONSHIP_TYPES = frozenset(
    {
        "IfcRelAssociatesMaterial",
        "IfcRelAssociatesClassification",
        "IfcRelAssignsToGroup",
    }
)


@dataclass
class GraphDataset:
    """In-memory records ready to be imported into Neo4j."""

    building_nodes: List[Dict[str, Any]]
    geometry_nodes: List[Dict[str, Any]]
    relates_edges: List[Dict[str, Any]]
    uses_geometry_edges: List[Dict[str, Any]]


def _read_csv(path: str, required_columns: Set[str]) -> pd.DataFrame:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing required file: {path}")
    df = pd.read_csv(path, dtype=object, keep_default_na=False)
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    return df


def _safe_filename(guid: str) -> str:
    """Escape GUID for case-insensitive filesystems."""
    out = []
    for ch in guid:
        if ch == "_":
            out.append("__")
        elif ch.isupper():
            out.append("_" + ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if text == "":
        return None
    if text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float) and pd.isna(value):
        return None
    if value == "":
        return None
    return value


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _normalize_text(value)
    if not text:
        return False
    return text.lower() in {"1", "true", "yes", "y", "t"}


def _parse_int(value: Any) -> Optional[int]:
    text = _normalize_text(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def _index_attributes(df: pd.DataFrame) -> Tuple[Dict[str, Dict[str, Any]], int]:
    indexed: Dict[str, Dict[str, Any]] = {}
    duplicate_count = 0
    for row in df.to_dict(orient="records"):
        gid = _normalize_text(row.get("GlobalId"))
        if not gid:
            continue
        cleaned = {k: _normalize_value(v) for k, v in row.items()}
        cleaned["GlobalId"] = gid
        if gid in indexed:
            duplicate_count += 1
        indexed[gid] = cleaned
    return indexed, duplicate_count


def _index_geometry_instances(df: pd.DataFrame) -> Tuple[Dict[str, Dict[str, Any]], int]:
    indexed: Dict[str, Dict[str, Any]] = {}
    duplicate_count = 0
    for row in df.to_dict(orient="records"):
        gid = _normalize_text(row.get("GlobalId"))
        if not gid:
            continue
        rec = {
            "GlobalId": gid,
            "method": _normalize_text(row.get("method")),
            "definition_id": _parse_int(row.get("definition_id")),
            "instance_params": _normalize_text(row.get("instance_params")),
        }
        if gid in indexed:
            duplicate_count += 1
        indexed[gid] = rec
    return indexed, duplicate_count


def _index_geometry_library(df: pd.DataFrame) -> Tuple[Dict[int, Dict[str, Any]], int]:
    indexed: Dict[int, Dict[str, Any]] = {}
    duplicate_count = 0
    for row in df.to_dict(orient="records"):
        definition_id = _parse_int(row.get("definition_id"))
        if definition_id is None:
            continue
        rec = {
            "definition_id": definition_id,
            "method": _normalize_text(row.get("method")),
            "representation_type": _normalize_text(row.get("representation_type")),
            "geometry_tree": _normalize_text(row.get("geometry_tree")),
            "instance_count": _parse_int(row.get("instance_count")) or 0,
        }
        if definition_id in indexed:
            duplicate_count += 1
        indexed[definition_id] = rec
    return indexed, duplicate_count


def build_graph_dataset(output_dir: str) -> Tuple[GraphDataset, Dict[str, Any]]:
    """Load parser outputs and produce graph records + import report."""
    attribute_df = _read_csv(
        os.path.join(output_dir, "attribute.csv"), REQUIRED_ATTRIBUTE_COLUMNS
    )
    relationship_df = _read_csv(
        os.path.join(output_dir, "relationships.csv"), REQUIRED_RELATIONSHIP_COLUMNS
    )
    geometry_instance_df = _read_csv(
        os.path.join(output_dir, "geometry_instance.csv"),
        REQUIRED_GEOMETRY_INSTANCE_COLUMNS,
    )
    geometry_library_df = _read_csv(
        os.path.join(output_dir, "geometry_library.csv"),
        REQUIRED_GEOMETRY_LIBRARY_COLUMNS,
    )

    attribute_index, attribute_duplicates = _index_attributes(attribute_df)
    geometry_instance_index, geometry_instance_duplicates = _index_geometry_instances(
        geometry_instance_df
    )
    geometry_library_index, geometry_library_duplicates = _index_geometry_library(
        geometry_library_df
    )

    object_ids = set(attribute_index.keys())

    building_nodes: List[Dict[str, Any]] = []
    for gid, attrs in attribute_index.items():
        geometry_info = geometry_instance_index.get(gid)
        geometry_method = geometry_info.get("method") if geometry_info else None
        geometry_file_path = None
        if geometry_method == "faceted_brep":
            geometry_file_path = os.path.join("geometry", f"{_safe_filename(gid)}.obj")

        all_attrs = {k: v for k, v in attrs.items() if k != "GlobalId"}
        building_nodes.append(
            {
                "GlobalId": gid,
                "props": {
                    "ifcType": _normalize_text(attrs.get("type")),
                    "name": _normalize_text(attrs.get("Name")),
                    "hasGeometry": _parse_bool(attrs.get("has_geometry")),
                    "geometryMethod": geometry_method,
                    "hasGeometryFilePath": geometry_file_path,
                    "attributesJson": json.dumps(all_attrs, ensure_ascii=False),
                },
            }
        )

    geometry_nodes: List[Dict[str, Any]] = []
    for definition_id, rec in geometry_library_index.items():
        geometry_nodes.append(
            {
                "definitionId": definition_id,
                "props": {
                    "method": rec.get("method"),
                    "representationType": rec.get("representation_type"),
                    "geometryTreeJson": rec.get("geometry_tree"),
                    "instanceCount": rec.get("instance_count", 0),
                },
            }
        )

    uses_geometry_edges: List[Dict[str, Any]] = []
    uses_geometry_seen: Set[Tuple[str, int]] = set()
    dropped_uses_geometry_no_definition = 0
    dropped_uses_geometry_unknown_object = 0
    dropped_uses_geometry_unknown_definition = 0
    dropped_uses_geometry_duplicates = 0
    for rec in geometry_instance_index.values():
        gid = rec["GlobalId"]
        definition_id = rec["definition_id"]
        if definition_id is None:
            dropped_uses_geometry_no_definition += 1
            continue
        if gid not in object_ids:
            dropped_uses_geometry_unknown_object += 1
            continue
        if definition_id not in geometry_library_index:
            dropped_uses_geometry_unknown_definition += 1
            continue
        key = (gid, definition_id)
        if key in uses_geometry_seen:
            dropped_uses_geometry_duplicates += 1
            continue
        uses_geometry_seen.add(key)
        uses_geometry_edges.append(
            {
                "src": gid,
                "definitionId": definition_id,
                "instanceParamsJson": rec.get("instance_params"),
            }
        )

    relates_edges: List[Dict[str, Any]] = []
    relates_seen: Set[Tuple[str, str, str]] = set()
    dropped_relationship_missing_data = 0
    dropped_relationship_non_object_endpoint = 0
    dropped_relationship_duplicates = 0
    dropped_relationship_by_type: Dict[str, int] = {
        k: 0 for k in EXCLUDED_RELATIONSHIP_TYPES
    }

    for row in relationship_df.to_dict(orient="records"):
        src = _normalize_text(row.get("Relating_Object_GUID"))
        dst = _normalize_text(row.get("Related_Object_GUID"))
        relationship_type = _normalize_text(row.get("Relationship_Type"))
        if not src or not dst or not relationship_type:
            dropped_relationship_missing_data += 1
            continue

        if relationship_type in EXCLUDED_RELATIONSHIP_TYPES:
            dropped_relationship_by_type[relationship_type] += 1
            continue

        if src not in object_ids or dst not in object_ids:
            dropped_relationship_non_object_endpoint += 1
            continue

        key = (src, dst, relationship_type)
        if key in relates_seen:
            dropped_relationship_duplicates += 1
            continue
        relates_seen.add(key)
        relates_edges.append(
            {
                "src": src,
                "dst": dst,
                "relationshipType": relationship_type,
            }
        )

    dataset = GraphDataset(
        building_nodes=building_nodes,
        geometry_nodes=geometry_nodes,
        relates_edges=relates_edges,
        uses_geometry_edges=uses_geometry_edges,
    )

    report = {
        "output_dir": output_dir,
        "input_counts": {
            "attribute_rows": len(attribute_df),
            "relationship_rows": len(relationship_df),
            "geometry_instance_rows": len(geometry_instance_df),
            "geometry_library_rows": len(geometry_library_df),
        },
        "index_counts": {
            "building_objects_indexed": len(attribute_index),
            "geometry_instances_indexed": len(geometry_instance_index),
            "geometry_definitions_indexed": len(geometry_library_index),
        },
        "output_counts": {
            "building_nodes": len(building_nodes),
            "geometry_nodes": len(geometry_nodes),
            "relates_edges": len(relates_edges),
            "uses_geometry_edges": len(uses_geometry_edges),
        },
        "duplicates": {
            "attribute_globalid": attribute_duplicates,
            "geometry_instance_globalid": geometry_instance_duplicates,
            "geometry_library_definition_id": geometry_library_duplicates,
            "relates_edges": dropped_relationship_duplicates,
            "uses_geometry_edges": dropped_uses_geometry_duplicates,
        },
        "dropped_relationships": {
            "missing_data": dropped_relationship_missing_data,
            "non_object_endpoint": dropped_relationship_non_object_endpoint,
            "excluded_types": dropped_relationship_by_type,
        },
        "dropped_uses_geometry": {
            "no_definition_id": dropped_uses_geometry_no_definition,
            "unknown_object": dropped_uses_geometry_unknown_object,
            "unknown_definition": dropped_uses_geometry_unknown_definition,
        },
    }

    return dataset, report
