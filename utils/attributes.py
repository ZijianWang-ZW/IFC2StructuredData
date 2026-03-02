from __future__ import annotations

import glob
import os
from typing import Any, Dict, List

import pandas as pd


UNNECESSARY_ATTRS = {
    'Id', 'OwnerHistory', 'ObjectType', 'Representation', 'ObjectPlacement', 'id',
    'Creation Date', 'Last Modified Date', 'Owning User', 'User organization',
    'Owning Application', 'Change Type'
}


def _round_value(val: Any) -> Any:
    """Round float values to 3 decimal places to reduce storage size."""
    if isinstance(val, float):
        return round(val, 3)
    return val


def extract_property_sets(obj: Any) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    try:
        for definition in getattr(obj, 'IsDefinedBy', []) or []:
            if definition.is_a('IfcRelDefinesByProperties'):
                pset = definition.RelatingPropertyDefinition
                if pset and pset.is_a('IfcPropertySet'):
                    items: Dict[str, Any] = {}
                    for prop in getattr(pset, 'HasProperties', []) or []:
                        if prop.is_a('IfcPropertySingleValue'):
                            val = prop.NominalValue.wrappedValue if getattr(prop, 'NominalValue', None) else None
                            items[prop.Name] = _round_value(val) if val is not None else "None"
                        elif prop.is_a('IfcPropertyEnumeratedValue'):
                            vals = getattr(prop, 'EnumerationValues', None)
                            if vals:
                                # Extract wrapped values and convert to strings
                                str_vals = []
                                for v in vals:
                                    if hasattr(v, 'wrappedValue'):
                                        str_vals.append(str(v.wrappedValue))
                                    else:
                                        str_vals.append(str(v))
                                items[prop.Name] = ', '.join(str_vals)
                            else:
                                items[prop.Name] = "None"
                    # ensure deterministic order of properties within the set
                    properties[pset.Name] = dict(sorted(items.items(), key=lambda kv: kv[0]))
    except Exception:
        pass
    return properties


def extract_quantities(obj: Any) -> Dict[str, Any]:
    all_quantities: Dict[str, Any] = {}
    try:
        for rel in getattr(obj, 'IsDefinedBy', []) or []:
            if rel.is_a('IfcRelDefinesByProperties'):
                pdef = rel.RelatingPropertyDefinition
                if pdef and pdef.is_a('IfcElementQuantity'):
                    qset = pdef.Name
                    qvals: Dict[str, Any] = {}
                    for q in getattr(pdef, 'Quantities', []) or []:
                        info = q.get_info()
                        name = info.get('Name')
                        if name:
                            for k, v in info.items():
                                if k.endswith('Value'):
                                    qvals[name] = _round_value(v) if v is not None else "None"
                    if qset not in all_quantities:
                        all_quantities[qset] = qvals
                    else:
                        all_quantities[qset].update(qvals)
    except Exception:
        pass
    return all_quantities


def extract_materials(obj: Any) -> Dict[str, Any]:
    mats: Dict[str, Any] = {}
    try:
        for assoc in getattr(obj, 'HasAssociations', []) or []:
            if assoc.is_a('IfcRelAssociatesMaterial'):
                material = assoc.RelatingMaterial
                if material.is_a('IfcMaterial'):
                    mats['Material'] = material.Name if material.Name is not None else "None"
                elif material.is_a('IfcMaterialLayerSetUsage'):
                    name = material.ForLayerSet.LayerSetName
                    mats['Material'] = name if name is not None else "None"
    except Exception:
        pass
    return mats


def extract_attributes(objects: List[Any]) -> pd.DataFrame:
    rows = []
    for obj in objects:
        try:
            attrs = obj.get_info()
            # Round float values in base attributes
            attrs = {k: _round_value(v) for k, v in attrs.items()}
            attrs['type'] = obj.is_a()
            attrs.update(extract_property_sets(obj))
            attrs.update(extract_quantities(obj))
            attrs.update(extract_materials(obj))
            rows.append(attrs)
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if 'GlobalId' in df.columns:
        cols = ['GlobalId'] + [c for c in df.columns if c != 'GlobalId']
        df = df[cols]
    df = df.drop(columns=list(UNNECESSARY_ATTRS), errors='ignore')
    return df
