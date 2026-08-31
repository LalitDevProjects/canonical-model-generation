"""
Ingestion and Normalization (Section 4)

Handles reading diverse input sources (XSD, WSDL, OpenAPI, custom contracts)
and normalizing them into the common AttributeRecord representation.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

import yaml

from ..models import (
    AttributeRecord,
    DataType,
    DomainArea,
    Region,
    SanitisationLevel,
    SourceArtefact,
    SourceType,
)


class ConnectorInterface(ABC):
    """
    Base interface for input connectors (Section 4.1).
    
    Each connector handles a specific input format and produces
    normalized AttributeRecords.
    """

    source_type: SourceType

    @abstractmethod
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """
        Check if this connector can parse the given content.
        
        Args:
            content: The raw content to check
            filename: Optional filename for heuristic checking
            
        Returns:
            True if this connector can parse the content
        """
        pass

    @abstractmethod
    def parse(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Parse source artifact and extract attributes.
        
        Args:
            source_artefact: The source to parse
            
        Returns:
            List of normalized AttributeRecords
        """
        pass

    @abstractmethod
    def infer_data_type(self, type_string: str) -> DataType:
        """
        Infer normalized DataType from source type string.
        
        Args:
            type_string: Type as declared in source
            
        Returns:
            Normalized DataType
        """
        pass


class XSDConnector(ConnectorInterface):
    """Connector for XML Schema (XSD) sources (Section 4.4)."""
    
    source_type = SourceType.XSD
    
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """Check if content is XSD."""
        if filename and filename.endswith(".xsd"):
            return True
        return "<?xml" in content and "xsd:schema" in content
    
    def parse(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Parse XSD schema and extract element definitions.
        
        Navigates XSD schema tree to find elements, attributes, and their
        type definitions, constraints, and cardinality.
        """
        attributes: List[AttributeRecord] = []
        
        try:
            root = ET.fromstring(source_artefact.content_preview + "...")
        except Exception:
            # If content_preview is truncated, return empty for now
            return attributes
        
        # Namespace handling for XSD
        ns = {'xsd': 'http://www.w3.org/2001/XMLSchema'}
        
        # Extract simple type definitions
        for simple_type in root.findall('.//xsd:simpleType', ns):
            type_name = simple_type.get('name', 'Unknown')
            restriction = simple_type.find('xsd:restriction', ns)
            if restriction is not None:
                base_type = restriction.get('base', 'string')
                base_normalized = self.infer_data_type(base_type)
                
                # Extract facets (constraints)
                min_length = restriction.find('xsd:minLength', ns)
                max_length = restriction.find('xsd:maxLength', ns)
                pattern = restriction.find('xsd:pattern', ns)
                
                attr = AttributeRecord(
                    id=uuid4(),
                    source_artefact_id=source_artefact.id,
                    region=source_artefact.region,
                    domain_area=source_artefact.domain_area,
                    xpath_or_reference=f"//xsd:simpleType[@name='{type_name}']",
                    name=type_name,
                    description=f"Simple type: {base_type}",
                    data_type=base_normalized,
                    data_type_original=base_type,
                    min_length=int(min_length.get('value')) if min_length is not None else None,
                    max_length=int(max_length.get('value')) if max_length is not None else None,
                    pattern_regex=pattern.get('value') if pattern is not None else None,
                    extracted_at=datetime.now(timezone.utc),
                )
                attributes.append(attr)
        
        # Extract complex type elements
        for complex_type in root.findall('.//xsd:complexType', ns):
            type_name = complex_type.get('name', 'Unknown')
            
            # Extract sequence elements
            for element in complex_type.findall('.//xsd:element', ns):
                elem_name = element.get('name', 'Unknown')
                elem_type = element.get('type', 'string')
                min_occurs = int(element.get('minOccurs', 0))
                max_occurs = element.get('maxOccurs', 1)
                if max_occurs == 'unbounded':
                    max_occurs = None
                else:
                    max_occurs = int(max_occurs)
                
                attr = AttributeRecord(
                    id=uuid4(),
                    source_artefact_id=source_artefact.id,
                    region=source_artefact.region,
                    domain_area=source_artefact.domain_area,
                    xpath_or_reference=f"//xsd:complexType[@name='{type_name}']/xsd:element[@name='{elem_name}']",
                    name=elem_name,
                    description=f"Part of {type_name}",
                    data_type=self.infer_data_type(elem_type),
                    data_type_original=elem_type,
                    required=min_occurs > 0,
                    min_occurs=min_occurs,
                    max_occurs=max_occurs,
                    parent_element=type_name,
                    extracted_at=datetime.now(timezone.utc),
                )
                attributes.append(attr)
        
        return attributes
    
    def infer_data_type(self, type_string: str) -> DataType:
        """Map XSD types to normalized types."""
        xsd_type_map = {
            "string": DataType.STRING,
            "integer": DataType.INTEGER,
            "int": DataType.INTEGER,
            "long": DataType.INTEGER,
            "decimal": DataType.NUMBER,
            "double": DataType.NUMBER,
            "float": DataType.NUMBER,
            "boolean": DataType.BOOLEAN,
            "date": DataType.DATE,
            "dateTime": DataType.DATETIME,
            "time": DataType.TIME,
            "base64Binary": DataType.BINARY,
        }
        return xsd_type_map.get(type_string, DataType.UNKNOWN)


class WSDLConnector(ConnectorInterface):
    """Connector for Web Service Description Language (WSDL) sources (Section 4.4)."""
    
    source_type = SourceType.WSDL
    
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """Check if content is WSDL."""
        if filename and filename.endswith(".wsdl"):
            return True
        return "<?xml" in content and "definitions" in content and "portType" in content
    
    def parse(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Parse WSDL definition and extract message parameters.
        
        Extracts message definitions and operation parameters from WSDL,
        including embedded XSD type information.
        """
        attributes: List[AttributeRecord] = []
        
        try:
            root = ET.fromstring(source_artefact.content_preview + "...")
        except Exception:
            return attributes
        
        ns = {
            'wsdl': 'http://schemas.xmlsoap.org/wsdl/',
            'soap': 'http://schemas.xmlsoap.org/wsdl/soap/',
            'xsd': 'http://www.w3.org/2001/XMLSchema'
        }
        
        # Extract message definitions
        for message in root.findall('.//wsdl:message', ns):
            message_name = message.get('name', 'Unknown')
            
            for part in message.findall('wsdl:part', ns):
                part_name = part.get('name', 'Unknown')
                part_type = part.get('type') or part.get('element')
                
                attr = AttributeRecord(
                    id=uuid4(),
                    source_artefact_id=source_artefact.id,
                    region=source_artefact.region,
                    domain_area=source_artefact.domain_area,
                    xpath_or_reference=f"//wsdl:message[@name='{message_name}']/wsdl:part[@name='{part_name}']",
                    name=f"{message_name}_{part_name}",
                    description=f"Message part from {message_name}",
                    data_type=self.infer_data_type(part_type or 'string'),
                    data_type_original=part_type or 'string',
                    extracted_at=datetime.now(timezone.utc),
                )
                attributes.append(attr)
        
        # Extract operation parameters
        for operation in root.findall('.//wsdl:operation', ns):
            op_name = operation.get('name', 'Unknown')
            
            for input_elem in operation.findall('wsdl:input', ns):
                input_name = input_elem.get('name', 'input')
                attr = AttributeRecord(
                    id=uuid4(),
                    source_artefact_id=source_artefact.id,
                    region=source_artefact.region,
                    domain_area=source_artefact.domain_area,
                    xpath_or_reference=f"//wsdl:operation[@name='{op_name}']/wsdl:input[@name='{input_name}']",
                    name=f"{op_name}_{input_name}",
                    description=f"Input for operation {op_name}",
                    data_type=DataType.OBJECT,
                    data_type_original="message",
                    required=True,
                    extracted_at=datetime.now(timezone.utc),
                )
                attributes.append(attr)
        
        return attributes
    
    def infer_data_type(self, type_string: str) -> DataType:
        """Map WSDL types (usually XSD-based) to normalized types."""
        return XSDConnector().infer_data_type(type_string)


class OpenAPIConnector(ConnectorInterface):
    """Connector for OpenAPI 3.x specification sources (Section 4.1-4.4)."""
    
    source_type = SourceType.OPENAPI
    
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """Check if content is OpenAPI."""
        if filename and filename.endswith((".yaml", ".yml", ".json")):
            return "openapi" in content or "swagger" in content
        return False
    
    def parse(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Parse OpenAPI specification (JSON/YAML format).
        
        Extracts paths, operations, parameters, and schema definitions
        from OpenAPI 3.x specifications.
        """
        attributes: List[AttributeRecord] = []
        
        try:
            # Try JSON first
            try:
                spec = json.loads(source_artefact.content_preview)
            except json.JSONDecodeError:
                # Try YAML
                spec = yaml.safe_load(source_artefact.content_preview)
        except Exception:
            return attributes
        
        # Extract paths and operations
        paths = spec.get('paths', {})
        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method not in ['get', 'post', 'put', 'delete', 'patch', 'options']:
                    continue
                
                op_id = operation.get('operationId', f"{method}_{path}")
                
                # Extract parameters
                for param in operation.get('parameters', []):
                    param_name = param.get('name', 'Unknown')
                    param_in = param.get('in', 'query')
                    param_schema = param.get('schema', {})
                    param_type = param_schema.get('type', 'string')
                    required = param.get('required', False)
                    
                    attr = AttributeRecord(
                        id=uuid4(),
                        source_artefact_id=source_artefact.id,
                        region=source_artefact.region,
                        domain_area=source_artefact.domain_area,
                        xpath_or_reference=f"paths.{path}.{method}.parameters[{param_name}]",
                        name=param_name,
                        description=f"{method.upper()} {path} - {param_in}",
                        data_type=self.infer_data_type(param_type),
                        data_type_original=param_type,
                        required=required,
                        semantic_hints={param_in},
                        extracted_at=datetime.now(timezone.utc),
                    )
                    attributes.append(attr)
                
                # Extract request body schema
                request_body = operation.get('requestBody', {})
                if request_body:
                    content = request_body.get('content', {})
                    for media_type, media_content in content.items():
                        schema = media_content.get('schema', {})
                        self._extract_schema_properties(
                            schema, f"{op_id}_request", 
                            source_artefact, attributes, f"paths.{path}.{method}.requestBody"
                        )
                
                # Extract response schemas
                responses = operation.get('responses', {})
                for status_code, response_def in responses.items():
                    content = response_def.get('content', {})
                    for media_type, media_content in content.items():
                        schema = media_content.get('schema', {})
                        self._extract_schema_properties(
                            schema, f"{op_id}_response_{status_code}",
                            source_artefact, attributes, f"paths.{path}.{method}.responses.{status_code}"
                        )
        
        # Extract global schemas
        components = spec.get('components', {})
        schemas = components.get('schemas', {})
        for schema_name, schema_def in schemas.items():
            self._extract_schema_properties(
                schema_def, schema_name, source_artefact, 
                attributes, f"components.schemas.{schema_name}"
            )
        
        return attributes
    
    def _extract_schema_properties(
        self,
        schema: Dict[str, Any],
        schema_name: str,
        source_artefact: SourceArtefact,
        attributes: List[AttributeRecord],
        path: str
    ) -> None:
        """Helper to extract properties from a JSON Schema."""
        if not isinstance(schema, dict):
            return
        
        properties = schema.get('properties', {})
        required = schema.get('required', [])
        
        for prop_name, prop_def in properties.items():
            if not isinstance(prop_def, dict):
                continue
            
            prop_type = prop_def.get('type', 'unknown')
            is_required = prop_name in required
            
            # Handle nested arrays
            if prop_type == 'array':
                items = prop_def.get('items', {})
                prop_type = items.get('type', 'object')
            
            attr = AttributeRecord(
                id=uuid4(),
                source_artefact_id=source_artefact.id,
                region=source_artefact.region,
                domain_area=source_artefact.domain_area,
                xpath_or_reference=f"{path}.properties.{prop_name}",
                name=prop_name,
                description=f"Property of {schema_name}: {prop_def.get('description', '')}",
                data_type=self.infer_data_type(prop_type),
                data_type_original=prop_type,
                required=is_required,
                min_length=prop_def.get('minLength'),
                max_length=prop_def.get('maxLength'),
                pattern_regex=prop_def.get('pattern'),
                min_value=prop_def.get('minimum'),
                max_value=prop_def.get('maximum'),
                allowed_values=prop_def.get('enum'),
                parent_element=schema_name,
                extracted_at=datetime.now(timezone.utc),
            )
            attributes.append(attr)
    
    def infer_data_type(self, type_string: str) -> DataType:
        """Map JSON Schema types to normalized types."""
        json_type_map = {
            "string": DataType.STRING,
            "number": DataType.NUMBER,
            "integer": DataType.INTEGER,
            "boolean": DataType.BOOLEAN,
            "array": DataType.ARRAY,
            "object": DataType.OBJECT,
            "null": DataType.UNKNOWN,
        }
        return json_type_map.get(type_string, DataType.UNKNOWN)


class JSONSchemaConnector(ConnectorInterface):
    """Connector for JSON Schema sources."""
    
    source_type = SourceType.JSON_SCHEMA
    
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """Check if content is JSON Schema."""
        if filename and filename.endswith(".json"):
            return "$schema" in content or "properties" in content or "type" in content
        return False
    
    def parse(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Parse JSON Schema and extract property definitions.
        
        Walks the schema tree to find properties, their types, constraints,
        and handles nested objects and array items.
        """
        attributes: List[AttributeRecord] = []
        
        try:
            schema = json.loads(source_artefact.content_preview)
        except json.JSONDecodeError:
            return attributes
        
        # Helper to recursively extract from schema
        def extract_from_schema(s: Dict[str, Any], prefix: str = "") -> None:
            if not isinstance(s, dict):
                return
            
            properties = s.get('properties', {})
            required = s.get('required', [])
            
            for prop_name, prop_def in properties.items():
                if not isinstance(prop_def, dict):
                    continue
                
                prop_type = prop_def.get('type', 'unknown')
                is_required = prop_name in required
                full_name = f"{prefix}.{prop_name}" if prefix else prop_name
                
                attr = AttributeRecord(
                    id=uuid4(),
                    source_artefact_id=source_artefact.id,
                    region=source_artefact.region,
                    domain_area=source_artefact.domain_area,
                    xpath_or_reference=f"$.properties.{full_name}",
                    name=prop_name,
                    description=prop_def.get('description', ''),
                    data_type=self.infer_data_type(prop_type),
                    data_type_original=prop_type,
                    required=is_required,
                    min_length=prop_def.get('minLength'),
                    max_length=prop_def.get('maxLength'),
                    pattern_regex=prop_def.get('pattern'),
                    min_value=prop_def.get('minimum'),
                    max_value=prop_def.get('maximum'),
                    allowed_values=prop_def.get('enum'),
                    extracted_at=datetime.now(timezone.utc),
                )
                attributes.append(attr)
                
                # Recursively handle nested objects
                if prop_type == 'object':
                    nested = prop_def.get('properties', {})
                    if nested:
                        # Create a pseudo-schema for recursion
                        pseudo_schema = {'properties': nested, 'required': prop_def.get('required', [])}
                        extract_from_schema(pseudo_schema, full_name)
        
        extract_from_schema(schema)
        return attributes
    
    def infer_data_type(self, type_string: str) -> DataType:
        """Map JSON types to normalized types."""
        return OpenAPIConnector().infer_data_type(type_string)


class CustomContractConnector(ConnectorInterface):
    """Connector for custom/proprietary contract formats."""
    
    source_type = SourceType.CUSTOM_CONTRACT
    
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """Check if content is custom contract."""
        # Custom connectors are explicitly selected
        return False
    
    def parse(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Parse custom contract format.
        
        Override in subclass for specific formats.
        """
        attributes: List[AttributeRecord] = []
        # TODO: Implement custom parsing in subclass
        return attributes
    
    def infer_data_type(self, type_string: str) -> DataType:
        """Default to unknown for custom formats."""
        return DataType.UNKNOWN


class CodeAnnotationConnector(ConnectorInterface):
    """Connector for extracting contracts from code annotations."""
    
    source_type = SourceType.CODE_ANNOTATION
    
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """Check if content has code annotations."""
        # Look for common patterns
        patterns = ["@Contract", "@ApiModel", "@Schema", "@Property"]
        return any(pattern in content for pattern in patterns)
    
    def parse(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Extract contracts from code annotations (Section 4.5).
        
        Placeholder for code contract inference.
        """
        attributes: List[AttributeRecord] = []
        # TODO: Implement code annotation parsing
        return attributes
    
    def infer_data_type(self, type_string: str) -> DataType:
        """Infer from programming language types."""
        type_map = {
            "str": DataType.STRING,
            "int": DataType.INTEGER,
            "float": DataType.NUMBER,
            "bool": DataType.BOOLEAN,
            "date": DataType.DATE,
            "datetime": DataType.DATETIME,
            "List": DataType.ARRAY,
            "Dict": DataType.OBJECT,
        }
        return type_map.get(type_string, DataType.UNKNOWN)


class IngestionPipeline:
    """
    Main ingestion pipeline orchestrator.
    
    Coordinates connectors and normalization (Section 4).
    """
    
    def __init__(self):
        """Initialize with all available connectors."""
        self.connectors: List[ConnectorInterface] = [
            XSDConnector(),
            WSDLConnector(),
            OpenAPIConnector(),
            JSONSchemaConnector(),
            CodeAnnotationConnector(),
        ]
    
    def ingest(self, source_artefact: SourceArtefact) -> List[AttributeRecord]:
        """
        Ingest a source artifact and produce normalized attributes.
        
        Process:
        1. Select appropriate connector
        2. Parse source content
        3. Apply relevance filtering (Section 4.2)
        4. Normalize types (Section 4.3)
        5. Apply blocking rules
        6. Return AttributeRecords
        
        Args:
            source_artefact: The source to ingest
            
        Returns:
            List of normalized AttributeRecords
        """
        # Find matching connector
        connector = None
        for conn in self.connectors:
            if conn.source_type == source_artefact.source_type:
                connector = conn
                break
        
        if connector is None:
            raise ValueError(f"No connector for {source_artefact.source_type}")
        
        # Parse
        attributes = connector.parse(source_artefact)
        
        # Apply relevance filtering (Section 4.2)
        attributes = self._filter_relevant(attributes)
        
        # Apply type normalization (Section 4.3)
        for attr in attributes:
            if attr.data_type == DataType.UNKNOWN:
                attr.data_type = connector.infer_data_type(attr.data_type_original)
        
        # Apply blocking and sanitisation
        for attr in attributes:
            attr = self._apply_blocking(attr)
            attr = self._apply_sanitisation(attr)
        
        return attributes
    
    def _filter_relevant(self, attributes: List[AttributeRecord]) -> List[AttributeRecord]:
        """
        Filter out irrelevant attributes (Section 4.2).
        
        Removes technical artifacts that don't represent domain data:
        - Metadata fields
        - Internal IDs
        - Technical flags
        - System timestamps
        """
        irrelevant_patterns = {
            "_metadata",
            "_id",
            "_timestamp",
            "_internal",
            "_system",
        }
        
        return [
            attr for attr in attributes
            if not any(
                pattern in attr.name.lower()
                for pattern in irrelevant_patterns
            )
        ]
    
    def _apply_blocking(self, attribute: AttributeRecord) -> AttributeRecord:
        """
        Apply blocking rules.
        
        Marks attributes that should not be included in canonical model.
        """
        # Check for PII and other blocking conditions
        blocking_keywords = {
            "password", "secret", "token", "apikey", "credit_card",
            "ssn", "sin", "account_number"
        }
        
        if any(keyword in attribute.name.lower() for keyword in blocking_keywords):
            attribute.is_blocked = True
            # TODO: Set appropriate blocking_reason
        
        return attribute
    
    def _apply_sanitisation(self, attribute: AttributeRecord) -> AttributeRecord:
        """
        Apply data sanitisation rules.
        
        Sets appropriate sanitisation level based on content.
        """
        pii_indicators = {"email", "phone", "ssn", "credit_card", "account"}
        
        if any(ind in attribute.name.lower() for ind in pii_indicators):
            attribute.sanitisation_level = SanitisationLevel.RESTRICTED
        
        return attribute
    
    def register_connector(self, connector: ConnectorInterface) -> None:
        """Register a custom connector."""
        self.connectors.append(connector)


__all__ = [
    "ConnectorInterface",
    "XSDConnector",
    "WSDLConnector",
    "OpenAPIConnector",
    "JSONSchemaConnector",
    "CustomContractConnector",
    "CodeAnnotationConnector",
    "IngestionPipeline",
]
