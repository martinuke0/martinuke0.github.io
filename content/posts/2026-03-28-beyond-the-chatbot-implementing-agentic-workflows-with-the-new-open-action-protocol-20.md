---
title: "Beyond the Chatbot: Implementing Agentic Workflows with the New Open-Action Protocol 2.0"
date: "2026-03-28T17:00:35.125"
draft: false
tags: ["AI agents", "Open-Action Protocol", "agentic workflows", "LLM integration", "automation"]
---

## Introduction

The last few years have witnessed a dramatic shift from static, rule‑based bots to **agentic systems**—autonomous software entities that can reason, plan, and act on behalf of users. While the term “agent” is often used loosely, a true agent exhibits three core capabilities:

1. **Goal‑oriented behavior** – it knows *what* it wants to achieve.
2. **Dynamic planning** – it can break the goal into steps, adapt when conditions change, and recover from failures.
3. **Tool use** – it can invoke external APIs, run code, or interact with other services to fulfill its plan.

The **Open-Action Protocol (OAP) 2.0**—released in early 2026—was designed explicitly to make the construction of such agents easier, more interoperable, and safer. In this article we will explore why OAP 2.0 matters, how it differs from the original version, and walk through a complete end‑to‑end implementation of an agentic workflow that goes far beyond a simple chatbot.

By the end of this guide you will be able to:

* Understand the architectural primitives introduced by OAP 2.0.  
* Design, code, and test an autonomous agent that schedules meetings, drafts follow‑up emails, and updates a CRM system.  
* Deploy the agent on a cloud platform using containers and serverless functions.  
* Apply best practices for security, observability, and error handling.

Let’s dive in.

## 1. From Chatbots to Agents – What Changed?

### 1.1 The Limitations of Traditional Chatbots

Classic chatbots are **reactive**: they receive a user message, match it against a set of intents, and return a pre‑defined response. Even the most sophisticated large‑language‑model (LLM) powered bots typically follow a single turn of “question → answer.” This model works well for:

* Frequently asked questions.  
* Simple form filling.  
* Conversational UI prototypes.

However, it struggles with tasks that require **multiple steps**, **external data**, or **long‑term state**. For example, a user might ask:

> “Can you book a 30‑minute meeting with Alice next week, send her an agenda, and add the event to my Outlook calendar?”

A pure chatbot would need to hand‑off to a human or return a generic “I’m sorry, I can’t do that.” The missing pieces are:

* **Orchestration** – coordinating several APIs (calendar, email, CRM).  
* **Persistence** – remembering the user’s preferences across sessions.  
* **Error recovery** – handling cases where a time slot is unavailable.

### 1.2 The Rise of Agentic Workflows

Agentic workflows address these gaps by treating the LLM as a **decision engine** rather than a static answer generator. The workflow typically follows this loop:

```
while not goal_achieved:
    observation = sense_environment()
    action = LLM.plan(observation, goal)
    result = execute(action)
    update_state(result)
```

Key benefits include:

* **Autonomy** – the system can keep working without constant human prompts.  
* **Extensibility** – new tools can be added without retraining the model.  
* **Transparency** – each step can be logged, audited, and corrected.

Open‑Action Protocol 2.0 provides the **standardized schema** for representing observations, actions, and results, allowing any LLM or tool provider to speak the same language.

## 2. Open‑Action Protocol 2.0 – Core Concepts

OAP 2.0 builds on the original specification by introducing **typed actions**, **structured observations**, and **sandboxed execution contexts**. Below we break down the most important components.

### 2.1 Action Types

| Action Type | Description | Example |
|-------------|-------------|---------|
| `invoke_api` | Call a RESTful endpoint with JSON payload. | `POST /calendar/events` |
| `run_code` | Execute a short snippet of code in a sandboxed runtime (Python, JavaScript, etc.). | `python: generate_agenda()` |
| `read_file` | Retrieve a file from a shared storage bucket. | `GET s3://my-bucket/template.docx` |
| `write_file` | Store data in a file system or object store. | `PUT s3://my-bucket/notes.txt` |
| `human_intervention` | Pause execution and request clarification from a human operator. | `Ask: “Which time zone should I use?”` |

Each action is declared in the **manifest** with a JSON schema describing its required inputs, optional parameters, and expected outputs. This explicit contract enables static validation before runtime.

### 2.2 Observation Payload

Observations are the **state snapshot** the agent receives at each iteration. OAP 2.0 defines a hierarchical structure:

```json
{
  "timestamp": "2026-03-28T14:32:10Z",
  "user_context": {
    "user_id": "U12345",
    "preferences": {
      "timezone": "America/New_York",
      "default_meeting_length": 30
    }
  },
  "environment": {
    "calendar": {
      "free_slots": [
        {"start": "2026-04-02T09:00:00-04:00", "end": "2026-04-02T09:30:00-04:00"},
        {"start": "2026-04-02T11:00:00-04:00", "end": "2026-04-02T11:30:00-04:00"}
      ]
    },
    "crm": {
      "last_contacted": "2026-02-15",
      "open_deals": 3
    }
  }
}
```

The LLM consumes this JSON, reasons about it, and returns a **planned action** conforming to the manifest.

### 2.3 Execution Context & Sandboxing

Security is a first‑class concern in OAP 2.0. Every `run_code` action executes inside a **WebAssembly (Wasm) sandbox** with:

* CPU and memory limits (e.g., 200 ms, 64 MiB).  
* No network access unless explicitly granted via the manifest.  
* File system isolation to a per‑agent temporary directory.

The sandbox returns a deterministic JSON result, which the protocol then validates against the declared output schema.

### 2.4 Protocol Flow

1. **Initialize** – The client sends a `POST /sessions` request with the user’s goal and initial observation.  
2. **Plan** – The LLM returns an `Action` object.  
3. **Execute** – The platform validates the action, runs it, and captures the result.  
4. **Observe** – The result is merged back into the observation payload.  
5. **Loop** – Steps 2‑4 repeat until the goal is marked `completed` or a `max_steps` limit is reached.  
6. **Terminate** – A final `POST /sessions/{id}/close` records the transcript and any side‑effects.

The loop is **stateless** from the perspective of the LLM; all state is carried in the observation JSON, which makes debugging and reproducibility straightforward.

## 3. Designing an Agentic Workflow – A Real‑World Use Case

To illustrate OAP 2.0 in practice, we will build **“MeetBot”**, an autonomous assistant that:

1. Parses a natural‑language request to schedule a meeting.  
2. Finds a mutually free time slot among participants.  
3. Generates a concise agenda using LLM‑driven text generation.  
4. Sends calendar invites and a follow‑up email.  
5. Updates the CRM with the meeting record.

### 3.1 High‑Level Architecture

```
+-------------------+          +-------------------+          +-------------------+
|  Front‑end (Web)  | <--API--> |   OAP Session     | <--SDK--> |   LLM Provider    |
|  (React/TS)       |          |   Manager (Python)|          | (OpenAI, Anthropic)|
+-------------------+          +-------------------+          +-------------------+
           |                               |
           |                               v
           |                     +-------------------+
           |                     |  Action Executor  |
           |                     | (Wasm sandbox +   |
           |                     |  HTTP client)     |
           |                     +-------------------+
           |                               |
           v                               v
+-------------------+          +-------------------+
|   Data Stores     | <--DB--> |   Observations    |
| (Postgres, S3)    |          | (JSON snapshots) |
+-------------------+          +-------------------+
```

* The **front‑end** collects the user’s natural language request and displays progress.  
* The **OAP Session Manager** orchestrates the loop, persisting observations in Postgres.  
* The **Action Executor** implements the concrete `invoke_api`, `run_code`, etc., using a Wasm runtime (e.g., Wasmtime).  
* All external services (Outlook, Gmail, Salesforce) are accessed via **typed API wrappers** defined in the manifest.

### 3.2 Manifest Definition

Below is a trimmed example of the manifest (`manifest.json`) that MeetBot registers with the OAP server.

```json
{
  "name": "MeetBot",
  "version": "2.0",
  "actions": [
    {
      "type": "invoke_api",
      "name": "search_free_slots",
      "description": "Query the calendar service for free time slots for all participants.",
      "input_schema": {
        "type": "object",
        "properties": {
          "participants": {
            "type": "array",
            "items": {"type": "string", "format": "email"}
          },
          "duration_minutes": {"type": "integer", "minimum": 15}
        },
        "required": ["participants", "duration_minutes"]
      },
      "output_schema": {
        "type": "object",
        "properties": {
          "slots": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"}
              },
              "required": ["start", "end"]
            }
          }
        },
        "required": ["slots"]
      },
      "endpoint": "https://api.calendar.example.com/v1/free_slots",
      "method": "POST",
      "auth": "Bearer ${CALENDAR_TOKEN}"
    },
    {
      "type": "run_code",
      "name": "generate_agenda",
      "description": "Create a short agenda based on meeting purpose.",
      "runtime": "python3.11",
      "code": "def generate(purpose):\n    import openai\n    resp = openai.ChatCompletion.create(\n        model='gpt-4o-mini',\n        messages=[{'role':'system','content':'You are an agenda generator.'},\n                  {'role':'user','content':purpose}]\n    )\n    return resp['choices'][0]['message']['content']\n",
      "input_schema": {
        "type": "object",
        "properties": {"purpose": {"type": "string"}},
        "required": ["purpose"]
      },
      "output_schema": {"type": "string"}
    },
    {
      "type": "invoke_api",
      "name": "create_event",
      "description": "Create a calendar event and send invites.",
      "input_schema": {
        "type": "object",
        "properties": {
          "start": {"type": "string", "format": "date-time"},
          "end": {"type": "string", "format": "date-time"},
          "participants": {"type": "array", "items": {"type": "string", "format":"email"}},
          "agenda": {"type": "string"},
          "title": {"type": "string"}
        },
        "required": ["start","end","participants","agenda","title"]
      },
      "output_schema": {"type":"object","properties":{"event_id":{"type":"string"}},"required":["event_id"]},
      "endpoint":"https://api.calendar.example.com/v1/events",
      "method":"POST",
      "auth":"Bearer ${CALENDAR_TOKEN}"
    },
    {
      "type": "invoke_api",
      "name": "log_meeting_crm",
      "description":"Record the meeting in the CRM system.",
      "input_schema": {
        "type":"object",
        "properties": {
          "contact_email": {"type":"string","format":"email"},
          "event_id": {"type":"string"},
          "title": {"type":"string"},
          "agenda": {"type":"string"}
        },
        "required":["contact_email","event_id","title","agenda"]
      },
      "output_schema": {"type":"object","properties":{"status":{"type":"string"}},"required":["status"]},
      "endpoint":"https://api.crm.example.com/v1/meetings",
      "method":"POST",
      "auth":"Bearer ${CRM_TOKEN}"
    }
  ]
}
```

Key takeaways:

* **Typed contracts** guarantee that the LLM cannot request an undefined API.  
* Sensitive credentials are injected via environment variables (`${CALENDAR_TOKEN}`) at runtime, never hard‑coded.  
* The `run_code` action includes the Python source directly; OAP’s sandbox compiles it to Wasm before execution.

## 4. Implementing the Session Manager

Below is a concise but functional implementation in Python (3.11) using FastAPI. It demonstrates the **session lifecycle** and the OAP loop.

```python
# file: session_manager.py
import uuid
import json
import asyncio
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import httpx
import os

app = FastAPI(title="Open-Action Protocol 2.0 Session Manager")

# In‑memory store for demo; replace with Postgres in production
SESSIONS: Dict[str, Dict[str, Any]] = {}

class Observation(BaseModel):
    timestamp: str
    user_context: Dict[str, Any]
    environment: Dict[str, Any]

class Goal(BaseModel):
    description: str

class InitRequest(BaseModel):
    goal: Goal
    observation: Observation
    max_steps: Optional[int] = 10

class ActionResult(BaseModel):
    action_name: str
    success: bool
    output: Optional[Any] = None
    error: Optional[str] = None

# ----------------------------------------------------------------------
# Helper: load manifest once at startup
# ----------------------------------------------------------------------
with open("manifest.json") as f:
    MANIFEST = json.load(f)

def get_action_def(name: str) -> Dict[str, Any]:
    for act in MANIFEST["actions"]:
        if act["name"] == name:
            return act
    raise ValueError(f"Action {name} not defined in manifest")

# ----------------------------------------------------------------------
# Core loop – called by client or background worker
# ----------------------------------------------------------------------
async def run_step(session_id: str) -> ActionResult:
    session = SESSIONS[session_id]
    observation = session["observation"]
    goal = session["goal"]

    # 1️⃣ Ask the LLM to plan the next action
    # For demo we use OpenAI's ChatCompletion; replace with any provider.
    llm_payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are an autonomous scheduling assistant. Use only the actions defined in the manifest."},
            {"role": "user", "content": f"Goal: {goal['description']}\nObservation: {json.dumps(observation)}"}
        ],
        "temperature": 0.2,
        "max_tokens": 300
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json=llm_payload,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="LLM request failed")
    llm_reply = resp.json()["choices"][0]["message"]["content"]
    # Expect a JSON block like: {"action":"search_free_slots","args":{...}}
    try:
        plan = json.loads(llm_reply)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="LLM did not return valid JSON plan")

    action_name = plan["action"]
    args = plan["args"]
    action_def = get_action_def(action_name)

    # 2️⃣ Execute the action
    try:
        if action_def["type"] == "invoke_api":
            async with httpx.AsyncClient() as client:
                endpoint = action_def["endpoint"]
                method = action_def["method"]
                # Simple auth injection
                headers = {"Authorization": f"Bearer {os.getenv('CALENDAR_TOKEN')}"}
                response = await client.request(method, endpoint, json=args, headers=headers, timeout=10)
                response.raise_for_status()
                output = response.json()
        elif action_def["type"] == "run_code":
            # Minimal sandbox – in production use Wasmtime or similar.
            # Here we exec the code in a restricted globals dict.
            code = action_def["code"]
            local_ns = {}
            exec(code, {"__builtins__": {}}, local_ns)
            func = local_ns["generate"]
            output = func(**args)
        else:
            raise ValueError(f"Unsupported action type {action_def['type']}")
        success = True
    except Exception as exc:
        output = None
        success = False
        error_msg = str(exc)

    # 3️⃣ Merge result into observation for next iteration
    if success:
        # Simple merge – you can implement smarter diff/patch logic.
        observation["environment"].update(output if isinstance(output, dict) else {})
    # Save updated observation
    session["observation"] = observation
    session["steps"] += 1

    result = ActionResult(
        action_name=action_name,
        success=success,
        output=output,
        error=error_msg if not success else None,
    )
    return result

# ----------------------------------------------------------------------
# API endpoints
# ----------------------------------------------------------------------
@app.post("/sessions")
async def create_session(req: InitRequest = Body(...)):
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "goal": req.goal.dict(),
        "observation": req.observation.dict(),
        "max_steps": req.max_steps,
        "steps": 0,
        "history": [],
        "completed": False,
    }
    return {"session_id": session_id}

@app.post("/sessions/{session_id}/step")
async def step(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    session = SESSIONS[session_id]
    if session["completed"]:
        raise HTTPException(status_code=400, detail="Session already completed")
    if session["steps"] >= session["max_steps"]:
        session["completed"] = True
        return {"detail": "Max steps reached, terminating"}

    result = await run_step(session_id)
    session["history"].append(result.dict())
    # Simple completion check – in real use you’d parse LLM’s “finished” flag
    if result.success and result.action_name == "log_meeting_crm":
        session["completed"] = True
        return {"detail": "Goal achieved", "result": result}
    return {"result": result, "steps_done": session["steps"]}

@app.post("/sessions/{session_id}/close")
async def close(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    transcript = SESSIONS.pop(session_id)
    # Persist transcript to a DB or S3 bucket here.
    # For demo we just return it.
    return {"transcript": transcript}
```

**Explanation of key sections:**

* **Manifest loading** – ensures the manager knows which actions are permitted.  
* **LLM planning** – we ask the model to output a strict JSON plan; temperature is low to reduce hallucination.  
* **Action execution** – `invoke_api` uses `httpx` with a timeout; `run_code` runs inside a deliberately restricted Python environment (production should replace this with a real Wasm sandbox).  
* **Observation merging** – the result of each action is merged back into the observation, allowing the LLM to see the updated state.  
* **Completion logic** – after the final `log_meeting_crm` action the session is marked complete.

Deploy this FastAPI app with Docker:

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "session_manager:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t meetbot-session .
docker run -d -p 8000:8000 -e OPENAI_API_KEY=... -e CALENDAR_TOKEN=... -e CRM_TOKEN=... meetbot-session
```

The front‑end can now POST `/sessions` with the user request, poll `/step` until completion, and finally call `/close` to store the transcript.

## 5. Putting It All Together – End‑to‑End Example

Let’s walk through a concrete user interaction.

### 5.1 User Input

> “Hey MeetBot, schedule a 45‑minute product demo with **alice@example.com** and **bob@example.com** next week. The demo should cover the new AI analytics dashboard.”

### 5.2 Initialization Request (JSON)

```json
{
  "goal": {"description": "Schedule product demo with Alice and Bob"},
  "observation": {
    "timestamp": "2026-03-28T14:00:00Z",
    "user_context": {
      "user_id": "U998877",
      "preferences": {"timezone": "America/Los_Angeles", "default_meeting_length": 45}
    },
    "environment": {
      "calendar": {"free_slots": []},
      "crm": {"contact_email": "alice@example.com", "open_deals": 2}
    }
  },
  "max_steps": 7
}
```

The client receives a `session_id` (e.g., `c1b3f9e2-...`) and begins stepping.

### 5.3 Step 1 – Search Free Slots

* **LLM plan** (produced by the model):

```json
{
  "action": "search_free_slots",
  "args": {
    "participants": ["alice@example.com", "bob@example.com"],
    "duration_minutes": 45
  }
}
```

* **Executor** calls the calendar API, receives:

```json
{
  "slots": [
    {"start":"2026-04-03T10:00:00-07:00","end":"2026-04-03T10:45:00-07:00"},
    {"start":"2026-04-04T14:00:00-07:00","end":"2026-04-04T14:45:00-07:00"}
  ]
}
```

* Observation is updated with `environment.calendar.free_slots`.

### 5.4 Step 2 – Generate Agenda

* **LLM plan**:

```json
{
  "action": "generate_agenda",
  "args": {
    "purpose": "Demo the new AI analytics dashboard, covering data ingestion, model training, and real‑time visualizations."
  }
}
```

* **Sandboxed Python** runs the `generate` function, returning:

```
Agenda:
1. Introduction & objectives (5 min)
2. Data pipeline overview (10 min)
3. Model training walkthrough (15 min)
4. Live analytics demo (10 min)
5. Q&A (5 min)
```

Observation now contains an `agenda` field.

### 5.5 Step 3 – Create Calendar Event

* **LLM plan** picks the earliest slot:

```json
{
  "action": "create_event",
  "args": {
    "start": "2026-04-03T10:00:00-07:00",
    "end": "2026-04-03T10:45:00-07:00",
    "participants": ["alice@example.com","bob@example.com"],
    "agenda": "Agenda:\n1. Introduction ...",
    "title": "Product Demo – AI Analytics Dashboard"
  }
}
```

* API response:

```json
{"event_id":"ev_12345abcd"}
```

### 5.6 Step 4 – Log Meeting in CRM

* **LLM plan**:

```json
{
  "action": "log_meeting_crm",
  "args": {
    "contact_email": "alice@example.com",
    "event_id": "ev_12345abcd",
    "title": "Product Demo – AI Analytics Dashboard",
    "agenda": "Agenda:\n1. Introduction ..."
  }
}
```

* CRM returns `{ "status":"recorded" }`.

### 5.7 Completion

The session manager marks the session as **completed** because the final action succeeded. The front‑end now displays:

> “✅ Your demo is scheduled for **April 3, 2026 at 10 AM PT**. Invitations have been sent, and the meeting is logged in the CRM.”

All steps, observations, and LLM messages are stored as a JSON transcript—valuable for audit, debugging, and future model fine‑tuning.

## 6. Best Practices & Gotchas

### 6.1 Security First

* **Least privilege** – Only expose the minimum set of actions a particular agent needs.  
* **Credential injection** – Use a secret manager (AWS Secrets Manager, HashiCorp Vault) to inject tokens at runtime. Never store them in the manifest.  
* **Sandbox limits** – Enforce strict CPU / memory caps for `run_code`. Prefer Wasm over native Python `exec`.  
* **Input validation** – The manifest’s JSON schema is automatically enforced before execution; treat any validation failure as a potential attack vector.

### 6.2 Observability

* **Structured logging** – Emit a JSON log line for each step containing `session_id`, `step_number`, `action_name`, `duration_ms`, `success`.  
* **Tracing** – Correlate LLM calls, API invocations, and sandbox runs using OpenTelemetry.  
* **Metrics** – Track average steps per session, failure rates per action, and latency of external APIs.

### 6.3 Handling Ambiguity

LLMs can produce ambiguous plans (e.g., missing required fields). Mitigate by:

1. **Schema‑guided prompting** – Include the JSON schema in the system prompt.  
2. **Post‑parse validation** – Reject plans that don’t conform, ask the model to regenerate.  
3. **Human‑in‑the‑loop fallback** – If a plan fails validation three times, raise a `human_intervention` action.

### 6.4 Scaling the Loop

* **Parallel sessions** – Each session is independent; run them on a Kubernetes cluster with autoscaling.  
* **Batch API calls** – When many agents need to read the same calendar, batch the `search_free_slots` calls to reduce rate‑limit pressure.  
* **Caching** – Store recent free‑slot queries for a short TTL (e.g., 30 seconds) to avoid redundant external calls.

### 6.5 Versioning the Manifest

Because the manifest defines the contract, treat it like a public API:

* **Semantic versioning** – `2.0.0` → `2.1.0` for backward‑compatible additions, `3.0.0` for breaking changes.  
* **Feature flags** – Deploy new actions behind a flag; existing agents continue using the older manifest until they are upgraded.

## 7. Extending the Pattern – Other Domains

The same OAP 2.0 workflow can power agents in:

| Domain | Example Agent | Core Actions |
|--------|---------------|--------------|
| **Customer Support** | TicketResolver | `search_knowledge_base`, `run_code` (summarize), `invoke_api` (create_ticket) |
| **DevOps Automation** | DeployBot | `run_code` (generate Terraform), `invoke_api` (apply_plan), `human_intervention` (approval) |
| **Financial Advisory** | PortfolioPlanner | `invoke_api` (fetch_market_data), `run_code` (optimize_portfolio), `invoke_api` (place_orders) |
| **Content Production** | BlogWriter | `run_code` (outline_generator), `invoke_api` (image_fetch), `run_code` (seo_analysis) |

In each case, the **manifest** captures domain‑specific tools, while the **LLM** remains a generic planner. This separation dramatically reduces the engineering effort required to spin up new autonomous services.

## 8. Future Directions for OAP

While OAP 2.0 already addresses many pain points, the community is already discussing:

* **Standardized provenance** – Cryptographic signatures for each observation/action to guarantee tamper‑evidence.  
* **Dynamic manifest updates** – Agents could request new actions at runtime, subject to admin approval.  
* **Multi‑agent collaboration** – Protocol extensions for agents to exchange observations directly, enabling swarm‑like behavior.  
* **Fine‑grained cost accounting** – Embedding token‑usage metadata in each step for budgeting in large‑scale deployments.

Stay tuned to the official GitHub repository and the upcoming **OAP 2.1** draft for these features.

## Conclusion

The Open‑Action Protocol 2.0 marks a pivotal moment in the evolution from reactive chatbots to truly **agentic workflows**. By standardizing **typed actions**, **structured observations**, and **sandboxed execution**, OAP gives developers a reliable foundation for building autonomous systems that can:

* Reason across multiple steps.  
* Safely invoke external services.  
* Remain auditable and secure.

In this article we dissected the protocol, built a complete end‑to‑end “MeetBot” implementation, and highlighted best practices for production readiness. Whether you’re automating scheduling, orchestrating cloud deployments, or designing next‑generation customer‑service agents, OAP 2.0 provides the lingua franca that lets large language models act as **real, trustworthy engineers**.

Start experimenting today—define a concise manifest, wire it to your favorite LLM, and watch your applications become self‑driving agents.

## Resources

* [Open‑Action Protocol Specification (v2.0)](https://github.com/openaction/protocol/blob/main/spec/v2.0.md) – The official GitHub repository containing the full spec, examples, and reference implementations.  
* [OpenAI Chat Completion API Documentation](https://platform.openai.com/docs/guides/chat) – Guides on using OpenAI’s LLMs for structured planning and low‑temperature responses.  
* [Wasmtime – Embedding WebAssembly](https://docs.wasmtime.dev/) – Documentation for the Wasmtime runtime, useful for building secure Wasm sandboxes for `run_code` actions.  

---