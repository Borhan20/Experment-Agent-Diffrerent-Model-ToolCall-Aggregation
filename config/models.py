"""Pydantic models for configuration validation."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class LLMRoleConfig(BaseModel):
    provider: Literal["openai", "anthropic", "gemini"]
    model: str
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)


class ToolMappingConfig(BaseModel):
    source_field: str
    target_field: str


class ToolDependencyConfig(BaseModel):
    tool_id: str
    mappings: List[ToolMappingConfig]


class ToolConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    handler: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    depends_on: List[ToolDependencyConfig] = []


class AgentConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    tools: List[ToolConfig] = Field(min_length=1)


class LLMRolesConfig(BaseModel):
    router: LLMRoleConfig
    tool_selector: LLMRoleConfig
    transformer: LLMRoleConfig
    aggregator: LLMRoleConfig


class AppConfig(BaseModel):
    llm_roles: LLMRolesConfig
    agents: List[AgentConfig] = Field(min_length=1)
