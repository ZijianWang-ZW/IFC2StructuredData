#!/usr/bin/env python3
"""Build viewer assets from IFC: model.glb + object_index.json."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from viewer_assets.builder import build_viewer_assets


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate viewer/model.glb and viewer/object_index.json from IFC."
    )
    parser.add_argument("ifc_file", help="Input IFC file path")
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument(
        "--threads", type=int, default=4, help="IfcOpenShell geometry threads (default: 4)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    return parser.parse_args()


def _setup_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def main() -> int:
    args = _parse_args()
    _setup_logging(args.log_level)

    ifc_path = os.path.abspath(args.ifc_file)
    out_dir = os.path.abspath(args.output_dir)
    if not os.path.isfile(ifc_path):
        print(f"[ERROR] IFC file not found: {ifc_path}")
        return 2

    try:
        result = build_viewer_assets(ifc_path, out_dir, threads=args.threads)
    except Exception as exc:
        viewer_dir = os.path.join(out_dir, "viewer")
        os.makedirs(viewer_dir, exist_ok=True)
        error_path = os.path.join(viewer_dir, "viewer_build_error.json")
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "ifc_file": ifc_path,
            "output_dir": out_dir,
            "error": str(exc),
        }
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"[ERROR] Viewer build failed: {exc}")
        print(f"Error report: {error_path}")
        return 1

    print("\n" + "=" * 60)
    print("Viewer Assets Build Summary")
    print("=" * 60)
    print(f"IFC:                {result['ifc_file']}")
    print(f"Viewer dir:         {result['viewer_dir']}")
    print(f"GLB:                {result['model_glb']}")
    print(f"Object index:       {result['object_index_json']}")
    print(f"Total elements:     {result['elements_total']}")
    print(f"Raw elements:       {result.get('elements_total_raw', result['elements_total'])}")
    print(f"Excluded elements:  {result.get('elements_excluded', 0)}")
    print(f"Excluded IFC types: {', '.join(result.get('excluded_ifc_types', [])) or '-'}")
    print(f"Geometry stats:     {result['geometry_stats']}")
    print(f"Indexed objects:    {result['object_index_count']}")
    print(f"Time:               {result['time_seconds']}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
