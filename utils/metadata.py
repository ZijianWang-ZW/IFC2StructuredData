from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import ifcopenshell

import json 

def _parse_timestamp(timestamp: str) -> str:
    try:
        if '+' in timestamp or (timestamp.count('-') > 2):
            if '+' in timestamp:
                date_part = timestamp.split('+')[0]
            else:
                match = re.match(r'(.+)-(\d{2}:\d{2})$', timestamp)
                date_part = match.group(1) if match else timestamp
            parsed_date = datetime.fromisoformat(date_part)
            return parsed_date.strftime('%Y-%m-%d %H:%M:%S')
        parsed_date = datetime.fromisoformat(timestamp)
        return parsed_date.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return timestamp


def _extract_timestamp(ifc_file: Any) -> Optional[str]:
    try:
        # ifcopenshell 0.8.4+: use ifc_file.header instead of ifc_file.wrapped_data.header
        timestamp = str(ifc_file.header.file_name.time_stamp)
        if timestamp and timestamp != 'None':
            return _parse_timestamp(timestamp)
    except Exception:
        return None
    return None


def parse_metadata(ifc_file: Any, ifc_file_path: Optional[str] = None) -> Dict[str, Any]:
    """Return only metadata (no repeated object info).

    Includes: model_guid, export_date, source, application info, and units.
    """
    meta: Dict[str, Any] = {}
    try:
        # File size (MB)
        try:
            if ifc_file_path:
                size_mb = os.path.getsize(ifc_file_path) / 1_000_000.0
                meta['file_size_mb'] = round(size_mb, 3)
        except Exception:
            pass

        # Export date
        ts = _extract_timestamp(ifc_file)
        if ts:
            meta['export_date'] = ts

        # Source schema
        # ifcopenshell 0.8.4+: use ifc_file.header instead of ifc_file.wrapped_data.header
        try:
            meta['source'] = ifc_file.header.file_schema.schema_identifiers[0]
        except Exception:
            pass

        # Model GUID
        try:
            projects = ifc_file.by_type('IfcProject')
            if projects:
                meta['model_guid'] = projects[0].GlobalId
        except Exception:
            pass

        # Application info
        try:
            apps = ifc_file.by_type('IfcApplication')
            if apps:
                app = apps[0]
                if hasattr(app, 'ApplicationFullName'):
                    meta['application_name'] = app.ApplicationFullName
                if hasattr(app, 'Version'):
                    meta['application_version'] = app.Version
        except Exception:
            pass

        # Units (merged from units.py)
        meta.update(extract_units(ifc_file))

    except Exception as e:
        meta.setdefault('error', str(e))

    return meta


def save_meta(metadata: Dict[str, Any], output_folder: str, processing_time: float, object_count: Optional[int] = None) -> Optional[str]:
    os.makedirs(output_folder, exist_ok=True)
    payload = {
        'metadata': {
            'model_guid': metadata.get('model_guid', 'Unknown'),
            'export_date': metadata.get('export_date', 'Unknown'),
            'source': metadata.get('source', 'Unknown'),
            'application_name': metadata.get('application_name', 'Unknown'),
            'application_version': metadata.get('application_version', 'Unknown'),
            'file_size_mb': metadata.get('file_size_mb', 0.0),
            'object_count': object_count,
            'units': {
                'length_unit': metadata.get('length_unit', 'Unknown'),
                'area_unit': metadata.get('area_unit', 'Unknown'),
                'volume_unit': metadata.get('volume_unit', 'Unknown'),
                'angle_unit': metadata.get('angle_unit', 'Unknown'),
                'mass_unit': metadata.get('mass_unit', 'Unknown'),
            },
            'geometry_units': {
                'note': 'OBJ geometry files contain vertices in world coordinates (meters). Property values remain in original IFC units as specified above.',
                'vertices': 'meters (world coordinates)',
                'format': 'OBJ + MTL per element',
                'properties': 'original IFC units (see length_unit)',
            },
            'processing_info': {
                'processing_time': round(processing_time, 2),
                'processed_date': datetime.now().isoformat(),
            },
        }
    }
    path = os.path.join(output_folder, 'meta.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path
    except Exception:
        return None


def _format_unit(prefix: Optional[str], name: str) -> str:
    if prefix is None:
        return name.lower()

    prefix_map = {
        'MILLI': 'm',
        'CENTI': 'c',
        'DECI': 'd',
        'KILO': 'k',
        'MEGA': 'M',
        'GIGA': 'G',
    }
    name_map = {
        'METRE': 'm',
        'GRAM': 'g',
        'SECOND': 's',
        'AMPERE': 'A',
        'KELVIN': 'K',
        'CANDELA': 'cd',
        'MOLE': 'mol',
        'SQUARE_METRE': 'm²',
        'CUBIC_METRE': 'm³',
        'RADIAN': 'rad',
        'STERADIAN': 'sr',
    }

    prefix_str = prefix_map.get(prefix, prefix.lower() if prefix else '')
    name_str = name_map.get(name, name.lower())
    return f"{prefix_str}{name_str}"


def extract_units(ifc_file: Any) -> Dict[str, Any]:
    units: Dict[str, Any] = {}
    try:
        for unit in ifc_file.by_type('IfcSIUnit'):
            try:
                unit_type = getattr(unit, 'UnitType', None)
                unit_name = getattr(unit, 'Name', None)
                unit_prefix = getattr(unit, 'Prefix', None)

                if unit_type == 'LENGTHUNIT':
                    if unit_prefix == 'MILLI' and unit_name == 'METRE':
                        length_unit = 'mm'
                    elif unit_prefix == 'CENTI' and unit_name == 'METRE':
                        length_unit = 'cm'
                    elif unit_prefix is None and unit_name == 'METRE':
                        length_unit = 'm'
                    elif unit_name == 'INCH':
                        length_unit = 'inch'
                    elif unit_name == 'FOOT':
                        length_unit = 'ft'
                    else:
                        prefix_str = unit_prefix.lower() if unit_prefix else ''
                        name_str = unit_name.lower() if unit_name else ''
                        length_unit = f"{prefix_str}{name_str}"
                    units['length_unit'] = length_unit

                elif unit_type == 'AREAUNIT':
                    units['area_unit'] = _format_unit(unit_prefix, unit_name)
                elif unit_type == 'VOLUMEUNIT':
                    units['volume_unit'] = _format_unit(unit_prefix, unit_name)
                elif unit_type == 'PLANEANGLEUNIT':
                    units['angle_unit'] = _format_unit(unit_prefix, unit_name)
                elif unit_type == 'MASSUNIT':
                    units['mass_unit'] = _format_unit(unit_prefix, unit_name)

            except Exception:
                continue

        for unit in ifc_file.by_type('IfcConversionBasedUnit'):
            try:
                if getattr(unit, 'UnitType', None) == 'PLANEANGLEUNIT' and getattr(unit, 'Name', None) == 'DEGREE':
                    units['angle_unit'] = 'degree'
            except Exception:
                continue

        units.setdefault('length_unit', 'unknown')
        units.setdefault('angle_unit', 'radian')
    except Exception:
        return {'length_unit': 'unknown', 'angle_unit': 'radian'}

    return units