# Codebase Walkthrough: Intelligent Multi-Agent Orchestration

Welcome! This guide is designed to help you understand how this multi-agent system works from the ground up. We will break down the system piece by piece, explaining **what** each part does and **why** we need it.

---

## 1. The Big Picture: What are we building?

Imagine you are running a company. You have:
- A **Coordinator** (the boss) who takes client requests and figures out who should do the work.
- Several **Specialized Agents** (workers) like a Weather Expert, a News Analyst, and a Math Whiz.
- **Tools** (calculators, search engines, APIs) that the workers use to do their jobs.
- An **Aggregator** (the editor) who takes everyone's reports and writes a final, coherent email back to the client.

We are building this exact structure using code. To manage the workflow (who talks to whom and when), we use a library called **LangGraph**. LangGraph treats our system like a flowchart (a "Graph") where data flows from one node (step) to the next.

### The Graph Flow
Here is how our graph looks:

```text
[START]
   │
   ▼
[Coordinator Node]  ───(Reads query, decides which agents are needed)
   │
   ├─► [Weather Agent Node]    (If weather is asked)
   ├─► [News Agent Node]       (If news is asked)
   └─► [Calculator Agent Node] (If math is asked)
   │
   ▼ (Wait for all assigned agents to finish)
   │
[Cross-Aggregator Node] ───(Combines all answers into one final response)
   │
   ▼
 [END]
```

---

## 2. Step-by-Step Code Walkthrough

Let's look at the actual code folders and files to see how this is built.

### A. Configuration (`config/`)
**Why we need it:** We want to be able to add new agents, change LLM models (like switching from OpenAI to Anthropic), or add new tools *without* rewriting our core Python code.

*   **`models.py`**: Defines the "shape" of our settings using Pydantic. It ensures that if we say an agent needs an "id" and a "name", the system crashes early if the config file is missing them.
*   **`loader.py`**: Reads `settings.yaml` (system settings) and `agents.yaml` (definitions of our agents and their tools) and turns them into Python objects we can use everywhere.
*   **`settings.yaml` / `agents.yaml`**: The actual human-readable text files where we configure our system.

### B. Talking to AI Models (`llm/`)
**Why we need it:** Different AI providers (OpenAI, Anthropic, Google Gemini) have different ways of formatting their code to ask questions and use tools. We want our main system to not care which provider it is using.

*   **`base.py`**: Defines a "Contract" (Protocol). It says "Any LLM we use MUST have a `complete()` method and a `stream()` method."
*   **`openai_adapter.py`, `anthropic_adapter.py`, `gemini_adapter.py`**: Translators. They take our standard format and translate it into the specific format that OpenAI, Anthropic, or Gemini expects.
*   **`factory.py`**: A helper that looks at our config and hands us the correct adapter (e.g., "Oh, the config says use Gemini for the Router? Here is the `gemini_adapter`").

### C. The Core Orchestration (`core/`)
**Why we need it:** This is the brain of the application. It defines the Graph, the Nodes, and the State.

*   **`state.py`**: **The Memory.** In LangGraph, as data moves from node to node, it is carried in a "State" dictionary. This file defines what lives in that memory (e.g., `conversation_history`, `current_query`, `routing_plan`, and `agent_results`).
*   **`coordinator.py`**: **The Boss.** This node looks at the `current_query`. It uses a smart LLM to figure out which agents are needed. It creates a `routing_plan`. If you ask "What can you do?", it realizes no tools are needed and writes a `direct_response` talking to you.
*   **`sub_agent.py`**: **The Worker.** This file has a factory `create_agent_node()` that creates a dedicated node for each agent. When an agent node runs:
    1. It looks at the query it was assigned.
    2. It asks its own LLM: "Which of my tools should I use?" (Tool Selection).
    3. It executes those tools.
    4. It asks a cheap LLM: "Summarize these tool results into a nice sentence." (Intra-Agent Aggregation).
    5. It saves its final answer to `agent_results` in the State.
*   **`dependency_resolver.py`**: **The Data Passer.** If an agent decides to run Tool A, and Tool B needs the output of Tool A, this script figures out how to pass that data safely.
*   **`aggregator.py`**: **The Editor.** This node runs last. It looks at the `agent_results` dictionary (which might have answers from the Weather agent AND the News agent), and uses an LLM to weave them into one smooth, final paragraph for the user.
*   **`graph.py`**: **The Map Maker.** This file uses LangGraph to actually tie all the above nodes together using `StateGraph`. It sets up the conditional edges (the branching paths) so the flow goes from Coordinator -> Specific Agents -> Aggregator.

### D. Tools (`tools/` & `demo/tools/`)
**Why we need it:** LLMs can't browse the live internet or do complex math reliably. Tools are standard Python functions that do actual work.

*   **`tools/registry.py`**: A central phonebook. When the app starts, it reads `agents.yaml`, finds all the tool functions, and registers them here so agents can look them up.
*   **`tools/executor.py`**: The engine that actually runs the Python tool functions. It is smart enough to run independent tools in parallel at the exact same time (using `asyncio.gather`) to save time.
*   **`demo/tools/`**: The actual Python files containing functions like `get_current_weather` or `calculate`. Right now, they return mock data for safety, but they could easily make real web requests.

### E. The User Interface (`ui/`)
**Why we need it:** We need a visual way for users to chat with the system, see the history, and watch the system think.

*   **`app.py`**: The main Streamlit file. It draws the chat box, the sidebar, and handles the submit button.
*   **`runner.py`**: Because LangGraph runs asynchronously (in the background) but Streamlit runs synchronously (blocking), this file bridges the gap. It runs the Graph in a separate background thread and passes updates back to the UI via a Queue.
*   **`components/`**: Smaller files to draw specific parts of the UI, like the Chat bubbles (`chat.py`), the spinning loading icons (`activity.py`), and the technical debugging view showing exactly what tools ran (`trace.py`).

---

## 3. Example: How a Request Flows

Let's trace what happens when you type: **"What is the weather in Tokyo and what is 5 * 10?"**

1. **UI (`ui/app.py`)**: You hit enter. The UI adds your text to the conversation history and passes it to `runner.py`.
2. **Graph Start (`core/graph.py`)**: The LangGraph is triggered with your query.
3. **Node 1: Coordinator (`core/coordinator.py`)**:
    * The Coordinator LLM looks at the text.
    * It says: "Ah, I need the `weather_agent` for Tokyo, and the `calculator_agent` for the math."
    * It updates the State with a `routing_plan`.
4. **Conditional Edge**: The graph reads the plan and activates the `weather_agent` node and `calculator_agent` node *at the same time*.
5. **Node 2 & 3: Sub-Agents (`core/sub_agent.py`)**:
    * **Weather Agent**: Asks its LLM which tool to use. LLM says `get_current_weather(location="Tokyo")`. The `executor.py` runs the tool. The agent's LLM summarizes the output: "It is sunny in Tokyo."
    * **Calculator Agent**: Asks its LLM. LLM says `calculate(expression="5 * 10")`. The tool runs and returns `50`. The agent's LLM summarizes: "5 times 10 is 50."
    * Both agents save their summaries into `state["agent_results"]`.
6. **Node 4: Cross-Aggregator (`core/aggregator.py`)**:
    * This node waits until both agents are done.
    * It sees the Weather answer and the Calculator answer.
    * It asks its LLM to combine them.
    * It outputs: *"Currently in Tokyo, it is sunny. Also, the result of 5 multiplied by 10 is 50."*
    * It saves this to `state["final_response"]`.
7. **End**: The Graph finishes, the UI receives the `final_response`, and prints it on your screen!
