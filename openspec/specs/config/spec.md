# Spec: Configuration-Driven Extensibility

**Source Requirements**: FR-6.1, FR-6.2, FR-6.3, NFR-2, NFR-3, NFR-7, IR-1, IR-2, IR-3
**Design Section**: design.md §6, §9, §11

---

## Purpose

All sub-agents, tools, and LLM role assignments are defined in YAML config files. Adding a new agent requires only a config entry and a tool handler module — zero changes to orchestration code.

---

## Config Files

### `config/settings.yaml` — LLM Role Assignments

Full schema:
```yaml
llm_roles:
  router:
    provider: string       # "openai" | "anthropic" | "gemini"
    model: string          # exact model ID
    temperature: float     # 0.0 – 1.0, default 0.0
  tool_selector:
    provider: string
    model: string
    temperature: float
  transformer:
    provider: string
    model: string
    temperature: float
  aggregator:
    provider: string
    model: string
    temperature: float
```

**Defaults** (used when settings.yaml is absent):
```yaml
llm_roles:
  router:     {provider: anthropic, model: claude-opus-4-6, temperature: 0.0}
  tool_selector: {provider: anthropic, model: claude-opus-4-6, temperature: 0.0}
  transformer: {provider: anthropic, model: claude-haiku-4-5-20251001, temperature: 0.0}
  aggregator:  {provider: anthropic, model: claude-haiku-4-5-20251001, temperature: 0.3}
```

### `config/agents.yaml` — Agent and Tool Definitions

Full schema per agent:
```yaml
agents:
  - id: string             # unique, used as routing key; snake_case
    name: string           # human-readable display name
    description: string    # shown to coordinator LLM for routing decisions
    tools:
      - id: string                     # unique within agent; snake_case
        name: string
        description: string            # shown to tool_selector LLM
        handler: string                # dotted module path to async function
        input_schema:                  # JSON Schema (draft-07 subset)
          type: object
          properties:
            field_name:
              type: string|number|integer|boolean|array|object
              description: string
          required: [field_name, ...]
        output_schema:                 # JSON Schema for output dict
          type: object
          properties: ...
        depends_on:                    # optional
          - tool_id: string            # must be another tool id within same agent
            mappings:
              - source_field: string   # field name in upstream tool's output
                target_field: string   # field name in this tool's input
```

**Constraints**:
- `id` fields: lowercase alphanumeric + underscore only; no spaces
- `handler`: must be a valid importable dotted path; validated at startup
- `depends_on.tool_id`: must reference a tool defined earlier in the same agent's tools list
- Circular dependencies: detected at startup, fail fast

---

## Pydantic Models (`config/models.py`)

```python
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
    id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    name: str
    description: str
    handler: str    # validated separately via importlib
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    depends_on: List[ToolDependencyConfig] = []

class AgentConfig(BaseModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
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
```

---

## Config Loader (`config/loader.py`)

### `load_config() -> AppConfig`

```
1. Load settings.yaml with yaml.safe_load
   - If file absent: use defaults
   - If file present but malformed: raise ConfigError with line number

2. Load agents.yaml with yaml.safe_load
   - If file absent: raise ConfigError("agents.yaml required")
   - If file present but malformed: raise ConfigError

3. Merge into single dict, parse with AppConfig.model_validate()
   - Pydantic raises ValidationError with field path + message on any violation

4. Validate handler importability:
   For each tool.handler:
     module_path, func_name = handler.rsplit(".", 1)
     importlib.import_module(module_path)  → ConfigError if ImportError
     getattr(module, func_name)            → ConfigError if AttributeError

5. Validate dependency references:
   For each agent, for each tool with depends_on:
     For each dep.tool_id: must exist in agent.tools ids  → ConfigError if not
   Build dependency graph per agent; detect cycles (DFS)   → ConfigError if cycle

6. Validate agent id uniqueness across all agents          → ConfigError if duplicate

7. Validate tool id uniqueness within each agent           → ConfigError if duplicate

8. Return validated AppConfig
```

### Error Message Format

All `ConfigError` messages follow:
```
ConfigError: [agents.yaml] agent 'weather_agent' → tool 'get_forecast' → depends_on 'nonexistent_tool': referenced tool_id not found in agent's tool list.
```

---

## Environment Variable Requirements

### Required per provider used

| Provider | Required Env Var |
|----------|-----------------|
| openai | `OPENAI_API_KEY` |
| anthropic | `ANTHROPIC_API_KEY` |
| gemini | `GOOGLE_API_KEY` |

### Startup check in `LLMFactory.get_adapter()`

```python
env_var_map = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}
required_var = env_var_map[provider]
if not os.environ.get(required_var):
    raise ConfigError(f"Missing environment variable: {required_var} (required for provider '{provider}')")
```

---

## Extensibility Contract (NFR-3)

Adding a new sub-agent requires ONLY:
1. Create `your_module/tools/my_agent.py` with async handler functions
2. Add entry to `config/agents.yaml`:
   ```yaml
   - id: my_agent
     name: My Agent
     description: "Handles my domain queries"
     tools:
       - id: my_tool
         handler: your_module.tools.my_agent.my_tool
         ...
   ```
3. Restart the application

**No changes required to**:
- `core/graph.py`
- `core/coordinator.py`
- `core/sub_agent.py`
- `ui/app.py`
- Any other orchestration file

---

## Boundary Conditions

| Condition | Behavior |
|-----------|----------|
| Two agents with same id | ConfigError at startup: "duplicate agent id: weather_agent" |
| Tool handler module not installed | ConfigError at startup with import path |
| settings.yaml missing | Use hardcoded defaults; no error |
| agents.yaml missing | ConfigError at startup (required) |
| Provider not in supported list | Pydantic ValidationError: "Input should be 'openai', 'anthropic', or 'gemini'" |
| Temperature outside 0–1 | Pydantic ValidationError: "Input should be >= 0 and <= 1" |
