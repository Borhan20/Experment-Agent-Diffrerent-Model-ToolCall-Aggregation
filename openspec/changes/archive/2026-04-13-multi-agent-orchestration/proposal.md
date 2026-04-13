# Proposal: Intelligent Multi-Agent Orchestration System

## Problem Statement

Complex user queries often span multiple domains (e.g., weather + news + finance). Today, a single LLM call handles these monolithically — either the LLM does everything inefficiently, or the developer hard-codes routing logic. Neither approach scales.

There is also a cost problem: high-capability LLMs (GPT-4, Claude Opus) are expensive. Using them for every step — routing, tool selection, parameter transformation, AND result aggregation — is wasteful when cheaper models can handle lower-complexity steps just as well.

The goal is a system where intelligent routing and tool selection are handled by capable models, while routine transformation and aggregation work is handled by cheaper models — automatically, based on task complexity.

## Target Users

- **Primary**: Developers and researchers building or demonstrating multi-agent AI systems.
- **Secondary**: End users interacting via the Streamlit chatbot who benefit from richer, multi-domain responses without seeing the complexity underneath.

## Success Metrics

1. A query spanning 2 domains is handled by 2 sub-agents in parallel — total latency is max(agent_A_time, agent_B_time), not sum.
2. Tool dependency chains: simple key-mapping dependencies handled with zero LLM calls; only transformations requiring reasoning invoke the cheap LLM.
3. Adding a new sub-agent with new tools requires only a config change — no modification to orchestration code.
4. The system works with at least 3 LLM providers: OpenAI (GPT), Anthropic (Claude), and Google (Gemini), configured per role (router, tool selector, aggregator).
5. A working Streamlit chatbot demo where tool execution steps are visible to the user in real time.

## Scope — IN

- Coordinator (router) agent powered by a configurable high-capability LLM
- Sub-agent framework with:
  - LLM-powered tool selection
  - Parallel execution for independent tools
  - Sequential (dependency-chain) execution for dependent tools, with programmatic key-mapping and cheap-LLM fallback for transformations
  - Result aggregation via cheap LLM
- Multi-agent parallel dispatch (coordinator fans out to N sub-agents simultaneously)
- Final cross-agent aggregation via cheap LLM
- Streamlit chatbot UI with real-time streaming and agent/tool activity indicators
- Config-driven sub-agent and tool registration (no hardcoding in core)
- At least 2–3 demo sub-agents with real or mock tools
- Multi-provider LLM support: OpenAI, Anthropic, Google Gemini

## Scope — OUT

- User authentication / login system
- Persistent conversation storage to a database
- Fine-tuning or training of models
- Production deployment infrastructure (Kubernetes, Docker Compose, etc.)
- Sub-agent communication with each other (agents are independent units; only the coordinator orchestrates)
- Financial billing tracking per LLM call (may be added later)
- Admin dashboard for managing agents

## Assumptions

1. API keys for LLM providers are supplied via environment variables — no secrets management system is in scope.
2. "Simple key mapping" between dependent tools is defined as: output field X of Tool A maps directly to input field Y of Tool B with no transformation needed beyond type coercion. Anything else triggers the cheap LLM.
3. Demo sub-agents may use mocked tool responses (e.g., static weather data) to avoid requiring real API subscriptions for the demo.
4. Conversation history is stored in memory per session; no cross-session persistence.
5. LangGraph is the required orchestration framework — alternatives are not evaluated.
6. Streamlit is the required UI framework — no React/Next.js frontend.
7. The system runs as a single Python process (not distributed microservices).

## Open Questions

| # | Question | Impact if wrong | Owner |
|---|----------|----------------|-------|
| OQ-1 | Which specific model IDs are preferred for each role? (e.g., `claude-opus-4` vs `claude-sonnet-4-6` for routing; `claude-haiku-4-5` vs `gpt-4o-mini` for aggregation) | Affects cost model and prompt design | Client |
| OQ-2 | Should demo tools use real external APIs (weather, news) or mocked responses? Real APIs require key management and can fail. | Affects demo reliability and setup complexity | Client |
| OQ-3 | What is the desired behavior when a sub-agent's tool fails mid-chain? Abort the whole response, return partial results, or retry? | Affects error handling design | Client |
| OQ-4 | Should the Streamlit UI support multi-turn conversation (the coordinator sees prior messages as context)? Or is each user input treated independently? | Affects coordinator prompt design and state management | Client |
| OQ-5 | Is there a latency SLA? (e.g., "end-to-end response within 30 seconds") | Affects timeout and retry strategy | Client |
| OQ-6 | Should the system log LLM call metadata (model used, token count, cost estimate) per turn? | Affects observability design | Client |
| OQ-7 | What are the 2–3 demo sub-agent domains? (Suggested: Weather, News, Finance/Stocks — confirm or revise.) | Affects demo tool design | Client |
