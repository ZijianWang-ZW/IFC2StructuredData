# Neo4j Import (Week 1)

## Purpose

Import `IFC2StructuredData` parser outputs into a Property Graph (Neo4j), with V1 filtering rules:

1. Keep only `BuildingObject` and `GeometryDefinition` nodes.
2. Drop material/classification/group-related edges.
3. Keep IFC relationship direction as-is (`Relating -> Related`).

## Command

Dry run (build dataset + report only):

```bash
python scripts/import_to_neo4j.py example_str --dry-run
```

Real import:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='your_password'
export NEO4J_DATABASE=neo4j

python scripts/import_to_neo4j.py example_str --replace
```

## Output

A report JSON is written to:

`<output_dir>/graph_import_report.json`

Key sections:

1. `input_counts`: rows loaded from CSV files.
2. `output_counts`: nodes/edges ready for Neo4j.
3. `dropped_relationships`: filtered relationship stats.
4. `dropped_uses_geometry`: dropped `USES_GEOMETRY` stats.
5. `import_result`: import timing/counts (non dry-run).

## Notes

1. `hasGeometryFilePath` is stored as relative path (`geometry/<safe_guid>.obj`) only for `faceted_brep`.
2. `USES_GEOMETRY` is created only when `definition_id` is present and valid.
3. If Neo4j is unavailable, the script exits gracefully and still writes a report with `import_error`.
