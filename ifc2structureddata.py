#!/usr/bin/env python3
"""
IFC2StructuredData — Convert IFC files to structured data

Outputs:
- attribute.csv: element attributes with has_geometry flag
- relationships.csv: element relationships
- geometry_library.csv: unique parametric geometry definitions (deduplicated)
- geometry_instance.csv: per-element geometry index (all elements with geometry)
- geometry/{guid}.obj + .mtl: mesh files for non-parametric elements only
- meta.json: model metadata
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
from utils.parametric import pre_classify_geometry, extract_parametric_geometry

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


def _sanitize(val):
    """Sanitize a value for CSV output."""
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


def run_parse(
    ifc_file_path: str,
    output_folder: str,
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

    # Pre-classify: parametric (CSV) vs non-parametric (OBJ)
    logger.info('Pre-classifying geometry types...')
    t_classify = time.perf_counter()
    parametric_guids, non_parametric_elements = pre_classify_geometry(elements)
    timings['classify'] = time.perf_counter() - t_classify

    # Step 1: Tessellate non-parametric elements only → OBJ files
    logger.info(f'Step 1/5: Tessellating {len(non_parametric_elements)} non-parametric elements (OBJ)...')
    t1 = time.perf_counter()
    mesh_guids, geom_stats = build_geometry(
        ifc, non_parametric_elements, output_dir=output_folder, num_threads=threads
    )
    timings['mesh'] = time.perf_counter() - t1
    logger.info(f"Mesh: {len(mesh_guids)} OBJ files written")
    memory_mb['after_mesh'] = _log_memory(logger, "After mesh")

    # Combined geometry set: parametric (CSV) + non-parametric (OBJ)
    guids_with_geometry_set = parametric_guids | set(mesh_guids)
    elements_with_geometry = len(guids_with_geometry_set)

    if should_cancel and should_cancel():
        raise UserCancellationRequested('Cancelled after step 1')

    # Step 2: Extract parametric geometry → library + instance CSV
    logger.info('Step 2/5: Extracting parametric geometry (instanced)...')
    t2 = time.perf_counter()
    library_df, instance_df = extract_parametric_geometry(elements, guids_with_geometry_set)

    library_path = os.path.join(output_folder, 'geometry_library.csv')
    instance_path = os.path.join(output_folder, 'geometry_instance.csv')
    library_df.to_csv(library_path, index=False)
    instance_df.to_csv(instance_path, index=False)

    n_definitions = len(library_df)
    n_instances = len(instance_df)
    n_parametric = int(instance_df['definition_id'].notna().sum()) if n_instances > 0 else 0
    timings['parametric'] = time.perf_counter() - t2
    logger.info(f"Parametric: {n_definitions} definitions, {n_instances} instances ({n_parametric} parametric)")
    del library_df, instance_df

    if should_cancel and should_cancel():
        raise UserCancellationRequested('Cancelled after step 2')

    # Step 3: Extract attributes
    logger.info('Step 3/5: Extracting attributes...')
    t3 = time.perf_counter()
    att_df = extract_attributes(elements)

    # Free elements
    elements = None
    gc.collect()
    memory_mb['after_attributes'] = _log_memory(logger, "After attributes")

    # Add has_geometry boolean column
    if 'GlobalId' in att_df.columns:
        att_df['has_geometry'] = att_df['GlobalId'].isin(guids_with_geometry_set)
    else:
        att_df['has_geometry'] = False

    # Sanitize columns for CSV
    for col in att_df.columns:
        if att_df[col].dtype == 'object':
            att_df[col] = att_df[col].map(_sanitize)

    # Drop invalid columns
    none_cols = [c for c in att_df.columns if c is None or (isinstance(c, float) and pd.isna(c))]
    if none_cols:
        att_df = att_df.drop(columns=none_cols)

    attribute_path = os.path.join(output_folder, 'attribute.csv')
    att_df.to_csv(attribute_path, index=False)
    timings['attributes'] = time.perf_counter() - t3
    del att_df
    gc.collect()

    if should_cancel and should_cancel():
        raise UserCancellationRequested('Cancelled after step 3')

    # Step 4: Relationships
    logger.info('Step 4/5: Extracting relationships...')
    t4 = time.perf_counter()
    rel_df = extract_relationships(ifc)
    rel_count = len(rel_df)
    relationships_path = os.path.join(output_folder, 'relationships.csv')
    rel_df.to_csv(relationships_path, index=False)
    timings['relationships'] = time.perf_counter() - t4
    del rel_df
    gc.collect()

    if should_cancel and should_cancel():
        raise UserCancellationRequested('Cancelled after step 4')

    # Step 5: Metadata
    logger.info('Step 5/5: Writing metadata...')
    t5 = time.perf_counter()
    meta = parse_metadata(ifc, ifc_file_path)
    json_path = save_meta(meta, output_folder, 0.0, object_count=num_elements)
    timings['metadata'] = time.perf_counter() - t5

    # Results
    total_time = time.perf_counter() - start
    peak_memory = max(memory_mb.values()) if memory_mb else 0.0

    stats = {
        'total_elements': num_elements,
        'elements_with_geometry': elements_with_geometry,
        'parametric_elements': len(parametric_guids),
        'mesh_elements': len(mesh_guids),
        'geometry_definitions': n_definitions,
        'relationships_count': rel_count,
        'mesh': geom_stats,
    }

    # Print summary
    print(f"\n{'='*50}")
    print(f"Total Elements:     {num_elements}")
    print(f"With Geometry:      {elements_with_geometry}")
    print(f"  Parametric (CSV): {len(parametric_guids)}")
    print(f"  Mesh (OBJ):       {len(mesh_guids)}")
    print(f"  Definitions:      {n_definitions}")
    print(f"Open IFC:       {timings.get('open_ifc', 0):.2f}s")
    print(f"Classify:       {timings.get('classify', 0):.2f}s")
    print(f"Mesh:           {timings.get('mesh', 0):.2f}s")
    print(f"Parametric:     {timings.get('parametric', 0):.2f}s")
    print(f"Attributes:     {timings.get('attributes', 0):.2f}s")
    print(f"Relationships:  {timings.get('relationships', 0):.2f}s")
    print(f"Metadata:       {timings.get('metadata', 0):.2f}s")
    print(f"Total:          {total_time:.2f}s")
    print(f"Peak Memory:    {peak_memory:.0f} MB")
    print(f"{'='*50}")

    # Cleanup
    logger.info("Cleaning up...")
    del ifc

    if is_temp:
        try:
            os.remove(actual_path)
        except OSError:
            pass

    gc.collect()
    _cleanup_logging(log_handlers)

    return {
        'success': True,
        'output_folder': output_folder,
        'attribute_file': attribute_path,
        'geometry_folder': os.path.join(output_folder, 'geometry'),
        'geometry_library_file': library_path,
        'geometry_instance_file': instance_path,
        'relationships_file': relationships_path,
        'json_file': json_path,
        'metadata': meta,
        'processing_time': total_time,
        'statistics': stats,
        'timings': timings,
        'memory': memory_mb,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='IFC Parser')
    parser.add_argument('ifc_file', help='Path to IFC file')
    parser.add_argument('output_folder', help='Output directory')
    parser.add_argument('--threads', type=int, default=4, help='Threads (default: 4)')
    args = parser.parse_args()

    result = run_parse(args.ifc_file, args.output_folder, threads=args.threads)

    if result['success']:
        s = result['statistics']
        print(f"\n[SUCCESS] Elements: {s['total_elements']}, "
              f"Geometry: {s['elements_with_geometry']} "
              f"({s['parametric_elements']} parametric, {s['mesh_elements']} mesh)")
        print(f"Output: {args.output_folder}")


if __name__ == '__main__':
    main()
