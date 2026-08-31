"""Unit tests for data models."""

import pytest
from uuid import uuid4

from src.models import (
    AttributeRecord,
    SourceArtefact,
    DataType,
    DomainArea,
    Region,
    SourceType,
    ProcessingStatus,
)


class TestSourceArtefact:
    """Tests for SourceArtefact contract (C1)."""
    
    def test_create_source_artefact(self):
        """Test creating a source artefact."""
        artifact = SourceArtefact(
            id=uuid4(),
            region=Region.US,
            source_type=SourceType.OPENAPI,
            external_id="test-123",
            name="Test API",
            domain_area=DomainArea.CLAIMS,
            version="1.0",
            content_hash="abc123",
            content_preview="Sample content",
            ingested_by="test_user",
        )
        
        assert artifact.region == Region.US
        assert artifact.source_type == SourceType.OPENAPI
        assert artifact.external_id == "test-123"
    
    def test_source_artefact_identity(self):
        """Test source artifact identity invariant."""
        # Identity is (region, source_type, external_id)
        artifact1 = SourceArtefact(
            id=uuid4(),
            region=Region.US,
            source_type=SourceType.OPENAPI,
            external_id="test-123",
            name="Test 1",
            domain_area=DomainArea.CLAIMS,
            version="1.0",
            content_hash="abc123",
            content_preview="Sample",
            ingested_by="user1",
        )
        
        artifact2 = SourceArtefact(
            id=uuid4(),
            region=Region.US,
            source_type=SourceType.OPENAPI,
            external_id="test-123",
            name="Test 2",  # Different name
            domain_area=DomainArea.CLAIMS,
            version="2.0",  # Different version
            content_hash="xyz789",  # Different hash
            content_preview="Different",
            ingested_by="user2",
        )
        
        # Same region, source_type, external_id means same identity
        assert artifact1.region == artifact2.region
        assert artifact1.source_type == artifact2.source_type
        assert artifact1.external_id == artifact2.external_id


class TestAttributeRecord:
    """Tests for AttributeRecord contract (C5)."""
    
    def test_create_attribute_record(self):
        """Test creating an attribute record."""
        attr = AttributeRecord(
            id=uuid4(),
            source_artefact_id=uuid4(),
            region=Region.US,
            domain_area=DomainArea.CLAIMS,
            xpath_or_reference="/claim/id",
            name="claim_id",
            data_type=DataType.STRING,
            data_type_original="xs:string",
        )
        
        assert attr.name == "claim_id"
        assert attr.data_type == DataType.STRING
        assert attr.required is True  # default
    
    def test_attribute_with_constraints(self):
        """Test attribute with constraints."""
        attr = AttributeRecord(
            id=uuid4(),
            source_artefact_id=uuid4(),
            region=Region.UK,
            domain_area=DomainArea.CLAIMS,
            xpath_or_reference="/root/amount",
            name="claim_amount",
            data_type=DataType.NUMBER,
            data_type_original="decimal",
            required=True,
            min_value=0.0,
            max_value=1_000_000.0,
            min_occurs=1,
            max_occurs=1,
        )
        
        assert attr.min_value == 0.0
        assert attr.max_value == 1_000_000.0
        assert attr.required is True


class TestDataTypeNormalization:
    """Tests for data type normalization."""
    
    def test_data_type_enum(self):
        """Test DataType enum values."""
        assert DataType.STRING.value == "string"
        assert DataType.INTEGER.value == "integer"
        assert DataType.NUMBER.value == "number"
        assert DataType.BOOLEAN.value == "boolean"
        assert DataType.DATE.value == "date"
        assert DataType.UNKNOWN.value == "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
