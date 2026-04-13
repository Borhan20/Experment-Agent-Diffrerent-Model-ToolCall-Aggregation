# Spec: Demo Sub-Agents

**Source Requirements**: FR-7.1, IR-5
**Design Section**: design.md §9 (agents.yaml excerpt)

---

## Purpose

Three demo sub-agents demonstrate the full system: routing, parallel dispatch, sequential tool dependency chains, and cross-agent aggregation. All tools have mock implementations so no external API keys are required for the demo.

---

## Demo Agent 1: Weather Agent

**ID**: `weather_agent`
**Description**: Handles weather-related queries. Retrieves current conditions and multi-day forecasts.

### Tool 1: `get_current_weather`

**Handler**: `demo.tools.weather.get_current_weather`

```
Input:
  location: str   # city name, e.g. "Dhaka"

Output:
  location: str
  temperature_c: float
  condition: str           # e.g., "Partly Cloudy"
  humidity_pct: int
  wind_kph: float

Mock behavior:
  Returns deterministic fake data based on location string hash.
  e.g., "Dhaka" → {temperature_c: 32.5, condition: "Hot and Humid", humidity_pct: 85, wind_kph: 12.0}
  Always succeeds. 0.5s simulated delay (asyncio.sleep).
```

### Tool 2: `get_weather_forecast`

**Handler**: `demo.tools.weather.get_weather_forecast`

**Depends on**: `get_current_weather` via mapping `location → location`

```
Input:
  location: str   # provided via dependency from get_current_weather
  days: int       # default 3, from tool_selector plan

Output:
  location: str
  forecasts: List[{day: str, high_c: float, low_c: float, condition: str}]

Mock behavior:
  Returns 3-day forecast generated from location hash + offset.
  0.3s simulated delay.
```

**Dependency type**: Simple field rename (location → location, same type). Zero LLM calls.

---

## Demo Agent 2: News Agent

**ID**: `news_agent`
**Description**: Handles news and current events queries. Searches recent articles and summarizes them.

### Tool 1: `search_news`

**Handler**: `demo.tools.news.search_news`

```
Input:
  query: str        # search terms
  max_results: int  # default 5

Output:
  query: str
  articles: List[{
    title: str,
    source: str,
    published_at: str,
    snippet: str,
    url: str
  }]

Mock behavior:
  Returns 5 fake articles with realistic-looking titles and snippets
  based on the query string. Titles include the query terms.
  0.8s simulated delay (simulating API call).
```

### Tool 2: `summarize_articles`

**Handler**: `demo.tools.news.summarize_articles`

**Depends on**: `search_news` via mapping `articles → articles`

```
Input:
  articles: List[dict]   # from search_news output

Output:
  summary: str           # bullet-point summary of key findings
  article_count: int

Mock behavior:
  Returns a constructed summary string mentioning article titles from input.
  This demonstrates sequential dependency: summarize needs search results.
  0.2s simulated delay.
```

**Dependency type**: Direct array pass-through (articles → articles, same type). Zero LLM calls.

---

## Demo Agent 3: Calculator Agent

**ID**: `calculator_agent`
**Description**: Handles mathematical computations, conversions, and numerical queries.

### Tool 1: `calculate`

**Handler**: `demo.tools.calculator.calculate`

```
Input:
  expression: str   # mathematical expression, e.g., "25 * 4 + 10"

Output:
  expression: str
  result: float
  formatted: str    # e.g., "110.0"

Implementation:
  Use Python's ast.literal_eval on a safe expression parser.
  Supported operations: +, -, *, /, **, (), basic math.
  Raises ValueError for unsafe expressions (exec, import, etc.).
  No simulated delay (local computation).
```

### Tool 2: `convert_units`

**Handler**: `demo.tools.calculator.convert_units`

```
Input:
  value: float
  from_unit: str    # e.g., "celsius", "km", "kg"
  to_unit: str      # e.g., "fahrenheit", "miles", "lbs"

Output:
  original_value: float
  original_unit: str
  converted_value: float
  converted_unit: str

Implementation:
  Hardcoded conversion factors for common unit pairs.
  No external API. No simulated delay.
```

---

## Demonstration Scenarios

These scenarios must work end-to-end to satisfy FR-7.1:

### Scenario A: Single Agent (Weather)
**Query**: "What's the weather like in Dhaka?"
**Expected flow**:
1. Coordinator → weather_agent
2. Tool selector → [get_current_weather, get_forecast] with forecast depending on current
3. get_current_weather runs (parallel batch of 1)
4. Dependency resolver: location → location (programmatic, no LLM)
5. get_forecast runs with resolved location
6. Intra-aggregator → response
7. No cross-aggregation LLM call (single agent)

### Scenario B: Multi-Agent Parallel (Weather + News)
**Query**: "What's the weather in Dhaka and the latest news about Bangladesh cricket?"
**Expected flow**:
1. Coordinator → weather_agent + news_agent (parallel)
2. Both agents run concurrently
3. Weather: get_current_weather → get_forecast (sequential within agent)
4. News: search_news → summarize_articles (sequential within agent)
5. Both complete independently
6. Cross-aggregator LLM call → unified response

### Scenario C: Calculator
**Query**: "What is 1500 / 12 and convert that to Fahrenheit if it were Celsius?"
**Expected flow**:
1. Coordinator → calculator_agent
2. Tool selector → [calculate, convert_units] with convert depending on calculate result
3. calculate runs: "1500 / 12" → 125.0
4. Dependency resolver: result → value (numeric pass-through, no LLM)
5. convert_units: 125.0 celsius → fahrenheit
6. Intra-aggregator → response

### Scenario D: Three Agents
**Query**: "Weather in Dhaka, latest tech news, and calculate compound interest: 10000 at 5% for 3 years"
**Expected flow**:
1. Coordinator → all 3 agents in parallel
2. All 3 execute concurrently
3. Cross-aggregator weaves together all 3 responses

---

## Mock Tool Implementation Notes

- All tool handlers are `async def` functions even if they don't do I/O
- Simulated delays use `await asyncio.sleep(seconds)` to demonstrate true parallelism
- Tools that "fail" can be triggered by special input (e.g., location="FAIL") for testing NFR-5
- No real external API calls in mock mode — the system runs fully offline

---

## File Locations

```
demo/
└── tools/
    ├── weather.py      # get_current_weather, get_weather_forecast
    ├── news.py         # search_news, summarize_articles
    └── calculator.py   # calculate, convert_units
```

All handlers importable as:
- `demo.tools.weather.get_current_weather`
- `demo.tools.weather.get_weather_forecast`
- `demo.tools.news.search_news`
- `demo.tools.news.summarize_articles`
- `demo.tools.calculator.calculate`
- `demo.tools.calculator.convert_units`
