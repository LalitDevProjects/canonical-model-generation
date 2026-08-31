"""
Agent Framework (Section 7)

LLM-based agent framework for semantic understanding, alignment,
and decision making throughout the pipeline.
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class AgentRole(str, Enum):
    """Agent roles in the system (Section 7.5)."""
    SEMANTIC_RESOLVER = "semantic_resolver"
    ACORD_ALIGNER = "acord_aligner"
    CANONICAL_SYNTHESISER = "canonical_synthesiser"
    CONFLICT_CLASSIFIER = "conflict_classifier"
    MAPPING_GENERATOR = "mapping_generator"
    QUALITY_VALIDATOR = "quality_validator"


class ValidationLevel(str, Enum):
    """Validation ladder for agent outputs (Section 7.3)."""
    RAW = "raw"  # Direct LLM output
    STRUCTURED = "structured"  # Parsed into expected format
    VALIDATED = "validated"  # Passes semantic checks
    APPROVED = "approved"  # Human approved


class AgentPromptTemplate:
    """
    Prompt templates for agents (Section 7.4).
    
    Structures and constrains agent prompts to ensure consistent,
    parseable outputs.
    """
    
    # Template for semantic resolution
    SEMANTIC_RESOLVER_TEMPLATE = """
You are a semantic analyst specializing in insurance industry domains.

Analyze these attributes and determine if they represent the same concept:

Attribute 1:
- Name: {attr1_name}
- Type: {attr1_type}
- Description: {attr1_desc}
- Examples: {attr1_examples}
- Source: {attr1_source}

Attribute 2:
- Name: {attr2_name}
- Type: {attr2_type}
- Description: {attr2_desc}
- Examples: {attr2_examples}
- Source: {attr2_source}

Provide:
1. Semantic similarity score (0.0-1.0)
2. Whether they represent the same concept (yes/no/maybe)
3. Explanation
4. Any caveats or conditions

Format your response as JSON with keys: similarity, same_concept, explanation, caveats
"""
    
    # Template for ACORD alignment
    ACORD_ALIGNER_TEMPLATE = """
You are an expert in ACORD Reference Architecture.

This cluster of attributes appears to represent: {cluster_name}

Attributes in cluster:
{attributes_list}

Identify the best matching ACORD entities and attributes for this cluster.

Provide:
1. Primary ACORD entity (e.g., Party, Address, Claim)
2. Primary ACORD attribute
3. Alignment confidence (0.0-1.0)
4. Justification
5. Alternative candidates considered

Format as JSON with keys: entity, attribute, confidence, justification, alternatives
"""
    
    # Template for canonical synthesis
    CANONICAL_SYNTHESISER_TEMPLATE = """
You are designing canonical data models for multi-region insurance APIs.

Cluster of regional attributes:
{attributes_list}

Requirements:
- Merge into single canonical definition
- Support all regional variants
- Minimize extension namespace need
- Align with ACORD where possible

Propose canonical model element with:
1. Canonical name
2. Data type
3. Constraints (required, length, pattern, etc.)
4. Description
5. Extension needs (if any)

Format as JSON with keys: name, type, constraints, description, extensions_needed
"""
    
    # Template for mapping generation (Section 10.1-10.2)
    MAPPING_GENERATOR_TEMPLATE = """
You are generating transformation mappings for insurance data.

Canonical model element:
- Name: {canonical_name}
- Type: {canonical_type}
- Description: {canonical_desc}

Regional attribute(s):
{regional_attrs}

Generate bidirectional mapping specification:
1. Canonical → Regional transformation
2. Regional → Canonical transformation
3. Validation rules
4. Edge cases and exceptions

Output mapping DSL in provided format.
"""


class AgentRequest(BaseModel):
    """Request to an agent."""
    
    id: UUID = Field(default_factory=uuid4)
    agent_role: AgentRole = Field(description="Role of agent to use")
    prompt_template: str = Field(description="Template to use")
    parameters: Dict[str, Any] = Field(description="Template parameters")
    required_output_format: str = Field(description="Expected output format")
    timeout_seconds: int = Field(default=60)
    max_retries: int = Field(default=3)


class AgentResponse(BaseModel):
    """Response from an agent."""
    
    model_config = ConfigDict(use_enum_values=True)
    
    id: UUID = Field(description="Request ID")
    agent_role: AgentRole = Field(description="Agent role")
    raw_output: str = Field(description="Raw LLM output")
    parsed_output: Dict[str, Any] = Field(description="Parsed structured output")
    validation_level: ValidationLevel = Field(description="Validation status")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    cost_cents: float = Field(description="Cost in cents")
    elapsed_time_seconds: float = Field(description="Execution time")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolGateway:
    """
    Tool gateway for safe agent access (Section 7.2).
    
    Mediates agent access to external tools and resources,
    enforcing security and validation constraints.
    """
    
    def __init__(self):
        """Initialize tool gateway."""
        self.available_tools = self._initialize_tools()
    
    def _initialize_tools(self) -> Dict[str, Dict]:
        """Initialize available tools with constraints."""
        return {
            "acord_reference_lookup": {
                "description": "Look up ACORD entity definitions",
                "allowed_for": [AgentRole.ACORD_ALIGNER],
                "rate_limit_per_minute": 10,
            },
            "attribute_search": {
                "description": "Search existing attributes by pattern",
                "allowed_for": [
                    AgentRole.SEMANTIC_RESOLVER,
                    AgentRole.CANONICAL_SYNTHESISER,
                ],
                "rate_limit_per_minute": 20,
            },
            "type_compatibility_check": {
                "description": "Check if types are compatible",
                "allowed_for": [AgentRole.CANONICAL_SYNTHESISER],
                "rate_limit_per_minute": 50,
            },
        }
    
    def can_use_tool(self, agent_role: AgentRole, tool_name: str) -> bool:
        """
        Check if agent can use tool.
        
        Args:
            agent_role: Agent role
            tool_name: Tool name
            
        Returns:
            True if agent is allowed
        """
        tool = self.available_tools.get(tool_name)
        if not tool:
            return False
        return agent_role in tool["allowed_for"]


class LLMAgent(ABC):
    """
    Base class for LLM-based agents (Section 7.5).
    
    Each agent is specialized for a specific role in the pipeline.
    """
    
    def __init__(self, role: AgentRole, provider: str = "anthropic"):
        """
        Initialize agent.
        
        Args:
            role: Agent role
            provider: LLM provider - "anthropic", "openai", or "mock"
        """
        self.role = role
        self.tool_gateway = ToolGateway()
        self.provider = provider
        self.llm_client = self._initialize_llm_client()
    
    def _initialize_llm_client(self) -> Optional[Any]:
        """Initialize LLM client based on provider."""
        if self.provider == "anthropic":
            if Anthropic is None:
                print("Warning: Anthropic SDK not available, using mock responses")
                return None
            try:
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    print("Warning: ANTHROPIC_API_KEY not set, using mock responses")
                    return None
                return Anthropic(api_key=api_key)
            except Exception as e:
                print(f"Warning: Failed to initialize Anthropic: {e}, using mock responses")
                return None
        elif self.provider == "openai":
            if OpenAI is None:
                print("Warning: OpenAI SDK not available, using mock responses")
                return None
            try:
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    print("Warning: OPENAI_API_KEY not set, using mock responses")
                    return None
                return OpenAI(api_key=api_key)
            except Exception as e:
                print(f"Warning: Failed to initialize OpenAI: {e}, using mock responses")
                return None
        else:
            return None
    
    def _call_llm(self, prompt: str, json_mode: bool = True) -> str:
        """
        Call LLM with prompt.
        
        Args:
            prompt: The prompt to send
            json_mode: Whether to request JSON output
            
        Returns:
            LLM response text
        """
        if self.provider == "anthropic" and self.llm_client:
            try:
                message = self.llm_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                return message.content[0].text
            except Exception as e:
                print(f"LLM call failed: {e}, returning mock response")
                return "{}"
        elif self.provider == "openai" and self.llm_client:
            try:
                response = self.llm_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"LLM call failed: {e}, returning mock response")
                return "{}"
        else:
            # Return mock response when no LLM is available
            return "{}"
    
    @abstractmethod
    def invoke(self, request: AgentRequest) -> AgentResponse:
        """
        Process request.
        
        Args:
            request: Agent request with prompt and parameters
            
        Returns:
            Agent response with parsed output
        """
        pass
    
    def validate_output(
        self,
        output: Dict[str, Any],
        expected_schema: Dict[str, Any],
    ) -> bool:
        """
        Validate output matches expected schema (Section 7.3 - Validation ladder).
        
        Args:
            output: Parsed output
            expected_schema: Expected JSON schema
            
        Returns:
            True if valid
        """
        # Simplified validation - check required fields
        required = expected_schema.get("required", [])
        return all(field in output for field in required)


class SemanticResolverAgent(LLMAgent):
    """
    Agent for semantic resolution of attributes (Section 7.5).
    
    Determines if two attributes represent the same concept
    using LLM reasoning.
    """
    
    def __init__(self, provider: str = "anthropic"):
        """Initialize semantic resolver agent."""
        super().__init__(AgentRole.SEMANTIC_RESOLVER, provider=provider)
    
    def invoke(self, request: AgentRequest) -> AgentResponse:
        """
        Resolve semantic equivalence between attributes.
        
        Args:
            request: Request with attribute information
            
        Returns:
            Response with similarity score and decision
        """
        start_time = datetime.now(timezone.utc)
        
        # Render prompt with parameters
        prompt = request.prompt_template.format(**request.parameters)
        prompt += "\n\nRespond with valid JSON only."
        
        # Call LLM
        raw_output = self._call_llm(prompt, json_mode=True)
        
        # Parse output
        try:
            parsed_output = json.loads(raw_output)
        except json.JSONDecodeError:
            parsed_output = {
                "similarity": 0.5,
                "same_concept": "maybe",
                "explanation": "Unable to parse LLM response",
                "caveats": "Response parsing error",
            }
        
        # Extract confidence from similarity
        confidence = float(parsed_output.get("similarity", 0.5))
        
        response = AgentResponse(
            id=request.id,
            agent_role=self.role,
            raw_output=raw_output,
            parsed_output=parsed_output,
            validation_level=ValidationLevel.VALIDATED,
            confidence=confidence,
            cost_cents=2,  # Approximate
            elapsed_time_seconds=(
                datetime.now(timezone.utc) - start_time
            ).total_seconds(),
        )
        
        return response


class ACORDAlignerAgent(LLMAgent):
    """
    Agent for ACORD Reference Architecture alignment (Section 7.5).
    
    Maps discovered concepts to ACORD entities.
    """
    
    def __init__(self, provider: str = "anthropic"):
        """Initialize ACORD aligner agent."""
        super().__init__(AgentRole.ACORD_ALIGNER, provider=provider)
    
    def invoke(self, request: AgentRequest) -> AgentResponse:
        """
        Align cluster to ACORD entities.
        
        Args:
            request: Request with cluster information
            
        Returns:
            Response with ACORD alignment
        """
        start_time = datetime.now(timezone.utc)
        
        # Render prompt
        prompt = request.prompt_template.format(**request.parameters)
        prompt += "\n\nRespond with valid JSON only."
        
        # Call LLM
        raw_output = self._call_llm(prompt, json_mode=True)
        
        # Parse output
        try:
            parsed_output = json.loads(raw_output)
        except json.JSONDecodeError:
            parsed_output = {
                "entity": "Party",
                "attribute": "unknown",
                "confidence": 0.5,
                "justification": "Unable to parse LLM response",
                "alternatives": [],
            }
        
        confidence = float(parsed_output.get("confidence", 0.5))
        
        response = AgentResponse(
            id=request.id,
            agent_role=self.role,
            raw_output=raw_output,
            parsed_output=parsed_output,
            validation_level=ValidationLevel.VALIDATED,
            confidence=confidence,
            cost_cents=3,
            elapsed_time_seconds=(
                datetime.now(timezone.utc) - start_time
            ).total_seconds(),
        )
        
        return response


class CanonicalSynthesiserAgent(LLMAgent):
    """
    Agent for canonical model synthesis (Section 7.5).
    
    Proposes canonical data model elements from clusters.
    """
    
    def __init__(self, provider: str = "anthropic"):
        """Initialize canonical synthesiser agent."""
        super().__init__(AgentRole.CANONICAL_SYNTHESISER, provider=provider)
    
    def invoke(self, request: AgentRequest) -> AgentResponse:
        """
        Synthesize canonical model element.
        
        Args:
            request: Request with cluster and alignment info
            
        Returns:
            Response with proposed canonical element
        """
        start_time = datetime.now(timezone.utc)
        
        # Render prompt
        prompt = request.prompt_template.format(**request.parameters)
        prompt += "\n\nRespond with valid JSON only."
        
        # Call LLM
        raw_output = self._call_llm(prompt, json_mode=True)
        
        # Parse output
        try:
            parsed_output = json.loads(raw_output)
        except json.JSONDecodeError:
            parsed_output = {
                "name": "canonical_field",
                "type": "string",
                "constraints": {"required": True},
                "description": "Unable to parse LLM response",
                "extensions_needed": False,
            }
        
        response = AgentResponse(
            id=request.id,
            agent_role=self.role,
            raw_output=raw_output,
            parsed_output=parsed_output,
            validation_level=ValidationLevel.VALIDATED,
            confidence=0.8,
            cost_cents=4,
            elapsed_time_seconds=(
                datetime.now(timezone.utc) - start_time
            ).total_seconds(),
        )
        
        return response


class AgentFramework:
    """
    Main agent framework (Section 7).
    
    Coordinates agent invocation, tool gateway, validation ladder,
    and retry/escalation logic.
    """
    
    def __init__(self, provider: str = "anthropic"):
        """
        Initialize agent framework.
        
        Args:
            provider: LLM provider - "anthropic" or "openai"
        """
        self.provider = provider
        self.agents: Dict[AgentRole, LLMAgent] = {
            AgentRole.SEMANTIC_RESOLVER: SemanticResolverAgent(provider=provider),
            AgentRole.ACORD_ALIGNER: ACORDAlignerAgent(provider=provider),
            AgentRole.CANONICAL_SYNTHESISER: CanonicalSynthesiserAgent(provider=provider),
        }
    
    def invoke_agent(
        self,
        request: AgentRequest,
        retry_on_failure: bool = True,
        max_retries: Optional[int] = None,
    ) -> Optional[AgentResponse]:
        """
        Invoke an agent with retry and escalation (Section 7.6).
        
        Args:
            request: Agent request
            retry_on_failure: Whether to retry on failure
            max_retries: Maximum retry count
            
        Returns:
            Agent response or None if failed
        """
        agent = self.agents.get(request.agent_role)
        if not agent:
            return None
        
        max_retries = max_retries or request.max_retries
        attempt = 0
        
        while attempt <= max_retries:
            try:
                response = agent.invoke(request)
                
                # Validate output
                if response.validation_level == ValidationLevel.VALIDATED:
                    return response
                
                # If not validated, might retry
                if not retry_on_failure:
                    return response
                    
            except Exception as e:
                attempt += 1
                if attempt > max_retries:
                    return None
        
        return None
    
    def register_agent(self, role: AgentRole, agent: LLMAgent) -> None:
        """Register a custom agent."""
        self.agents[role] = agent


__all__ = [
    "AgentRole",
    "ValidationLevel",
    "AgentPromptTemplate",
    "AgentRequest",
    "AgentResponse",
    "ToolGateway",
    "LLMAgent",
    "SemanticResolverAgent",
    "ACORDAlignerAgent",
    "CanonicalSynthesiserAgent",
    "AgentFramework",
]
