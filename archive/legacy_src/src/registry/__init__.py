"""Artefact Registry and Versioning (Section 11)

Versioned storage and query system for canonical models and generated artefacts.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID


class ArtefactRegistry:
    """
    Registry for generated artefacts (Section 11).
    
    Maintains versioned storage of:
    - Canonical contracts (OpenAPI 3.1)
    - Mapping specifications
    - Logical models
    - Coverage reports
    - Release manifests
    """
    
    def __init__(self):
        """Initialize registry."""
        self.artefacts: Dict[UUID, Dict] = {}
        self.versions: Dict[str, List[Dict]] = {}
    
    def register_artefact(
        self,
        artefact_type: str,
        domain_area: str,
        content: Dict[str, Any],
        version: str,
        created_by: str,
    ) -> UUID:
        """
        Register a new artefact (Section 11.1, 11.2, 11.3).
        
        Args:
            artefact_type: Type (canonical_contract, mapping, etc.)
            domain_area: Domain (claims, party, etc.)
            content: Artefact content
            version: Version string
            created_by: Creator
            
        Returns:
            Artefact ID
        """
        artefact_id = UUID(int=0)  # Generate
        
        artefact = {
            "id": artefact_id,
            "type": artefact_type,
            "domain": domain_area,
            "content": content,
            "version": version,
            "created_by": created_by,
            "created_at": datetime.utcnow(),
            "tags": set(),
        }
        
        self.artefacts[artefact_id] = artefact
        
        # Track version
        key = f"{artefact_type}/{domain_area}"
        if key not in self.versions:
            self.versions[key] = []
        self.versions[key].append(artefact)
        
        return artefact_id
    
    def get_artefact(self, artefact_id: UUID) -> Optional[Dict]:
        """Retrieve an artefact."""
        return self.artefacts.get(artefact_id)
    
    def get_latest_version(self, artefact_type: str, domain_area: str) -> Optional[Dict]:
        """Get latest version of an artefact type."""
        key = f"{artefact_type}/{domain_area}"
        versions = self.versions.get(key, [])
        return versions[-1] if versions else None
    
    def query_artefacts(
        self,
        artefact_type: Optional[str] = None,
        domain_area: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Query artefacts by criteria.
        
        Args:
            artefact_type: Optional type filter
            domain_area: Optional domain filter
            tags: Optional tag filter
            
        Returns:
            Matching artefacts
        """
        results = list(self.artefacts.values())
        
        if artefact_type:
            results = [a for a in results if a["type"] == artefact_type]
        
        if domain_area:
            results = [a for a in results if a["domain"] == domain_area]
        
        if tags:
            results = [
                a for a in results
                if any(tag in a["tags"] for tag in tags)
            ]
        
        return results


__all__ = [
    "ArtefactRegistry",
]
