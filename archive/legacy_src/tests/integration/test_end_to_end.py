"""
End-to-End Integration Tests

Tests the complete pipeline from ingestion to candidate generation.
"""

import json
from uuid import uuid4

import pytest

from src.algorithms import ACORDAligner, HierarchicalClustering, SimilarityScorer
from src.ingestion import IngestionPipeline, JSONSchemaConnector
from src.models import (
    AttributeRecord,
    DataType,
    DomainArea,
    Region,
    SourceArtefact,
    SourceType,
)


class TestJSONSchemaIngestion:
    """Test JSON Schema parsing and attribute extraction."""
    
    @pytest.fixture
    def sample_schema(self):
        """Sample JSON Schema for testing."""
        return {
            "type": "object",
            "properties": {
                "party_id": {
                    "type": "string",
                    "description": "Unique party identifier",
                    "minLength": 5,
                    "maxLength": 50,
                },
                "party_name": {
                    "type": "string",
                    "description": "Full name of party",
                },
                "party_type": {
                    "type": "string",
                    "enum": ["individual", "organization", "group"],
                },
            },
            "required": ["party_id", "party_name"],
        }
    
    @pytest.fixture
    def source_artefact(self, sample_schema):
        """Create a test source artefact."""
        content = json.dumps(sample_schema)
        return SourceArtefact(
            id=uuid4(),
            region=Region.US,
            source_type=SourceType.JSON_SCHEMA,
            external_id="test-schema-001",
            name="Party Schema",
            description="Test party schema",
            domain_area=DomainArea.PARTY,
            version="1.0",
            content_hash="abc123",
            content_preview=content[:1000],
            ingested_by="test_user",
        )
    
    def test_connector_can_parse(self, sample_schema):
        """Test that connector recognizes JSON Schema."""
        connector = JSONSchemaConnector()
        content = json.dumps(sample_schema)
        
        # JSONSchemaConnector requires both .json filename AND schema keywords
        assert connector.can_parse(content, filename="schema.json") is True
        assert connector.can_parse('{"type": "object"}', filename="schema.json") is True
        assert connector.can_parse("<xml/>", filename="schema.xml") is False
    
    def test_extract_attributes_from_schema(self, source_artefact):
        """Test extraction of attributes from JSON Schema."""
        connector = JSONSchemaConnector()
        attributes = connector.parse(source_artefact)
        
        # Should extract 3 properties
        assert len(attributes) == 3
        
        # Check party_id attribute
        party_id_attr = next((a for a in attributes if a.name == "party_id"), None)
        assert party_id_attr is not None
        assert party_id_attr.data_type == DataType.STRING
        assert party_id_attr.required is True
        assert party_id_attr.min_length == 5
        assert party_id_attr.max_length == 50
        
        # Check party_type attribute
        party_type_attr = next((a for a in attributes if a.name == "party_type"), None)
        assert party_type_attr is not None
        assert party_type_attr.allowed_values == ["individual", "organization", "group"]


class TestSimilarityScoring:
    """Test semantic similarity scoring."""
    
    @pytest.fixture
    def test_attributes(self):
        """Create test attributes for similarity scoring."""
        return [
            AttributeRecord(
                id=uuid4(),
                source_artefact_id=uuid4(),
                region=Region.US,
                domain_area=DomainArea.PARTY,
                xpath_or_reference="//party_id",
                name="party_id",
                description="Party identifier",
                data_type=DataType.STRING,
                data_type_original="string",
            ),
            AttributeRecord(
                id=uuid4(),
                source_artefact_id=uuid4(),
                region=Region.UK,
                domain_area=DomainArea.PARTY,
                xpath_or_reference="//party_identifier",
                name="party_identifier",
                description="Unique party identifier",
                data_type=DataType.STRING,
                data_type_original="string",
            ),
            AttributeRecord(
                id=uuid4(),
                source_artefact_id=uuid4(),
                region=Region.EU,
                domain_area=DomainArea.PARTY,
                xpath_or_reference="//address_street",
                name="address_street",
                description="Street address",
                data_type=DataType.STRING,
                data_type_original="string",
            ),
        ]
    
    def test_identical_attributes_high_similarity(self, test_attributes):
        """Test that identical attributes score high similarity."""
        scorer = SimilarityScorer()
        attr = test_attributes[0]
        
        # Same attribute to itself - should be very similar
        similarity = scorer.compute_similarity(attr, attr)
        # Name match gives 1.0, type match gives 1.0, no hints gives 0
        # Result: (0.5 * 1.0 + 0.3 * 1.0 + 0.2 * 0.0) = 0.8
        assert similarity >= 0.8
    
    def test_related_attributes_moderate_similarity(self, test_attributes):
        """Test that related attributes score with some similarity."""
        scorer = SimilarityScorer()
        attr1 = test_attributes[0]  # party_id
        attr2 = test_attributes[1]  # party_identifier
        
        similarity = scorer.compute_similarity(attr1, attr2)
        # party_id vs party_identifier have token overlap but not complete match
        # Should be between 0.3 and 0.9
        assert 0.3 <= similarity < 0.9
    
    def test_unrelated_attributes_low_similarity(self, test_attributes):
        """Test that unrelated attributes score low similarity."""
        scorer = SimilarityScorer()
        attr1 = test_attributes[0]  # party_id
        attr3 = test_attributes[2]  # address_street
        
        similarity = scorer.compute_similarity(attr1, attr3)
        assert 0.0 <= similarity < 0.5  # Should be dissimilar


class TestClustering:
    """Test hierarchical clustering algorithm."""
    
    @pytest.fixture
    def clusterable_attributes(self):
        """Create attributes for clustering test."""
        return [
            AttributeRecord(
                id=uuid4(),
                source_artefact_id=uuid4(),
                region=Region.US,
                domain_area=DomainArea.CLAIMS,
                xpath_or_reference="us/claim_id",
                name="claim_id",
                data_type=DataType.STRING,
                data_type_original="string",
            ),
            AttributeRecord(
                id=uuid4(),
                source_artefact_id=uuid4(),
                region=Region.UK,
                domain_area=DomainArea.CLAIMS,
                xpath_or_reference="uk/claim_number",
                name="claim_number",
                data_type=DataType.STRING,
                data_type_original="string",
            ),
            AttributeRecord(
                id=uuid4(),
                source_artefact_id=uuid4(),
                region=Region.US,
                domain_area=DomainArea.CLAIMS,
                xpath_or_reference="us/claim_date",
                name="claim_date",
                data_type=DataType.DATE,
                data_type_original="date",
            ),
        ]
    
    def test_hierarchical_clustering(self, clusterable_attributes):
        """Test hierarchical clustering produces clusters."""
        # Compute similarity matrix
        scorer = SimilarityScorer()
        n = len(clusterable_attributes)
        similarity_matrix = [[0.0] * n for _ in range(n)]
        
        for i in range(n):
            for j in range(n):
                if i == j:
                    similarity_matrix[i][j] = 1.0
                elif i < j:
                    sim = scorer.compute_similarity(
                        clusterable_attributes[i],
                        clusterable_attributes[j]
                    )
                    similarity_matrix[i][j] = sim
                    similarity_matrix[j][i] = sim
        
        # Convert to numpy array
        import numpy as np
        sim_matrix = np.array(similarity_matrix)
        
        # Perform clustering
        clusterer = HierarchicalClustering()
        clusters = clusterer.cluster(
            clusterable_attributes,
            sim_matrix,
            min_cluster_size=1,
        )
        
        # Should produce at least one cluster
        assert len(clusters) >= 1


class TestACORDAlignment:
    """Test ACORD Reference Architecture alignment."""
    
    @pytest.fixture
    def concept_cluster(self):
        """Create a concept cluster for alignment."""
        from src.models import ConceptCluster
        return ConceptCluster(
            id=uuid4(),
            cluster_name="party_identifier",
            attribute_ids=[uuid4()],
            region_coverage={Region.US: 1, Region.UK: 1},
            cohesion_score=0.85,
            confidence=0.9,
            representative_attributes=[uuid4()],
        )
    
    def test_acord_alignment(self, concept_cluster):
        """Test that clusters can be aligned to ACORD entities."""
        aligner = ACORDAligner()
        alignments = aligner.align(concept_cluster)
        
        # The aligner should try to match based on cluster name
        # With name "party_identifier", it may or may not find a direct match
        # depending on the ACORD reference data loaded
        assert isinstance(alignments, list)


class TestIngestionPipeline:
    """Test complete ingestion pipeline."""
    
    def test_pipeline_initialization(self):
        """Test that pipeline initializes with all connectors."""
        pipeline = IngestionPipeline()
        
        assert len(pipeline.connectors) == 5
        assert any(isinstance(c, JSONSchemaConnector) for c in pipeline.connectors)
    
    def test_pipeline_ingests_json_schema(self):
        """Test that pipeline can ingest JSON Schema sources."""
        pipeline = IngestionPipeline()
        
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        
        source = SourceArtefact(
            id=uuid4(),
            region=Region.US,
            source_type=SourceType.JSON_SCHEMA,
            external_id="test-001",
            name="Test Schema",
            domain_area=DomainArea.PARTY,
            version="1.0",
            content_hash="hash",
            content_preview=json.dumps(schema),
            ingested_by="test",
        )
        
        attributes = pipeline.ingest(source)
        
        # Should extract at least 2 attributes
        assert len(attributes) >= 2
        
        # Check they're properly normalized
        for attr in attributes:
            assert attr.source_artefact_id == source.id
            assert attr.region == Region.US
            assert attr.domain_area == DomainArea.PARTY


class TestIntegrationWorkflow:
    """Test integrated workflow from ingestion through alignment."""
    
    def test_complete_workflow(self):
        """Test complete workflow: ingest -> cluster -> align."""
        # 1. Create test sources
        schema1 = {
            "type": "object",
            "properties": {
                "party_id": {"type": "string"},
                "party_name": {"type": "string"},
            },
            "required": ["party_id"],
        }
        
        source1 = SourceArtefact(
            id=uuid4(),
            region=Region.US,
            source_type=SourceType.JSON_SCHEMA,
            external_id="us-001",
            name="US Party Schema",
            domain_area=DomainArea.PARTY,
            version="1.0",
            content_hash="hash1",
            content_preview=json.dumps(schema1),
            ingested_by="test",
        )
        
        # 2. Ingest
        pipeline = IngestionPipeline()
        attributes = pipeline.ingest(source1)
        
        # Should extract at least 1 attribute (filtering may remove some)
        assert len(attributes) >= 1
        
        # 3. Score similarities
        scorer = SimilarityScorer()
        assert all(0 <= scorer.compute_similarity(attributes[0], attributes[i]) <= 1
                  for i in range(len(attributes)))
        
        # 4. Align (if clustering happens)
        if len(attributes) > 0:
            from src.models import ConceptCluster
            test_cluster = ConceptCluster(
                id=uuid4(),
                cluster_name="party_attributes",
                attribute_ids=[a.id for a in attributes[:1]],
                region_coverage={Region.US: len(attributes)},
                cohesion_score=0.8,
                confidence=0.85,
                representative_attributes=[attributes[0].id if attributes else uuid4()],
            )
            
            aligner = ACORDAligner()
            alignments = aligner.align(test_cluster)
            
            # Alignments should be a list (may be empty)
            assert isinstance(alignments, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
