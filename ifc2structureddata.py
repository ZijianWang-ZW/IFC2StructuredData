#!/usr/bin/env python3
"""
IFC2StructuredData — Convert IFC files to structured data

Outputs:
- attribute.csv: element attributes with has_geometry flag
- relationships.csv: element relationships
- geometry/{guid}.obj + .mtl: per-element geometry files (world coords, meters)
- meta.json: model metadata
- model.glb (optional, with --glb flag)
"""

from __future__ import annotations
import argparse
import gc
import json
import logging
import os
import time
import tempfile
from typing import Any, Dict, List, Optional, Callable, Tuple

import ifcopenshell
import pandas as pd
from utils.metadata import parse_metadata, save_meta
from utils.geometry import build_geometry
from utils.relationships import extract_relationships
from utils.attributes import extract_attributes
from utils.parquet2glb import convert_geometry_to_glb

try:
    import psutil
    def _log_memory(logger, stage: str) -> float:
        try:
            rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            logger.info(f"[MEMORY] {stage}: {rss_mb:.0f} MB")
            return rss_mb
        except Exception:
            return 0.0
except ImportError:
    def _log_memory(logger, stage: str) -> float:
        return 0.0

GLB_FILTER_TYPES = ['IfcOpeningElement', 'IfcSpace', 'IfcAnnotation']


class UserCancellationRequested(Exception):
    pass


def _convert_ifc4x3_if_needed(ifc_path: str) -> Tuple[str, bool]:
    """Convert IFC4X3 to IFC4x3_ADD2 if needed."""
    with open(ifc_path, 'r', encoding='utf-8', errors='ignore') as f:
        header = ''.join(f.readline() for _ in range(100))

    if 'IFC4X3' in header.upper() and 'ADD2' not in header.upper():
        with open(ifc_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        content = content.replace("'IFC4X3'", "'IFC4x3_ADD2'", 1).replace("'IFC4x3'", "'IFC4x3_ADD2'", 1)

        fd, temp_path = tempfile.mkstemp(suffix='.ifc', prefix='ifc_temp_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        return temp_path, True

    return ifc_path, False


def _setup_logging(output_folder: str, level: int = logging.INFO) -> Tuple[logging.Logger, List[logging.Handler]]:
    """Setup logging and return logger with its handlers for cleanup."""
    root = logging.getLogger()
    root.setLevel(level)

    handlers_to_cleanup: List[logging.Handler] = []

    for h in root.handlers[:]:
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    handlers_to_cleanup.append(console)

    os.makedirs(output_folder, exist_ok=True)
    fh = logging.FileHandler(os.path.join(output_folder, 'ifc_parser.log'), mode='w', encoding='utf-8')
    fh.setFormatter(fmt)
    root.addHandler(fh)
    handlers_to_cleanup.append(fh)

    return logging.getLogger('ifc2structureddata'), handlers_to_cleanup


def _cleanup_logging(handlers: List[logging.Handler]) -> None:
    """Cleanup logging handlers to prevent memory leaks."""
    root = logging.getLogger()
    for h in handlers:
        try:
            root.removeHandler(h)
            h.close()
        except Exception:
            pass


def run_parse(
    ifc_file_path: str,
    output_folder: str,
    make_glb: bool = False,
    glb_path: Optional[str] = None,
    *,
    threads: int = 4,
    should_cancel: Optional[Callable[[], bool]] = None
) -> Dict[str, Any]:

    start = time.perf_counter()
    timings: Dict[str, float] = {}
    memory_mb: Dict[str, float] = {}

    logger, log_handlers = _setup_logging(output_folder)
    logger.info(f"Starting IFC parsing: {ifc_file_path}")

    if not os.path.exists(ifc_file_path):
        raise FileNotFoundError(f"IFC file not found: {ifc_file_path}")
    os.makedirs(output_folder, exist_ok=True)

    # Convert IFC4X3 if needed
    actual_path, is_temp = _convert_ifc4x3_if_needed(ifc_file_path)
    if is_temp:
        logger.info("Converted IFC4X3 -> IFC4x3_ADD2")

    # Load IFC
    logger.info('Opening IFC file...')
    t0 = time.perf_counter()
    ifc = ifcopenshell.open(actual_path)
    elements = ifc.by_type('IfcProduct')
    num_elements = len(elements)
    timings['open_ifc'] = time.perf_counter() - t0
    logger.info(f"Loaded IFC: {num_elements} elements")
    memory_mb['after_load'] = _log_memory(logger, "After load")

    # Step 1: Extract geometry — write OBJ + MTL per element
    logger.info('Step 1/4: Extracting geometry (OBJ + MTL per element)...')
    t1 = time.perf_counter()
    guids_with_geometry, geometry_memory, geom_stats = build_geometry(
        ifc, elements, output_dir=output_folder, num_threads=threads
    )
    timings['mesh'] = time.perf_counter() - t1
    elements_with_geometry = len(guids_with_geometry)
    guids_with_geometry_set = set(guids_with_geometry)
    logger.info(f"Geometry: {elements_with_geometry} elements with geometry")
    memory_mb['after_mesh'] = _log_memory(logger, "After mesh")

    if should_cancel and should_cancel():
        raise UserCancellationRequested('Cancelled after step 1')

    # Step 2: Extract attributes
    logger.info('Step 2/4: Extracting attributes...')
    t2 = time.perf_counter()
    att_df = extract_attributes(elements)
    elements = None
    gc.collect()
    memory_mb['after_attributes'] = _log_memory(logger, "After attributes")

    # Add has_geometry boolean column
    if 'GlobalId' in att_df.columns:
        att_df['has_geometry'] = att_df['GlobalId'].isin(guids_with_geometry_set)
    else:
        att_df['has_geometry'] = False

    # Sanitize columns for CSV
    def _sanitize(val):
        if val is None:
            return None
        if isinstance(val, (str, int, float, bool)):
            return val
        if isinstance(val, (list, dict)):
            try:
                return json.dumps(val)
            except Exception:
                return str(val)
        return str(val)

    for col in att_df.columns:
        if att_df[col].dtype == 'object':
            att_df[col] = att_df[col].map(_sanitize)

    # Drop invalid columns
    none_cols = [c for c in att_df.columns if c is None or (isinstance(c, float) and pd.isna(c))]
    if none_cols:
        att_df = att_df.drop(columns=none_cols)

    # Write attribute.csv
    attribute_path = os.path.join(output_folder, 'attribute.csv')
    logger.info("Writing attribute.csv...")
    att_df.to_csv(attribute_path, index=False)
    timings['attributes'] = time.perf_counter() - t2
    memory_mb['after_csv'] = _log_memory(logger, "After CSV")
    gc.collect()

    if should_cancel and should_cancel():
        raise UserCancellationRequested('Cancelled after step 2')

    # Step 3: Relationships
    logger.info('Step 3/4: Extracting relationships...')
    t3 = time.perf_counter()
    rel_df = extract_relationships(ifc)
    rel_count = len(rel_df)
    relationships_path = os.path.join(output_folder, 'relationships.csv')
    rel_df.to_csv(relationships_path, index=False)
    timings['relationships'] = time.perf_counter() - t3
    rel_df = None
    gc.collect()

    if should_cancel and should_cancel():
        raise UserCancellationRequested('Cancelled after step 3')

    # Step 4: Metadata
    logger.info('Step 4/4: Writing metadata...')
    t4 = time.perf_counter()
    meta = parse_metadata(ifc, ifc_file_path)
    json_path = save_meta(meta, output_folder, 0.0, object_count=num_elements)
    timings['metadata'] = time.perf_counter() - t4

    # Optional GLB
    glb_created = None
    if make_glb:
        try:
            logger.info('Generating GLB...')
            memory_mb['before_glb'] = _log_memory(logger, "Before GLB")

            # Filter out GLB_FILTER_TYPES
            # Build a set of types to exclude by looking up each guid in att_df
            type_by_guid = {}
            if 'GlobalId' in att_df.columns and 'type' in att_df.columns:
                type_by_guid = dict(zip(att_df['GlobalId'], att_df['type']))

            filtered_geometry = [
                g for g in geometry_memory
                if type_by_guid.get(g['GlobalId']) not in GLB_FILTER_TYPES
            ]
            logger.info(f"Filtered: {len(filtered_geometry)} elements for GLB (from {len(geometry_memory)})")

            t5 = time.perf_counter()
            glb_out = glb_path or os.path.join(output_folder, 'model.glb')
            glb_created = convert_geometry_to_glb(filtered_geometry, glb_out)
            timings['glb'] = time.perf_counter() - t5

            logger.info(f"GLB created: {glb_created}")
            memory_mb['after_glb'] = _log_memory(logger, "After GLB")

            del filtered_geometry
            gc.collect()
        except Exception as e:
            logger.exception(f"GLB generation failed: {e}")
    else:
        timings['glb'] = 0.0

    # Results
    total_time = time.perf_counter() - start
    peak_memory = max(memory_mb.values()) if memory_mb else 0.0

    stats = {
        'total_elements': num_elements,
        'elements_with_geometry': elements_with_geometry,
        'relationships_count': rel_count,
        'geometry': geom_stats,
    }

    # Print summary
    print(f"\n{'='*50}")
    print(f"Total Elements: {num_elements}")
    print(f"Elements with Geometry: {elements_with_geometry}")
    print(f"Open IFC: {timings.get('open_ifc', 0):.2f}s")
    print(f"Mesh: {timings.get('mesh', 0):.2f}s")
    print(f"Attributes: {timings.get('attributes', 0):.2f}s")
    print(f"Relationships: {timings.get('relationships', 0):.2f}s")
    print(f"GLB: {timings.get('glb', 0):.2f}s")
    print(f"Total: {total_time:.2f}s")
    print(f"\nMemory:")
    print(f"  Peak: {peak_memory:.0f} MB")
    print(f"{'='*50}")

    # Cleanup
    logger.info("Cleaning up...")
    del att_df, ifc
    del geometry_memory

    if is_temp:
        try:
            os.remove(actual_path)
        except OSError:
            pass

    gc.collect()
    _cleanup_logging(log_handlers)

    geometry_folder = os.path.join(output_folder, 'geometry')

    return {
        'success': True,
        'output_folder': output_folder,
        'attribute_file': attribute_path,
        'geometry_folder': geometry_folder,
        'relationships_file': relationships_path,
        'json_file': json_path,
        'metadata': meta,
        'processing_time': total_time,
        'statistics': stats,
        'glb_file': glb_created,
        'timings': timings,
        'memory': memory_mb,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='IFC Parser')
    parser.add_argument('ifc_file', help='Path to IFC file')
    parser.add_argument('output_folder', help='Output directory')
    parser.add_argument('--glb', nargs='?', const=True, default=False, help='Generate GLB')
    parser.add_argument('--threads', type=int, default=4, help='Threads (default: 4)')
    args = parser.parse_args()

    make_glb = bool(args.glb)
    glb_path = None if args.glb is True else (args.glb if isinstance(args.glb, str) else None)

    result = run_parse(args.ifc_file, args.output_folder, make_glb=make_glb, glb_path=glb_path, threads=args.threads)

    if result['success']:
        s = result['statistics']
        print(f"\n[SUCCESS] Elements: {s['total_elements']}, Geometry: {s['elements_with_geometry']}")
        print(f"Output: {args.output_folder}")
        if result.get('glb_file'):
            glb_size = os.path.getsize(result['glb_file']) / (1024 * 1024)
            print(f"GLB: {result['glb_file']} ({glb_size:.2f} MB)")


if __name__ == '__main__':
    main()
