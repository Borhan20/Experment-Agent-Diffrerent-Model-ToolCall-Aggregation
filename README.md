# Lean Multi-Agent Orchestration System

A cost-optimized multi-agent AI orchestrator built with LangGraph and Streamlit.
Routes user queries to specialized sub-agents, executes domain-specific tools in
parallel or sequential order, and aggregates results using a dual-LLM strategy
(high-capability for routing/selection, cheap for transformation/aggregation).

## Features

- **Intelligent routing** — coordinator LLM selects which agents handle each query
- **Parallel agent dispatch** — multiple sub-agents run concurrently via LangGraph Send API
- **Parallel & sequential tool execution** — DAG-based tool execution within each agent
- **Cost-optimized LLM usage** — cheap LLM for aggregation; zero LLM for simple parameter mapping
- **Config-driven extensibility** — add new agents/tools via YAML, no code changes required
- **Multi-provider support** — OpenAI, Anthropic, and Google Gemini
- **Real-time Streamlit UI** — streaming responses, agent activity indicators, tool trace

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your API key(s)
```

At minimum, one provider key is needed. Edit `config/settings.yaml` to point all
LLM roles at that provider.

### 3. Run the app

```bash
streamlit run ui/app.py
```

### 4. Try the demo queries

- **Single agent**: "What's the weather like in Dhaka?"
- **Multi-agent parallel**: "What's the weather in London and the latest AI news?"
- **Calculator**: "What is 1500 divided by 12, then convert that from Celsius to Fahrenheit?"
- **Three agents**: "Weather in Tokyo, latest tech news, and calculate 2 to the power of 10"

## Configuration

### `config/settings.yaml` — LLM role assignments

```yaml
llm_roles:
  router:         { provider: anthropic, model: claude-opus-4-6, temperature: 0.0 }
  tool_selector:  { provider: anthropic, model: claude-opus-4-6, temperature: 0.0 }
  transformer:    { provider: anthropic, model: claude-haiku-4-5-20251001, temperature: 0.0 }
  aggregator:     { provider: anthropic, model: claude-haiku-4-5-20251001, temperature: 0.3 }
```

Supported providers: `anthropic`, `openai`, `gemini`

### `config/agents.yaml` — Agent and tool definitions

Each agent has an `id`, `name`, `description`, and a list of `tools`.
Each tool has:
- `id`, `name`, `description` — used for LLM selection
- `handler` — dotted Python module path to an async function
- `input_schema` / `output_schema` — JSON Schema
- `depends_on` — optional dependency on another tool's output

## Adding a New Agent

1. Create your tool handlers as async Python functions:

```python
# mypackage/tools/finance.py
async def get_stock_price(ticker: str) -> dict:
    return {"ticker": ticker, "price": 150.0}
```

2. Add an entry to `config/agents.yaml`:

```yaml
- id: finance_agent
  name: Finance Agent
  description: Handles stock prices and financial queries
  tools:
    - id: get_stock_price
      name: Get Stock Price
      description: Returns the current price for a stock ticker
      handler: mypackage.tools.finance.get_stock_price
      input_schema:
        type: object
        properties:
          ticker: {type: string, description: "Stock ticker symbol"}
        required: [ticker]
      output_schema:
        type: object
        properties:
          ticker: {type: string}
          price: {type: number}
```

3. Restart the app — no other code changes needed.

## Running Tests

```bash
# Unit tests (no API keys needed)
pytest tests/unit/ -v

# Integration tests (no API keys needed — uses mock LLMs)
pytest tests/integration/ -v

# All tests
pytest tests/ -v
```

## Project Structure

```
├── config/          # YAML config + Pydantic models + loader
├── core/            # LangGraph graph, coordinator, sub-agent, aggregator
├── llm/             # Provider adapters (OpenAI, Anthropic, Gemini) + factory
├── tools/           # Tool registry + execution engine
├── demo/tools/      # Demo tool handlers (weather, news, calculator)
├── ui/              # Streamlit app + components
└── tests/           # Unit and integration tests
```
