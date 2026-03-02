"""
Relationship extraction from IFC models.

Extracts spatial, hierarchical, connectivity, and association relationships:
- IfcRelAggregates: Part-of relationships (e.g., Building → Storey)
- IfcRelNests: Nesting relationships (e.g., Equipment → Components)
- IfcRelContainedInSpatialStructure: Spatial containment (e.g., Storey → Wall)
- IfcRelCoversBldgElements: Coverings on elements (e.g., insulation on pipes)
- IfcRelVoidsElement: Openings in elements
- IfcRelFillsElement: Elements filling openings (doors/windows)
- IfcRelConnectsPathElements: Path connections (walls joining)
- IfcRelServicesBuildings: Services serving buildings
- IfcRelAssignsToGroup: Group assignments (systems)
- IfcRelAssociatesMaterial: Material associations
- IfcRelAssociatesClassification: Classification associations
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Configuration for relationship extraction
# (rel_type, relating_attr, related_attr, is_list)
# is_list: True if related_attr returns a list, False if single object
RELATIONSHIP_CONFIGS: List[Tuple[str, str, str, bool]] = [
    # Existing (Decomposition)
    ('IfcRelAggregates', 'RelatingObject', 'RelatedObjects', True),
    ('IfcRelNests', 'RelatingObject', 'RelatedObjects', True),
    ('IfcRelContainedInSpatialStructure', 'RelatingStructure', 'RelatedElements', True),
    
    # Connectivity relationships
    ('IfcRelCoversBldgElements', 'RelatingBuildingElement', 'RelatedCoverings', True),
    ('IfcRelVoidsElement', 'RelatingBuildingElement', 'RelatedOpeningElement', False),
    ('IfcRelFillsElement', 'RelatingOpeningElement', 'RelatedBuildingElement', False),
    ('IfcRelConnectsPathElements', 'RelatingElement', 'RelatedElement', False),
    ('IfcRelServicesBuildings', 'RelatingSystem', 'RelatedBuildings', True),
    
    # Assignment/Association relationships
    ('IfcRelAssignsToGroup', 'RelatingGroup', 'RelatedObjects', True),
    ('IfcRelAssociatesMaterial', 'RelatingMaterial', 'RelatedObjects', True),
    ('IfcRelAssociatesClassification', 'RelatingClassification', 'RelatedObjects', True),
]


def _get_object_identifier(obj: Any) -> Optional[str]:
    """
    Get identifier (GlobalId or Name) for an object.
    
    For IfcProduct objects, use GlobalId.
    For material/classification references, use Name or other identifier.
    """
    # Try GlobalId first (for IfcProduct and most objects)
    guid = getattr(obj, 'GlobalId', None)
    if guid:
        return guid
    
    # For material/classification references, try Name
    name = getattr(obj, 'Name', None)
    if name:
        return str(name)
    
    # Try other common identifier attributes
    for attr in ['Identification', 'ItemReference', 'id']:
        val = getattr(obj, attr, None)
        if val:
            return str(val)
    
    return None


def _get_object_type(obj: Any) -> str:
    """Get the IFC type name for an object."""
    if hasattr(obj, 'is_a'):
        return obj.is_a()
    return 'Unknown'


def _extract_relationship_rows(
    ifc: Any,
    rel_type: str,
    relating_attr: str,
    related_attr: str,
    is_list: bool
) -> List[Dict[str, str]]:
    """
    Extract relationship rows for a specific relationship type.
    
    Args:
        ifc: IFC model
        rel_type: IFC relationship type (e.g., 'IfcRelAggregates')
        relating_attr: Attribute name for relating object
        related_attr: Attribute name for related objects
        is_list: True if related_attr returns a list, False if single object
    
    Returns:
        List of relationship dictionaries
    """
    rows: List[Dict[str, str]] = []
    
    try:
        relationships = ifc.by_type(rel_type)
    except Exception as e:
        logger.warning(f"[RELATIONSHIPS] Failed to get {rel_type}: {e}")
        return rows
    
    for rel in relationships:
        try:
            relating = getattr(rel, relating_attr, None)
            if relating is None:
                continue
            
            relating_type = _get_object_type(relating)
            relating_guid = _get_object_identifier(relating)
            if not relating_guid:
                continue
            
            # Handle both list and single object cases
            if is_list:
                related_objects = getattr(rel, related_attr, []) or []
                # Handle tuple (common in IFC) and list
                if isinstance(related_objects, tuple):
                    related_objects = list(related_objects)
                elif not isinstance(related_objects, list):
                    related_objects = [related_objects] if related_objects else []
            else:
                related_obj = getattr(rel, related_attr, None)
                related_objects = [related_obj] if related_obj is not None else []
            
            for related in related_objects:
                if related is None:
                    continue
                
                try:
                    related_type = _get_object_type(related)
                    related_guid = _get_object_identifier(related)
                    if not related_guid:
                        continue
                    
                    rows.append({
                        'Relating_Object_Type': relating_type,
                        'Relating_Object_GUID': relating_guid,
                        'Related_Object_Type': related_type,
                        'Related_Object_GUID': related_guid,
                        'Relationship_Type': rel_type,
                    })
                except Exception as e:
                    logger.debug(f"[RELATIONSHIPS] Error processing related object in {rel_type}: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"[RELATIONSHIPS] Error processing {rel_type} relationship: {e}")
            continue
    
    return rows


def extract_relationships(ifc: Any) -> pd.DataFrame:
    """
    Extract spatial, hierarchical, connectivity, and association relationships from IFC model.
    
    Extracts:
    - IfcRelAggregates: Part-of relationships (e.g., Building → Storey)
    - IfcRelNests: Nesting relationships (e.g., Equipment → Components)
    - IfcRelContainedInSpatialStructure: Spatial containment (e.g., Storey → Wall)
    - IfcRelCoversBldgElements: Coverings on elements (e.g., insulation on pipes)
    - IfcRelVoidsElement: Openings in elements
    - IfcRelFillsElement: Elements filling openings (doors/windows)
    - IfcRelConnectsPathElements: Path connections (walls joining)
    - IfcRelServicesBuildings: Services serving buildings
    - IfcRelAssignsToGroup: Group assignments (systems)
    - IfcRelAssociatesMaterial: Material associations
    - IfcRelAssociatesClassification: Classification associations
    
    Args:
        ifc: IFC model
    
    Returns:
        DataFrame with columns:
        - Relating_Object_Type, Relating_Object_GUID
        - Related_Object_Type, Related_Object_GUID
        - Relationship_Type
    """
    all_rows: List[Dict[str, str]] = []
    
    for rel_type, relating_attr, related_attr, is_list in RELATIONSHIP_CONFIGS:
        rows = _extract_relationship_rows(ifc, rel_type, relating_attr, related_attr, is_list)
        all_rows.extend(rows)
        logger.debug(f"[RELATIONSHIPS] Extracted {len(rows)} {rel_type} relationships")
    
    logger.info(f"[RELATIONSHIPS] Total: {len(all_rows)} relationships extracted")
    
    return pd.DataFrame(all_rows)
