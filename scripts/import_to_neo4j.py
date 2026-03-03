#!/usr/bin/env python3
"""Import IFC2StructuredData outputs to Neo4j."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from graph_ingest.dataset import build_graph_dataset
from graph_ingest.neo4j_importer import Neo4jImporter


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import parsed IFC outputs (CSV/OBJ) into Neo4j graph schema."
    )
    parser.add_argument(
        "output_dir",
        help="Directory containing attribute.csv / relationships.csv / geometry_*.csv",
    )
    parser.add_argument(
        "--uri",
        default=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j URI (default: env NEO4J_URI or bolt://localhost:7687)",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("NEO4J_USER", "neo4j"),
        help="Neo4j user (default: env NEO4J_USER or neo4j)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("NEO4J_PASSWORD"),
        help="Neo4j password (default: env NEO4J_PASSWORD)",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("NEO4J_DATABASE", "neo4j"),
        help="Neo4j database (default: env NEO4J_DATABASE or neo4j)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for UNWIND writes (default: 1000)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing BuildingObject / GeometryDefinition nodes before import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build dataset and report only (no Neo4j write)",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Write JSON report to this path (default: <output_dir>/graph_import_report.json)",
    )
    return parser.parse_args()


def _print_summary(report: dict) -> None:
    print("\n" + "=" * 60)
    print("Graph Import Summary")
    print("=" * 60)
    print(f"Output dir:      {report.get('output_dir')}")
    print(f"Dry run:         {report.get('dry_run')}")
    print(f"Imported:        {report.get('import_result', {}).get('imported_counts', {})}")
    print(f"Output counts:   {report.get('dataset_report', {}).get('output_counts', {})}")
    print(f"Dropped rels:    {report.get('dataset_report', {}).get('dropped_relationships', {})}")
    print(f"Dropped geom:    {report.get('dataset_report', {}).get('dropped_uses_geometry', {})}")
    print("=" * 60)


def main() -> int:
    args = _parse_args()
    output_dir = os.path.abspath(args.output_dir)
    if not os.path.isdir(output_dir):
        print(f"[ERROR] Output directory not found: {output_dir}")
        return 2

    dataset, dataset_report = build_graph_dataset(output_dir)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": output_dir,
        "dry_run": bool(args.dry_run),
        "neo4j": {
            "uri": args.uri,
            "user": args.user,
            "database": args.database,
            "batch_size": args.batch_size,
            "replace": bool(args.replace),
        },
        "dataset_report": dataset_report,
        "import_result": {},
    }

    if not args.dry_run:
        if not args.password:
            print(
                "[ERROR] Neo4j password is required. "
                "Pass --password or set NEO4J_PASSWORD."
            )
            return 2
        try:
            importer = Neo4jImporter(
                uri=args.uri,
                user=args.user,
                password=args.password,
                database=args.database,
                batch_size=args.batch_size,
            )
            try:
                result = importer.import_dataset(dataset, replace=args.replace)
                report["import_result"] = result
            finally:
                importer.close()
        except Exception as exc:
            report["import_error"] = str(exc)
            report_path = args.report_path or os.path.join(
                output_dir, "graph_import_report.json"
            )
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"[ERROR] Neo4j import failed: {exc}")
            print(f"Report written: {report_path}")
            return 1

    report_path = args.report_path or os.path.join(output_dir, "graph_import_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    _print_summary(report)
    print(f"Report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
