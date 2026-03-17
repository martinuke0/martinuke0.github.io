---
title: "Beyond the Chatbot: Implementing Agentic Workflows with the New Open-Action Protocol 2.0"
date: "2026-03-17T00:00:59.641"
draft: false
tags: ["Open-Action", "Agentic Workflows", "AI Orchestration", "LLM Integration", "Automation"]
---

## Introduction

The rise of large language models (LLMs) has reshaped how developers think about conversational interfaces. Early deployments focused on *chatbots*—systems that respond to user input with a single turn of generated text. While chatbots are valuable, they are only the tip of the iceberg. Modern LLM‑driven applications increasingly demand **agentic behavior**: the ability to plan, execute, and coordinate multiple actions autonomously, often across disparate services.

Enter **Open-Action Protocol 2.0** (OAP 2.0). Building on the original Open-Action specification, version 2.0 introduces a richer schema for describing *actions*, *intents*, and *state transitions*, enabling developers to construct robust, multi‑step agentic workflows without hard‑coding procedural logic. In this article we will:

1. Explain the conceptual shift from chatbots to agentic workflows.
2. Dive deep into the core components of OAP 2.0.
3. Walk through a complete, production‑ready implementation using Python.
4. Showcase advanced patterns—human‑in‑the‑loop, dynamic plugin loading, and cross‑service orchestration.
5. Offer best‑practice guidelines and a look at the future of open, interoperable AI agents.

By the end, you’ll have a practical roadmap for turning LLMs into **autonomous assistants** that can schedule meetings, manipulate databases, and adapt their behavior on the fly—all while adhering to a standardized protocol that encourages interoperability.

---

## 1. From Chatbots to Agentic Workflows

### 1.1 What Is a Chatbot?

A chatbot is essentially a **single‑turn** mapping:

```
User Input → LLM Prompt → Textual Response
```

The LLM receives a prompt, generates text, and the conversation ends. Even with context windows, the bot remains *reactive*: it does not initiate actions beyond the textual reply.

### 1.2 Defining Agentic Behavior

An *agentic* system exhibits three additional capabilities:

| Capability | Description | Example |
|------------|-------------|---------|
| **Planning** | Generates a sequence of steps to achieve a goal. | “To book a flight, first check the calendar, then query the airline API.” |
| **Execution** | Calls external services (APIs, databases, scripts) on behalf of the user. | POST `/flights/book` with passenger details. |
| **Adaptation** | Adjusts its plan based on feedback, errors, or new information. | If the chosen flight is sold out, propose alternatives. |

These capabilities require **stateful orchestration**—a loop where the LLM’s output is interpreted, actions are performed, results are fed back, and the cycle repeats.

> **Note:** Agentic systems must be designed with safety in mind. Uncontrolled execution can lead to security breaches or unintended side effects. OAP 2.0 embeds security primitives directly into the protocol.

### 1.3 Why Standardize?

Without a common language, every team builds its own ad‑hoc messaging format (JSON, XML, custom DSL). This fragmentation:

* Hinders **interoperability** between LLM providers, toolchains, and third‑party services.
* Increases **maintenance overhead** as APIs evolve.
* Limits **reusability** of action definitions across projects.

Open-Action Protocol 2.0 solves these problems by providing a **canonical schema** for describing actions, intents, and state transitions, all expressed in JSON‑LD that can be validated against a shared vocabulary.

---

## 2. Overview of Open-Action Protocol 2.0

### 2.1 Core Concepts

1. **Action** – A discrete operation (e.g., `send_email`, `query_database`). Each action includes:
   * `@type`: `"OpenAction:Action"`
   * `name`: Human‑readable identifier.
   * `inputSchema`: JSON Schema describing required parameters.
   * `outputSchema`: JSON Schema for the result.
2. **Intent** – The high‑level goal the agent wants to achieve (e.g., `schedule_meeting`). Intents are **composed** of one or more actions.
3. **State** – A mutable JSON object that persists across the workflow. It can hold partial results, error flags, or context.
4. **Context** – Metadata about the execution environment (e.g., user ID, authentication tokens, timestamps).
5. **Security** – OAP 2.0 introduces `accessControl` objects that define required scopes, rate limits, and verification steps.

### 2.2 Message Flow

```
User → LLM Prompt → LLM Output (OpenAction JSON) → Action Dispatcher → Service → Result → LLM (next turn) → …
```

The LLM’s output is expected to be **well‑formed Open‑Action JSON**. The dispatcher validates the JSON, executes the described actions, updates the state, and feeds the result back to the LLM for the next iteration.

### 2.3 Schema Highlights

A minimal action definition in OAP 2.0 looks like:

```json
{
  "@type": "OpenAction:Action",
  "name": "send_email",
  "description": "Send an email to a recipient.",
  "inputSchema": {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
      "to": { "type": "string", "format": "email" },
      "subject": { "type": "string" },
      "body": { "type": "string" }
    },
    "required": ["to", "subject", "body"]
  },
  "outputSchema": {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
      "messageId": { "type": "string" },
      "status": { "type": "string", "enum": ["sent", "failed"] }
    },
    "required": ["messageId", "status"]
  },
  "accessControl": {
    "requiredScopes": ["email:send"],
    "rateLimit": "10/min"
  }
}
```

Key additions in 2.0 include:

* **`accessControl`** – Fine‑grained permission model.
* **`fallbackAction`** – Optional alternative if the primary action fails.
* **`conditional`** – Boolean expressions allowing actions to be executed only when certain state criteria are met.

---

## 3. Setting Up the Development Environment

### 3.1 Prerequisites

| Tool | Version |
|------|---------|
| Python | >=3.10 |
| `openai` SDK | 1.2.0+ |
| `jsonschema` | 4.20.0 |
| `fastapi` | 0.110.0 |
| `uvicorn` | 0.27.0 |

### 3.2 Installing Dependencies

```bash
python -m venv .venv
source .venv/bin/activate

pip install openai jsonschema fastapi uvicorn python-dotenv
```

Create a `.env` file with your OpenAI API key and any service tokens:

```dotenv
OPENAI_API_KEY=sk-...
EMAIL_API_KEY=...
CALENDAR_API_TOKEN=...
```

### 3.3 Project Structure

```
agentic-workflow/
├─ main.py                # FastAPI entry point
├─ dispatcher.py          # Core OAP 2.0 interpreter
├─ actions/
│  ├─ send_email.py
│  ├─ query_calendar.py
│  └─ create_event.py
├─ schemas/
│  └─ openaction_v2.json  # Shared OAP 2.0 JSON‑LD schema
└─ utils/
   └─ validator.py
```

---

## 4. Building a Simple Agentic Workflow

We will implement a **meeting‑scheduler** agent that can:

1. Check the user’s calendar for free slots.
2. Send an invitation email.
3. Create a calendar event.

All three steps are described using OAP 2.0 actions, and the LLM will orchestrate them.

### 4.1 Defining the Actions

#### 4.1.1 `query_calendar`

```python
# actions/query_calendar.py
import requests
from utils.validator import validate_schema

def query_calendar(input_data: dict, context: dict) -> dict:
    """
    Calls a mock calendar service to fetch free slots.
    """
    # Validate input against the action's inputSchema (omitted for brevity)
    token = context["tokens"]["calendar"]
    response = requests.get(
        "https://api.mockcalendar.com/v1/free-slots",
        headers={"Authorization": f"Bearer {token}"},
        params={"duration": input_data["duration_minutes"]},
    )
    response.raise_for_status()
    slots = response.json()["slots"]
    return {"availableSlots": slots}
```

#### 4.1.2 `send_email`

```python
# actions/send_email.py
import requests

def send_email(input_data: dict, context: dict) -> dict:
    token = context["tokens"]["email"]
    payload = {
        "to": input_data["to"],
        "subject": input_data["subject"],
        "body": input_data["body"]
    }
    resp = requests.post(
        "https://api.mockemail.com/v1/send",
        json=payload,
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    data = resp.json()
    return {"messageId": data["id"], "status": "sent"}
```

#### 4.1.3 `create_event`

```python
# actions/create_event.py
import requests

def create_event(input_data: dict, context: dict) -> dict:
    token = context["tokens"]["calendar"]
    resp = requests.post(
        "https://api.mockcalendar.com/v1/events",
        json=input_data,
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    return {"eventId": resp.json()["id"], "status": "created"}
```

### 4.2 The Dispatcher

The dispatcher validates the Open‑Action JSON, resolves the appropriate Python module, executes the action, and merges the result into the workflow state.

```python
# dispatcher.py
import json
import importlib
from jsonschema import validate, ValidationError
from utils.validator import load_schema
from fastapi import HTTPException

SCHEMA = load_schema("schemas/openaction_v2.json")

def dispatch(open_action_json: dict, state: dict, context: dict) -> dict:
    """
    Core OAP 2.0 dispatcher.
    """
    # 1️⃣ Validate against OAP 2.0 schema
    try:
        validate(instance=open_action_json, schema=SCHEMA)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid OpenAction: {exc.message}")

    # 2️⃣ Resolve the action implementation
    action_name = open_action_json["name"]
    try:
        module = importlib.import_module(f"actions.{action_name}")
        action_func = getattr(module, action_name)
    except (ImportError, AttributeError):
        raise HTTPException(status_code=404, detail=f"Action '{action_name}' not implemented")

    # 3️⃣ Merge input parameters with current state (state can provide defaults)
    input_params = {**open_action_json.get("input", {}), **state.get("lastResult", {})}
    result = action_func(input_params, context)

    # 4️⃣ Update state with the new result
    state["lastResult"] = result
    state["history"] = state.get("history", []) + [open_action_json]

    return {"state": state, "result": result}
```

### 4.3 FastAPI Endpoint

```python
# main.py
import os
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dispatcher import dispatch
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

class OAPRequest(BaseModel):
    open_action: dict
    state: dict = {}
    user_id: str

def build_context(user_id: str) -> dict:
    # In a real system, fetch tokens from a vault or DB
    return {
        "user": user_id,
        "tokens": {
            "email": os.getenv("EMAIL_API_KEY"),
            "calendar": os.getenv("CALENDAR_API_TOKEN")
        }
    }

@app.post("/execute")
async def execute(request: OAPRequest):
    context = build_context(request.user_id)
    response = dispatch(request.open_action, request.state, context)
    return response
```

### 4.4 Orchestrating with the LLM

We now ask the LLM to generate an Open‑Action plan. Using the `openai.ChatCompletion` endpoint:

```python
import openai
import json

def generate_plan(goal: str, user_context: dict) -> dict:
    prompt = f"""You are an autonomous scheduling assistant. Your goal is: "{goal}".
You must respond ONLY with a JSON array of OpenAction objects (OAP 2.0) that will achieve the goal.
Each action must reference the previously defined actions (send_email, query_calendar, create_event)."""

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.2,
        max_tokens=800,
    )
    # The model returns a stringified JSON; parse it safely
    json_str = response.choices[0].message.content.strip()
    return json.loads(json_str)

# Example usage
plan = generate_plan(
    "Schedule a 30‑minute meeting with alice@example.com next week.",
    {"user_id": "12345"}
)

# The plan is a list of OpenAction dicts; we iterate through them
state = {}
for action in plan:
    resp = dispatch(action, state, build_context("12345"))
    state = resp["state"]
    print(f"Executed {action['name']}: {resp['result']}")
```

The LLM might output something like:

```json
[
  {
    "@type": "OpenAction:Action",
    "name": "query_calendar",
    "input": { "duration_minutes": 30 }
  },
  {
    "@type": "OpenAction:Action",
    "name": "send_email",
    "input": {
      "to": "alice@example.com",
      "subject": "Proposed meeting times",
      "body": "Hi Alice, here are my available slots: {{state.lastResult.availableSlots}}"
    },
    "conditional": "state.lastResult.availableSlots.length > 0"
  },
  {
    "@type": "OpenAction:Action",
    "name": "create_event",
    "input": {
      "title": "Meeting with Alice",
      "start": "{{state.lastResult.availableSlots[0].start}}",
      "end": "{{state.lastResult.availableSlots[0].end}}",
      "attendees": ["alice@example.com"]
    }
  }
]
```

The dispatcher resolves each step, updates the shared `state`, and the LLM can be prompted for the next iteration if any `conditional` fails (e.g., no free slots).

---

## 5. Advanced Use Cases

### 5.1 Multi‑Step Orchestration with Branching

Complex workflows often need **branching logic** (if‑else). OAP 2.0 supports a `conditional` field that evaluates a Jinja‑style expression against the current state.

```json
{
  "@type": "OpenAction:Action",
  "name": "fallback_suggest_alternative",
  "input": { "suggestion": "next week Monday" },
  "conditional": "state.lastResult.availableSlots.length == 0"
}
```

The dispatcher checks the condition before executing. If the condition is false, the action is skipped, enabling **dynamic plan adaptation** without re‑prompting the LLM.

### 5.2 Human‑in‑the‑Loop (HITL)

Some decisions require confirmation. OAP 2.0 introduces a `humanApproval` wrapper:

```json
{
  "@type": "OpenAction:HumanApproval",
  "prompt": "User wants to send the following email. Approve?",
  "action": {
    "@type": "OpenAction:Action",
    "name": "send_email",
    "input": { ... }
  }
}
```

When the dispatcher encounters a `HumanApproval` node, it pauses execution and returns a payload to the front‑end, where a UI can present the prompt to the user. Once the user approves (or rejects), the front‑end calls `/execute` again with a flag indicating the decision.

### 5.3 Dynamic Plugin Loading

Enterprises may maintain a catalog of proprietary actions (e.g., internal ERP calls). OAP 2.0 supports a `pluginReference` field that points to a **module name** resolved at runtime.

```json
{
  "@type": "OpenAction:Action",
  "pluginReference": "company.plugins.erp.create_invoice",
  "input": { "orderId": "1234", "amount": 2500 }
}
```

The dispatcher loads the module via `importlib` only when needed, keeping the core runtime lightweight.

### 5.4 Cross‑Service Orchestration

Suppose you need to:

1. Pull a lead from a CRM.
2. Generate a personalized PDF via a third‑party service.
3. Email the PDF to the lead.

You can chain actions across three distinct services, each with its own `accessControl`. OAP 2.0’s schema allows you to declare **aggregate scopes**:

```json
"accessControl": {
  "requiredScopes": ["crm:read", "pdf:generate", "email:send"]
}
```

A gateway (e.g., API gateway or service mesh) can enforce that the executing token possesses all required scopes before any action runs, providing a **single point of audit**.

---

## 6. Integration with Existing Platforms

### 6.1 LLM Providers

Open‑Action is **LLM‑agnostic**. The only requirement is that the model can emit valid JSON. Prompt engineering patterns that work with OpenAI, Anthropic, or Cohere are similar:

* Use **system messages** to define the contract.
* Set **temperature** low (≤0.3) for deterministic JSON.
* Enforce a **max token** limit to avoid truncation.

### 6.2 CI/CD Pipelines

You can embed OAP 2.0 workflows in CI pipelines to automate:

* Release notes generation.
* Dependency vulnerability scanning.
* Automated rollback decisions.

Example: a workflow that queries a security scanner, decides whether to block a merge, and posts the outcome to Slack—all described as Open‑Action steps.

### 6.3 Monitoring & Observability

Because every action passes through the dispatcher, you can instrument a **middleware** that logs:

* Action name.
* Execution latency.
* Success/failure status.
* Correlation IDs for tracing across services.

Export these logs to **OpenTelemetry**, **Prometheus**, or a SaaS observability platform to get a real‑time view of agentic activity.

---

## 7. Best Practices and Common Pitfalls

| Area | Recommendation | Why It Matters |
|------|----------------|----------------|
| **Schema Validation** | Validate every incoming Open‑Action against the official JSON‑LD schema using `jsonschema`. | Prevents malformed actions that could crash the dispatcher or cause security leaks. |
| **Least‑Privilege Tokens** | Issue per‑action scopes (`email:send`, `calendar:read`) rather than broad tokens. | Reduces impact of token compromise. |
| **Idempotency** | Design actions to be idempotent (e.g., include a client‑generated `requestId`). | Enables safe retries when network errors occur. |
| **State Size Management** | Keep the workflow state under 1 MiB; prune old entries after they’re no longer needed. | Avoids hitting request size limits and improves performance. |
| **Human Approval** | For any action that incurs cost or modifies critical data, wrap it in `HumanApproval`. | Provides a safety net against unintended side effects. |
| **Versioning** | Include a `protocolVersion` field in every payload (`"2.0"`). | Allows graceful upgrades when the spec evolves. |
| **Testing** | Use **contract tests** that feed sample Open‑Action JSON into the dispatcher and assert expected state transitions. | Guarantees that changes to the dispatcher don’t break existing workflows. |

### Common Pitfalls

1. **Over‑reliance on LLM for validation** – LLMs may hallucinate missing fields. Always perform server‑side validation.
2. **Hard‑coding secrets in action modules** – Use environment variables or secret managers.
3. **Ignoring rate limits** – `accessControl` can specify limits; enforce them centrally to avoid service bans.
4. **Unstructured error handling** – Return a consistent error schema (`errorCode`, `message`, `retryable`) so the LLM can decide to retry or fallback.

---

## 8. Future Directions

Open‑Action Protocol 2.0 lays a solid foundation, but the ecosystem is still maturing. Anticipated advancements include:

* **Declarative Workflow DSL** – A higher‑level language that compiles to OAP JSON, enabling visual workflow designers.
* **Standardized Semantics for Intent** – A shared taxonomy (e.g., `finance:invoice`, `hr:onboarding`) that LLMs can reference for better intent disambiguation.
* **Federated Execution** – Distributed agents that negotiate responsibilities across organizational boundaries while preserving data sovereignty.
* **Self‑Optimizing Agents** – Feedback loops where agents analyze execution metrics and automatically rewrite parts of their plan for efficiency.

Developers who adopt OAP 2.0 early will help shape these extensions, ensuring that the protocol remains open, extensible, and aligned with real‑world needs.

---

## Conclusion

The transition from simple chatbots to **agentic workflows** unlocks a whole new class of intelligent applications—systems that can plan, act, and adapt autonomously. Open‑Action Protocol 2.0 provides the **standardized glue** that binds LLM reasoning with concrete, secure actions, turning abstract intent into reliable execution.

In this article we:

* Clarified why agentic behavior matters beyond conversational UI.
* Explored the core schema of OAP 2.0, emphasizing security and conditional logic.
* Built a complete end‑to‑end meeting‑scheduler, showcasing how the dispatcher, actions, and LLM cooperate.
* Demonstrated advanced patterns such as branching, human‑in‑the‑loop, and dynamic plugin loading.
* Offered pragmatic best‑practice guidance to keep implementations safe, maintainable, and observable.

By integrating OAP 2.0 into your stack, you gain **interoperability**, **auditability**, and a future‑proof pathway to richer AI‑driven automation. The next wave of applications will no longer be limited to answering questions—they will **execute** them, all while speaking a common language that the community can extend together.

---

## Resources

* [Open-Action Protocol Specification (v2.0)](https://github.com/open-action/specification) – Official GitHub repository containing the full JSON‑LD schema and version history.  
* [OpenAI Chat Completion API Documentation](https://platform.openai.com/docs/guides/chat) – Guidance on prompting models to emit structured JSON.  
* [FastAPI – Building APIs with Python](https://fastapi.tiangolo.com/) – High‑performance web framework used in the example implementation.  
* [JSON Schema Draft‑07 Specification](https://json-schema.org/specification-links.html#draft-7) – Reference for defining and validating action input/output schemas.  
* [OpenTelemetry – Observability for Distributed Systems](https://opentelemetry.io/) – Tools for tracing and monitoring agentic workflows.  