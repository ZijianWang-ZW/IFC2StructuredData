#!/usr/bin/env python3
"""Week 6 acceptance runner for IFC2StructuredData."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.app import create_app
from backend.settings import Settings
from graph_ingest.dataset import build_graph_dataset


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Week6 acceptance checks and write report JSON.")
    parser.add_argument(
        "--output-dir",
        default="example_str",
        help="Parsed IFC output directory (default: example_str)",
    )
    parser.add_argument(
        "--report-path",
        default="docs/week6_acceptance_report.json",
        help="Output JSON report path (default: docs/week6_acceptance_report.json)",
    )
    parser.add_argument(
        "--viewer-index-path",
        default=None,
        help="Viewer object_index.json path (optional)",
    )
    parser.add_argument(
        "--viewer-files-dir",
        default=None,
        help="Viewer files dir for static mount (optional)",
    )
    parser.add_argument(
        "--frontend-dir",
        default="frontend",
        help="Frontend directory for root route test (default: frontend)",
    )
    parser.add_argument(
        "--skip-dry-import",
        action="store_true",
        help="Skip scripts/import_to_neo4j.py --dry-run check",
    )
    return parser.parse_args()


def _req(client: TestClient, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
    response = client.request(method, url, **kwargs)
    payload: Dict[str, Any] = {"status_code": response.status_code}
    try:
        payload["json"] = response.json()
    except Exception:
        payload["text"] = response.text
    return payload


def _safe_get(d: Dict[str, Any], path: List[str], default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def main() -> int:
    args = _parse_args()
    output_dir = os.path.abspath(args.output_dir)
    report_path = os.path.abspath(args.report_path)
    viewer_index_path = (
        os.path.abspath(args.viewer_index_path)
        if args.viewer_index_path
        else os.path.join(output_dir, "viewer", "object_index.json")
    )
    viewer_files_dir = (
        os.path.abspath(args.viewer_files_dir) if args.viewer_files_dir else None
    )
    frontend_dir = os.path.abspath(args.frontend_dir) if args.frontend_dir else None

    dataset, dataset_report = build_graph_dataset(output_dir)
    report: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": output_dir,
        "checks": {},
        "summary": {"pass": False},
    }

    report["checks"]["dataset"] = {
        "building_nodes": len(dataset.building_nodes),
        "geometry_nodes": len(dataset.geometry_nodes),
        "relates_edges": len(dataset.relates_edges),
        "uses_geometry_edges": len(dataset.uses_geometry_edges),
        "dropped_relationships": dataset_report.get("dropped_relationships", {}),
        "dropped_uses_geometry": dataset_report.get("dropped_uses_geometry", {}),
    }

    dry_import_result: Dict[str, Any] = {"skipped": args.skip_dry_import}
    if not args.skip_dry_import:
        cmd = [sys.executable, "scripts/import_to_neo4j.py", output_dir, "--dry-run"]
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        dry_import_result = {
            "command": " ".join(cmd),
            "return_code": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    report["checks"]["dry_import"] = dry_import_result

    settings = Settings(
        graph_store_mode="csv",
        graph_output_dir=output_dir,
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="",
        neo4j_database="neo4j",
        viewer_index_path=viewer_index_path,
        viewer_files_dir=viewer_files_dir,
        viewer_model_url="/viewer-files/model.glb",
        frontend_dir=frontend_dir,
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        api_check: Dict[str, Any] = {}
        health = _req(client, "GET", "/api/health")
        config = _req(client, "GET", "/api/config")
        overview = _req(client, "GET", "/api/graph/overview")
        full = _req(client, "GET", "/api/graph/full", params={"limit": 1000})
        viewer_index = _req(client, "GET", "/api/viewer/index")
        root = _req(client, "GET", "/")

        center_global_id = None
        building_nodes = _safe_get(full, ["json", "nodes", "buildingObjects"], [])
        if building_nodes:
            center_global_id = building_nodes[0].get("GlobalId")

        neighborhood = {"status_code": 0}
        object_detail = {"status_code": 0}
        geometry_detail = {"status_code": 0}
        if center_global_id:
            neighborhood = _req(
                client,
                "GET",
                "/api/graph/neighborhood",
                params={"globalId": center_global_id, "hops": 2, "limit": 500},
            )
            object_detail = _req(client, "GET", f"/api/object/{center_global_id}")

        geometry_nodes = _safe_get(full, ["json", "nodes", "geometryDefinitions"], [])
        if geometry_nodes:
            definition_id = geometry_nodes[0].get("definitionId")
            if definition_id is not None:
                geometry_detail = _req(client, "GET", f"/api/geometry/{int(definition_id)}")

        api_check["health"] = health
        api_check["config"] = config
        api_check["overview"] = {
            "status_code": overview.get("status_code"),
            "building_objects": _safe_get(overview, ["json", "building_objects"]),
            "geometry_definitions": _safe_get(overview, ["json", "geometry_definitions"]),
            "relates_edges": _safe_get(overview, ["json", "relates_edges"]),
        }
        api_check["full"] = {
            "status_code": full.get("status_code"),
            "building_count": len(building_nodes),
            "geometry_count": len(geometry_nodes),
        }
        api_check["viewer_index"] = {
            "status_code": viewer_index.get("status_code"),
            "count": len(viewer_index.get("json", {}))
            if isinstance(viewer_index.get("json"), dict)
            else None,
        }
        api_check["root"] = {"status_code": root.get("status_code")}
        api_check["sample_global_id"] = center_global_id
        api_check["neighborhood"] = {
            "status_code": neighborhood.get("status_code"),
            "building_count": len(_safe_get(neighborhood, ["json", "nodes", "buildingObjects"], [])),
        }
        api_check["object_detail"] = {
            "status_code": object_detail.get("status_code"),
            "ifcType": _safe_get(object_detail, ["json", "object", "ifcType"]),
        }
        api_check["geometry_detail"] = {
            "status_code": geometry_detail.get("status_code"),
            "definitionId": _safe_get(geometry_detail, ["json", "geometry", "definitionId"]),
            "hasGeometryTreeJson": _safe_get(geometry_detail, ["json", "geometry", "geometryTreeJson"])
            is not None,
        }
        report["checks"]["api"] = api_check

        pass_conditions = [
            len(dataset.building_nodes) > 0,
            len(dataset.relates_edges) > 0,
            dry_import_result.get("ok", True),
            health.get("status_code") == 200,
            overview.get("status_code") == 200,
            full.get("status_code") == 200,
            neighborhood.get("status_code") == 200 if center_global_id else False,
            object_detail.get("status_code") == 200 if center_global_id else False,
            geometry_detail.get("status_code") == 200 if geometry_nodes else True,
        ]
    report["summary"] = {
        "pass": all(pass_conditions),
        "pass_conditions": pass_conditions,
    }

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"[WEEK6] Acceptance report written: {report_path}")
    print(f"[WEEK6] PASS={report['summary']['pass']}")
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
