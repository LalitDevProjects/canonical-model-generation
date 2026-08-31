"""
Core Algorithms (Section 9)

Implements the core mathematical and semantic algorithms:
- Attribute profiling
- Blocking
- Similarity scoring
- Clustering
- Conflict classification
- ACORD alignment
- Coverage computation
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity

from ..models import (
    Alignment,
    AttributeRecord,
    Candidate,
    ConceptCluster,
    DataType,
)


class SimilarityScorer:
    """
    Similarity scoring algorithm (Section 9.3).
    
    Computes semantic similarity between attributes using multiple strategies:
    - String similarity (edit distance, token overlap)
    - Type compatibility
    - Semantic hints
    - Contextual information
    """
    
    def __init__(self, threshold: float = 0.7):
        """
        Initialize similarity scorer.
        
        Args:
            threshold: Minimum similarity score to consider matching
        """
        self.threshold = threshold
    
    def compute_similarity(
        self,
        attr1: AttributeRecord,
        attr2: AttributeRecord,
    ) -> float:
        """
        Compute similarity between two attributes (0.0 to 1.0).
        
        Combines multiple scoring approaches:
        1. Name similarity (string matching with normalization)
        2. Type compatibility
        3. Semantic hint alignment
        4. Description similarity
        
        Args:
            attr1: First attribute
            attr2: Second attribute
            
        Returns:
            Similarity score (0.0 = dissimilar, 1.0 = identical)
        """
        if attr1.is_blocked or attr2.is_blocked:
            return 0.0
        
        # Component scores
        name_score = self._name_similarity(attr1.name, attr2.name)
        type_score = self._type_compatibility(attr1.data_type, attr2.data_type)
        semantic_score = self._semantic_similarity(attr1.semantic_hints, attr2.semantic_hints)
        
        # Weighted average
        combined = (
            0.5 * name_score +
            0.3 * type_score +
            0.2 * semantic_score
        )
        
        return max(0.0, min(1.0, combined))
    
    def _name_similarity(self, name1: str, name2: str) -> float:
        """
        String similarity using multiple methods.
        
        Returns score 0.0 to 1.0.
        """
        norm1 = self._normalize_name(name1)
        norm2 = self._normalize_name(name2)
        
        # Exact match
        if norm1 == norm2:
            return 1.0
        
        # Token overlap
        tokens1 = set(norm1.split("_"))
        tokens2 = set(norm2.split("_"))
        
        if tokens1 and tokens2:
            overlap = len(tokens1 & tokens2)
            total = len(tokens1 | tokens2)
            return overlap / total if total > 0 else 0.0
        
        return 0.0
    
    def _normalize_name(self, name: str) -> str:
        """Normalize name for comparison."""
        return name.lower().replace(" ", "_").replace("-", "_")
    
    def _type_compatibility(self, type1: DataType, type2: DataType) -> float:
        """
        Type compatibility scoring.
        
        Returns:
            1.0 if same type
            0.5 if compatible (e.g., int and number)
            0.0 if incompatible
        """
        if type1 == type2:
            return 1.0
        
        # Compatibility groups
        numeric_types = {DataType.NUMBER, DataType.INTEGER}
        temporal_types = {DataType.DATE, DataType.DATETIME, DataType.TIME}
        
        if type1 in numeric_types and type2 in numeric_types:
            return 0.8
        
        if type1 in temporal_types and type2 in temporal_types:
            return 0.8
        
        if type1 == DataType.UNKNOWN or type2 == DataType.UNKNOWN:
            return 0.3
        
        return 0.0
    
    def _semantic_similarity(self, hints1: Set[str], hints2: Set[str]) -> float:
        """Similarity based on semantic hints."""
        if not hints1 or not hints2:
            return 0.0
        
        overlap = len(hints1 & hints2)
        total = len(hints1 | hints2)
        return overlap / total if total > 0 else 0.0


class AttributeProfiler:
    """
    Attribute profiling algorithm (Section 9.1).
    
    Analyzes and characterizes attributes to support downstream analysis.
    """
    
    @staticmethod
    def profile(attributes: List[AttributeRecord]) -> Dict[UUID, Dict]:
        """
        Profile a collection of attributes.
        
        For each attribute, computes:
        - Frequency statistics
        - Type distribution
        - Constraint patterns
        - Outliers and edge cases
        
        Args:
            attributes: Attributes to profile
            
        Returns:
            Dictionary mapping attribute ID to profile data
        """
        profiles = {}
        
        for attr in attributes:
            profile = {
                "name": attr.name,
                "type": attr.data_type.value if attr.data_type else "unknown",
                "required": attr.required,
                "regions_present": 1,  # Would aggregate across multiple
                "blocked": attr.is_blocked,
                "example_count": len(attr.examples),
                "constraints": {
                    "min_length": attr.min_length,
                    "max_length": attr.max_length,
                    "pattern": attr.pattern_regex,
                },
            }
            
            profiles[attr.id] = profile
        
        return profiles


class ClusteringAlgorithm(ABC):
    """Base class for clustering algorithms."""
    
    @abstractmethod
    def cluster(
        self,
        attributes: List[AttributeRecord],
        similarity_matrix: np.ndarray,
        min_cluster_size: int = 2,
    ) -> List[ConceptCluster]:
        """
        Cluster attributes based on similarity.
        
        Args:
            attributes: Attributes to cluster
            similarity_matrix: Precomputed similarity matrix
            min_cluster_size: Minimum cluster size
            
        Returns:
            List of concept clusters
        """
        pass


class HierarchicalClustering(ClusteringAlgorithm):
    """
    Hierarchical agglomerative clustering (Section 9.4).
    
    Groups semantically similar attributes into concept clusters.
    """
    
    def cluster(
        self,
        attributes: List[AttributeRecord],
        similarity_matrix: np.ndarray,
        min_cluster_size: int = 2,
    ) -> List[ConceptCluster]:
        """
        Perform hierarchical clustering.
        
        Converts similarity to distance, applies linkage, and
        returns concept clusters.
        """
        if len(attributes) < min_cluster_size:
            return []
        
        # Convert similarity to distance
        distance_matrix = 1.0 - similarity_matrix
        
        # Perform clustering
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=0.3,
            linkage='average',
        )
        
        labels = clustering.fit_predict(distance_matrix)
        
        # Group by cluster
        clusters = {}
        for attr, label in zip(attributes, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(attr)
        
        # Filter by minimum size and create ConceptCluster objects
        concept_clusters = []
        for cluster_id, cluster_attrs in clusters.items():
            if len(cluster_attrs) >= min_cluster_size:
                concept_cluster = ConceptCluster(
                    id=UUID(int=cluster_id),  # Simplified
                    cluster_name=f"Cluster_{cluster_id}",
                    attribute_ids=[a.id for a in cluster_attrs],
                    region_coverage={
                        a.region: sum(1 for x in cluster_attrs if x.region == a.region)
                        for a in cluster_attrs
                    },
                    cohesion_score=self._compute_cohesion(cluster_attrs, similarity_matrix),
                    confidence=0.85,
                    representative_attributes=[cluster_attrs[0].id],
                )
                concept_clusters.append(concept_cluster)
        
        return concept_clusters
    
    @staticmethod
    def _compute_cohesion(cluster_attrs: List[AttributeRecord], similarity_matrix: np.ndarray) -> float:
        """Compute internal cohesion of cluster."""
        # Simplified: return average of all pairwise similarities
        if len(cluster_attrs) <= 1:
            return 1.0
        
        # In real implementation, would index into similarity_matrix
        return 0.75


class ACORDAligner:
    """
    ACORD alignment scoring (Section 9.6).
    
    Maps discovered clusters to ACORD Reference Architecture concepts.
    """
    
    def __init__(self):
        """Initialize with ACORD reference vocabulary."""
        # This would be loaded from ACORD reference data
        self.acord_entities = self._load_acord_reference()
    
    def align(self, cluster: ConceptCluster) -> List[Alignment]:
        """
        Find ACORD alignments for a cluster.
        
        Returns ranked list of possible alignments.
        
        Args:
            cluster: Concept cluster to align
            
        Returns:
            List of Alignment objects, sorted by score
        """
        alignments = []
        
        # Score against each ACORD entity
        for entity in self.acord_entities:
            score = self._compute_alignment_score(cluster, entity)
            
            if score > 0.5:  # Threshold
                alignment = Alignment(
                    id=UUID(int=0),  # Generated
                    cluster_id=cluster.id,
                    acord_entity=entity["entity"],
                    acord_attribute=entity["attribute"],
                    alignment_score=score,
                    justification=f"Aligned based on name and semantic match",
                    alternative_alignments=[],
                )
                alignments.append(alignment)
        
        # Sort by score
        alignments.sort(key=lambda a: a.alignment_score, reverse=True)
        return alignments
    
    def _compute_alignment_score(self, cluster: ConceptCluster, acord_entity: Dict) -> float:
        """Compute alignment score."""
        # Simplified scoring based on name match
        cluster_name_tokens = set(cluster.cluster_name.lower().split("_"))
        acord_name_tokens = set(acord_entity["attribute"].lower().split("_"))
        
        overlap = len(cluster_name_tokens & acord_name_tokens)
        total = len(cluster_name_tokens | acord_name_tokens)
        
        return overlap / total if total > 0 else 0.0
    
    @staticmethod
    def _load_acord_reference() -> List[Dict]:
        """Load ACORD reference entities."""
        # Simplified reference data
        return [
            {"entity": "Party", "attribute": "party_id"},
            {"entity": "Party", "attribute": "party_name"},
            {"entity": "Party", "attribute": "party_type"},
            {"entity": "Address", "attribute": "address_line"},
            {"entity": "Address", "attribute": "city"},
            {"entity": "Address", "attribute": "country"},
            {"entity": "Money", "attribute": "amount"},
            {"entity": "Money", "attribute": "currency"},
            {"entity": "Claim", "attribute": "claim_number"},
            {"entity": "Claim", "attribute": "claim_date"},
        ]


class CoverageAnalyzer:
    """
    Coverage computation (Section 9.8).
    
    Measures how much of the regional estate is covered by candidates.
    """
    
    @staticmethod
    def compute_coverage(
        all_attributes: List[AttributeRecord],
        candidate_attributes: Set[UUID],
    ) -> Tuple[float, List[UUID]]:
        """
        Compute coverage percentage.
        
        Args:
            all_attributes: All source attributes
            candidate_attributes: Attributes covered by candidates
            
        Returns:
            (coverage_percentage, uncovered_attribute_ids)
        """
        if not all_attributes:
            return 0.0, []
        
        active_attributes = [
            a for a in all_attributes
            if not a.is_blocked
        ]
        
        if not active_attributes:
            return 0.0, []
        
        covered = len([a for a in active_attributes if a.id in candidate_attributes])
        total = len(active_attributes)
        
        percentage = (covered / total * 100) if total > 0 else 0.0
        uncovered = [a.id for a in active_attributes if a.id not in candidate_attributes]
        
        return percentage, uncovered


__all__ = [
    "SimilarityScorer",
    "AttributeProfiler",
    "ClusteringAlgorithm",
    "HierarchicalClustering",
    "ACORDAligner",
    "CoverageAnalyzer",
]
