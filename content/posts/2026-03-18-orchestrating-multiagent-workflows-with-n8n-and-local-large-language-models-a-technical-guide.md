---
title: "Orchestrating Multi‑Agent Workflows with n8n and Local Large Language Models: A Technical Guide"
date: "2026-03-18T04:01:13.034"
draft: false
tags: ["n8n","LLM","workflow automation","multi‑agent systems","AI engineering"]
---

## Introduction

Large language models (LLMs) have moved from research curiosities to production‑ready components that can power everything from chatbots to data extraction pipelines. At the same time, **workflow automation platforms**—especially open‑source, node‑based tools like **n8n**—have become the glue that connects disparate services, handles conditional logic, and provides visual debugging.

When you combine the two, a powerful pattern emerges: **multi‑agent workflows**. Instead of a single monolithic LLM that tries to do everything, you break the problem into specialized *agents* (e.g., a classifier, a summarizer, a planner) and let an orchestrator coordinate them. This approach yields:

* **Modularity** – each agent can be swapped out or fine‑tuned independently.
* **Scalability** – you can run agents in parallel or on different hardware.
* **Transparency** – the orchestrator logs each step, making debugging easier.
* **Cost efficiency** – lightweight agents can run locally, reserving cloud resources for heavy tasks.

In this guide we will walk through the end‑to‑end process of building a multi‑agent workflow with **n8n** as the orchestrator and **local LLMs** (e.g., Ollama, LM Studio, or a self‑hosted Hugging Face model) as the intelligent back‑ends. By the end you will have a production‑ready n8n workflow that:

1. Receives an incoming support ticket.
2. Routes the ticket to a **classification agent** to decide its category.
3. Sends the ticket to a **sentiment agent** to gauge emotional tone.
4. Generates a **draft response** with a **generation agent**.
5. Stores the output in a database and optionally forwards it to a human operator.

> **Note:** The concepts presented here are platform‑agnostic. You can replace n8n with Make, Node‑RED, or any other orchestrator that supports HTTP calls and scripting.

---

## Table of Contents

1. [Prerequisites](#prerequisites)  
2. [Setting Up a Local LLM Server](#setting-up-a-local-llm-server)  
   1. [Ollama Quick‑Start](#ollama-quick-start)  
   2. [Running a Hugging Face Model via `text-generation-inference`](#hugging-face-setup)  
3. [Installing and Configuring n8n](#installing-n8n)  
4. [Designing the Multi‑Agent Architecture](#designing-architecture)  
   1. [Agent Responsibilities](#agent-responsibilities)  
   2. [Data Flow Diagram](#data-flow-diagram)  
5. [Building the Workflow in n8n](#building-workflow)  
   1. [Trigger Node – Webhook](#trigger-webhook)  
   2. [Agent 1: Classification (HTTP Request)](#agent-classification)  
   3. [Agent 2: Sentiment (Function Node + HTTP Request)](#agent-sentiment)  
   4. [Agent 3: Draft Generation (HTTP Request)](#agent-generation)  
   5. [Conditional Routing & Parallel Execution](#conditional-routing)  
   6. [Persisting Results (PostgreSQL / SQLite)](#persist-results)  
7. [Full n8n Workflow JSON Export](#workflow-json)  
8. [Error Handling, Retries, and Logging](#error-handling)  
9. [Performance Tips & Scaling Strategies](#performance)  
10. [Real‑World Use Cases](#real-world)  
11. [Conclusion](#conclusion)  
12. [Resources](#resources)  

---

<a name="prerequisites"></a>

## 1. Prerequisites

| Requirement | Why It Matters | Recommended Version |
|-------------|----------------|---------------------|
| **Docker** | Simplifies deployment of both n8n and local LLM servers. | 24.x+ |
| **Node.js (>=18)** | n8n is a Node.js application; newer LTS versions give better performance. | 18.17 |
| **Git** | For pulling example repositories and version‑controlling workflow definitions. | 2.40+ |
| **Python (optional)** | Some LLM servers (e.g., `text-generation-inference`) rely on Python. | 3.11 |
| **A small GPU (or CPU‑only)** | Local inference can be GPU‑accelerated for speed; CPU‑only works for smaller models. | NVIDIA RTX 3060 or Apple M1/M2 |

You also need a **text editor** (VS Code works great) and basic familiarity with JSON and REST APIs.

---

<a name="setting-up-a-local-llm-server"></a>

## 2. Setting Up a Local LLM Server

There are several ways to expose a local LLM as a REST endpoint. We’ll cover two of the most common approaches:

1. **Ollama** – a lightweight server that ships with many popular models (e.g., Llama 3, Mistral).  
2. **Hugging Face `text-generation-inference`** – a more configurable, container‑based server that can run any model from the HF Hub.

Both expose a **`POST /api/generate`** endpoint that accepts JSON payloads like:

```json
{
  "model": "llama3",
  "prompt": "Your prompt goes here",
  "stream": false,
  "options": {
    "temperature": 0.7,
    "max_new_tokens": 256
  }
}
```

### 2.1 Ollama Quick‑Start

```bash
# Install Ollama (Linux/macOS)
curl -L https://ollama.com/install.sh | sh

# Pull a model (e.g., Llama 3 8B)
ollama pull llama3

# Run the server (defaults to http://127.0.0.1:11434)
ollama serve &
```

**Testing the endpoint**

```bash
curl -X POST http://127.0.0.1:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3","prompt":"Explain quantum entanglement in one sentence","options":{"temperature":0.5}}'
```

You should receive a JSON response with a `response` field containing the generated text.

### 2.2 Running a Hugging Face Model via `text-generation-inference`

```bash
# Pull the Docker image
docker pull ghcr.io/huggingface/text-generation-inference:latest

# Run a model (e.g., Mistral‑7B‑Instruct)
docker run -d --gpus all -p 8080:80 \
  -e MODEL_ID=mistralai/Mistral-7B-Instruct-v0.2 \
  ghcr.io/huggingface/text-generation-inference:latest
```

The container will expose **`http://localhost:8080/generate`**. The request format is similar but includes a `inputs` field instead of `prompt`.

```bash
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"inputs":"Write a haiku about sunrise","parameters":{"max_new_tokens":64}}'
```

Both servers return a JSON object with a `generated_text` (or `response`) key.

---

<a name="installing-n8n"></a>

## 3. Installing and Configuring n8n

n8n can be run directly with Docker, as an npm package, or via the hosted cloud version. For a fully self‑contained environment, Docker is the simplest.

```bash
docker run -d \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n
```

After the container starts, open **`http://localhost:5678`** in your browser. You’ll be prompted to set up a user account. Once logged in, you can start creating workflows.

### Configuring Credentials

1. **HTTP Request Credentials** – Create a new credential set named `LocalLLM` that stores the base URL (`http://127.0.0.1:11434` for Ollama or `http://localhost:8080` for HF).  
2. **Database Credentials** – Add a PostgreSQL or SQLite credential depending on where you want to store the results.

These credentials will be referenced in the workflow nodes to avoid hard‑coding URLs or secrets.

---

<a name="designing-architecture"></a>

## 4. Designing the Multi‑Agent Architecture

A well‑designed architecture makes the workflow easy to extend. Below we outline the responsibilities of each agent and the overall data flow.

<a name="agent-responsibilities"></a>

### 4.1 Agent Responsibilities

| Agent | Core Task | Prompt Example | Output |
|-------|-----------|----------------|--------|
| **Classifier** | Assign a ticket to a category (e.g., *billing*, *technical*, *account*) | `Classify the following support request into one of: Billing, Technical, Account. Ticket: "{{ticket_body}}"` | `"Technical"` |
| **Sentiment Analyzer** | Determine emotional tone (positive, neutral, negative) | `What is the sentiment of the following text? "{{ticket_body}}"` | `"Negative"` |
| **Response Generator** | Draft a helpful reply based on category & sentiment | `Write a concise, friendly response for a {{category}} issue with {{sentiment}} sentiment. Ticket: "{{ticket_body}}"` | `"Hi ..."` |

Each agent is a **stateless** LLM call; the orchestrator (n8n) supplies the prompt and parses the response.

<a name="data-flow-diagram"></a>

### 4.2 Data Flow Diagram

```
[Webhook (Ticket)] --> [Set (Normalize)] --> [Parallel]
                                          |--> [HTTP: Classifier] --> [Set: category]
                                          |--> [HTTP: Sentiment] --> [Set: sentiment]
                                          |
                                          +---> [Merge] --> [HTTP: Generator] --> [Set: reply]
                                                            |
                                                            v
                                                   [Database Insert] --> [Optional Email]
```

- **Parallel execution** reduces latency: classification and sentiment analysis run simultaneously.
- **Merge** node collects both results before the generation step.
- **Conditional routing** can be added (e.g., if sentiment is negative, add escalation flag).

---

<a name="building-workflow"></a>

## 5. Building the Workflow in n8n

Below is a step‑by‑step walkthrough of constructing the workflow. Screenshots are omitted for brevity, but each description matches the UI elements you’ll see.

<a name="trigger-webhook"></a>

### 5.1 Trigger Node – Webhook

1. **Add a new node** → *Webhook*.
2. Set **HTTP Method** to `POST`.
3. Define **Path** as `/ticket`.
4. Enable **Response Mode** → *On Received* (so the caller gets a quick ACK).

The webhook expects a JSON payload:

```json
{
  "ticket_id": "12345",
  "subject": "Cannot access my account",
  "body": "I tried logging in but keep getting an error..."
}
```

<a name="agent-classification"></a>

### 5.2 Agent 1: Classification (HTTP Request)

1. **Add a node** → *HTTP Request* (named *Classify Ticket*).
2. Choose **Credential** → `LocalLLM`.
3. Set **Method** to `POST`.
4. **URL**: `{{ $credentials.LocalLLM.baseUrl }}/api/generate` (Ollama) or `/generate` (HF).
5. **Headers** → `Content-Type: application/json`.
6. **Body** → *JSON*:

```json
{
  "model": "llama3",
  "prompt": "Classify the following support request into one of: Billing, Technical, Account.\nTicket: \"{{ $json.body }}\"",
  "options": {
    "temperature": 0.0,
    "max_new_tokens": 16
  }
}
```

7. **Add a *Function* node** after the HTTP request to extract the raw string:

```javascript
// Ollama response format
const response = items[0].json.response.trim();
return [{ json: { category: response } }];
```

If using HF, adjust to `items[0].json.generated_text`.

<a name="agent-sentiment"></a>

### 5.3 Agent 2: Sentiment (Function + HTTP Request)

We’ll illustrate a **two‑step** approach: first format the prompt, then call the LLM.

**Prompt Builder (Function node)**:

```javascript
const body = $json.body;
return [{
  json: {
    prompt: `What is the sentiment (Positive, Neutral, Negative) of the following text?\n"${body}"`
  }
}];
```

**HTTP Request (Sentiment LLM)** – identical to the classification node but with a different prompt. Use the same extraction function as before, naming the output `sentiment`.

<a name="agent-generation"></a>

### 5.4 Agent 3: Draft Generation (HTTP Request)

Now we have three pieces of data: `category`, `sentiment`, and the original ticket.

1. **Merge** node – combine the outputs of classification and sentiment with the original webhook data. Set **Mode** to *Combine* and **Keep Only Set** to `true`.
2. **Function node** to craft the final prompt:

```javascript
const { body, category, sentiment } = $json;
return [{
  json: {
    prompt: `Write a concise, friendly response for a ${category} issue with ${sentiment.toLowerCase()} sentiment.\nTicket: "${body}"`
  }
}];
```

3. **HTTP Request** – same endpoint, but with a higher `temperature` (e.g., 0.7) and longer `max_new_tokens` (e.g., 256). The extraction function now returns `reply`.

<a name="conditional-routing"></a>

### 5.5 Conditional Routing & Parallel Execution

- **Parallel** node: Connect the *Classify Ticket* and *Sentiment* branches to a *Parallel* node. This ensures both HTTP calls fire simultaneously.
- **Merge** node: After the parallel branches, attach a *Merge* node (mode: *Wait for All*) to collect `category` and `sentiment`.
- **If** node (optional): If `sentiment === "Negative"`, add a step that flags the ticket for human review. Example:

```javascript
return $json.sentiment === "Negative";
```

The **true** branch could trigger an email or Slack notification.

<a name="persist-results"></a>

### 5.6 Persisting Results (PostgreSQL / SQLite)

1. **Add a node** → *Postgres* (or *SQLite*) named *Save Ticket*.
2. Use the database credentials you set earlier.
3. **Operation** → *Insert*.
4. **Table** → `tickets`.
5. **Columns**: `ticket_id`, `subject`, `body`, `category`, `sentiment`, `reply`, `created_at`.
6. Map each column to the appropriate JSON value (`$json.ticket_id`, `$json.reply`, etc.).

If you prefer a NoSQL store, replace the node with a *MongoDB* or *Firestore* node—n8n supports them out of the box.

---

<a name="workflow-json"></a>

## 6. Full n8n Workflow JSON Export

Below is the complete JSON representation that can be imported via **Import → From File** in the n8n UI. Replace placeholder IDs (`"1"` etc.) with the ones generated in your environment; the structure remains the same.

```json
{
  "nodes": [
    {
      "parameters": {
        "path": "ticket",
        "method": "POST",
        "responseMode": "onReceived",
        "options": {}
      },
      "id": "1",
      "name": "Ticket Webhook",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 1,
      "position": [ -300, 0 ]
    },
    {
      "parameters": {
        "functionCode": "return [{ json: { body: $json.body, ticket_id: $json.ticket_id, subject: $json.subject } }];"
      },
      "id": "2",
      "name": "Set Ticket Data",
      "type": "n8n-nodes-base.function",
      "typeVersion": 1,
      "position": [ -100, 0 ]
    },
    {
      "parameters": {
        "url": "={{ $credentials.LocalLLM.baseUrl }}/api/generate",
        "method": "POST",
        "jsonParameters": true,
        "options": {},
        "bodyParametersJson": "={{\n  \"model\": \"llama3\",\n  \"prompt\": \"Classify the following support request into one of: Billing, Technical, Account.\\nTicket: \\\"{{ $json.body }}\\\"\",\n  \"options\": { \"temperature\": 0.0, \"max_new_tokens\": 16 }\n}}"
      },
      "id": "3",
      "name": "Classify Ticket",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 1,
      "position": [ 100, -200 ],
      "credentials": {
        "httpRequestApi": {
          "id": "LocalLLM",
          "name": "LocalLLM"
        }
      }
    },
    {
      "parameters": {
        "functionCode": "const resp = items[0].json.response.trim();\nreturn [{ json: { category: resp } }];"
      },
      "id": "4",
      "name": "Extract Category",
      "type": "n8n-nodes-base.function",
      "typeVersion": 1,
      "position": [ 300, -200 ]
    },
    {
      "parameters": {
        "functionCode": "return [{ json: { prompt: `What is the sentiment (Positive, Neutral, Negative) of the following text?\\n\\\"${$json.body}\\\"` } }];"
      },
      "id": "5",
      "name": "Build Sentiment Prompt",
      "type": "n8n-nodes-base.function",
      "typeVersion": 1,
      "position": [ 100, 200 ]
    },
    {
      "parameters": {
        "url": "={{ $credentials.LocalLLM.baseUrl }}/api/generate",
        "method": "POST",
        "jsonParameters": true,
        "options": {},
        "bodyParametersJson": "={{\n  \"model\": \"llama3\",\n  \"prompt\": $json.prompt,\n  \"options\": { \"temperature\": 0.0, \"max_new_tokens\": 8 }\n}}"
      },
      "id": "6",
      "name": "Sentiment LLM",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 1,
      "position": [ 300, 200 ],
      "credentials": {
        "httpRequestApi": {
          "id": "LocalLLM",
          "name": "LocalLLM"
        }
      }
    },
    {
      "parameters": {
        "functionCode": "const resp = items[0].json.response.trim();\nreturn [{ json: { sentiment: resp } }];"
      },
      "id": "7",
      "name": "Extract Sentiment",
      "type": "n8n-nodes-base.function",
      "typeVersion": 1,
      "position": [ 500, 200 ]
    },
    {
      "parameters": {
        "mode": "wait",
        "type": "merge"
      },
      "id": "8",
      "name": "Merge Data",
      "type": "n8n-nodes-base.merge",
      "typeVersion": 1,
      "position": [ 600, 0 ]
    },
    {
      "parameters": {
        "functionCode": "return [{ json: { prompt: `Write a concise, friendly response for a ${$json.category} issue with ${$json.sentiment.toLowerCase()} sentiment.\\nTicket: \\\"${$json.body}\\\"` } }];"
      },
      "id": "9",
      "name": "Build Generation Prompt",
      "type": "n8n-nodes-base.function",
      "typeVersion": 1,
      "position": [ 800, 0 ]
    },
    {
      "parameters": {
        "url": "={{ $credentials.LocalLLM.baseUrl }}/api/generate",
        "method": "POST",
        "jsonParameters": true,
        "options": {},
        "bodyParametersJson": "={{\n  \"model\": \"llama3\",\n  \"prompt\": $json.prompt,\n  \"options\": { \"temperature\": 0.7, \"max_new_tokens\": 256 }\n}}"
      },
      "id": "10",
      "name": "Generate Reply",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 1,
      "position": [ 1000, 0 ],
      "credentials": {
        "httpRequestApi": {
          "id": "LocalLLM",
          "name": "LocalLLM"
        }
      }
    },
    {
      "parameters": {
        "functionCode": "const resp = items[0].json.response.trim();\nreturn [{ json: { reply: resp } }];"
      },
      "id": "11",
      "name": "Extract Reply",
      "type": "n8n-nodes-base.function",
      "typeVersion": 1,
      "position": [ 1200, 0 ]
    },
    {
      "parameters": {
        "operation": "insert",
        "table": "tickets",
        "columns": [
          { "name": "ticket_id", "value": "={{ $json.ticket_id }}" },
          { "name": "subject", "value": "={{ $json.subject }}" },
          { "name": "body", "value": "={{ $json.body }}" },
          { "name": "category", "value": "={{ $json.category }}" },
          { "name": "sentiment", "value": "={{ $json.sentiment }}" },
          { "name": "reply", "value": "={{ $json.reply }}" },
          { "name": "created_at", "value": "={{ $now }}" }
        ]
      },
      "id": "12",
      "name": "Save Ticket",
      "type": "n8n-nodes-base.postgres",
      "typeVersion": 1,
      "position": [ 1400, 0 ],
      "credentials": {
        "postgres": {
          "id": "PostgresDB",
          "name": "PostgresDB"
        }
      }
    },
    {
      "parameters": {
        "condition": "={{ $json.sentiment === \"Negative\" }}",
        "mode": "always"
      },
      "id": "13",
      "name": "If Negative Sentiment",
      "type": "n8n-nodes-base.if",
      "typeVersion": 1,
      "position": [ 1200, 200 ]
    },
    {
      "parameters": {
        "toEmail": "support@mycompany.com",
        "subject": "Ticket {{ $json.ticket_id }} needs human review",
        "text": "Sentiment was negative. Category: {{ $json.category }}.\n\nTicket body:\n{{ $json.body }}\n\nDraft reply:\n{{ $json.reply }}"
      },
      "id": "14",
      "name": "Escalate Email",
      "type": "n8n-nodes-base.emailSend",
      "typeVersion": 1,
      "position": [ 1400, 200 ],
      "credentials": {
        "smtp": {
          "id": "SMTP",
          "name": "SMTP"
        }
      }
    }
  ],
  "connections": {
    "Ticket Webhook": { "main": [ [ { "node": "Set Ticket Data", "type": "main", "index": 0 } ] ] },
    "Set Ticket Data": { "main": [ [ { "node": "Classify Ticket", "type": "main", "index": 0 }, { "node": "Build Sentiment Prompt", "type": "main", "index": 0 } ] ] },
    "Classify Ticket": { "main": [ [ { "node": "Extract Category", "type": "main", "index": 0 } ] ] },
    "Extract Category": { "main": [ [ { "node": "Merge Data", "type": "main", "index": 0 } ] ] },
    "Build Sentiment Prompt": { "main": [ [ { "node": "Sentiment LLM", "type": "main", "index": 0 } ] ] },
    "Sentiment LLM": { "main": [ [ { "node": "Extract Sentiment", "type": "main", "index": 0 } ] ] },
    "Extract Sentiment": { "main": [ [ { "node": "Merge Data", "type": "main", "index": 0 } ] ] },
    "Merge Data": { "main": [ [ { "node": "Build Generation Prompt", "type": "main", "index": 0 } ] ] },
    "Build Generation Prompt": { "main": [ [ { "node": "Generate Reply", "type": "main", "index": 0 } ] ] },
    "Generate Reply": { "main": [ [ { "node": "Extract Reply", "type": "main", "index": 0 } ] ] },
    "Extract Reply": { "main": [ [ { "node": "Save Ticket", "type": "main", "index": 0 }, { "node": "If Negative Sentiment", "type": "main", "index": 0 } ] ] },
    "If Negative Sentiment": {
      "main": [
        [ { "node": "Escalate Email", "type": "main", "index": 0 } ],
        []
      ]
    }
  },
  "active": false,
  "settings": {},
  "id": "workflow_1"
}
```

Importing this JSON gives you a fully functional ticket‑triage pipeline that can be tested with a simple `curl`:

```bash
curl -X POST http://localhost:5678/webhook/ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"T-1001","subject":"Login failure","body":"I cannot log in after the recent password reset."}'
```

You should see the workflow execute, store the ticket in your DB, and (if sentiment is negative) send an escalation email.

---

<a name="error-handling"></a>

## 7. Error Handling, Retries, and Logging

A production workflow must survive transient failures:

| Failure Mode | n8n Strategy | Implementation |
|--------------|--------------|----------------|
| **LLM server timeout** | Automatic retries | In the *HTTP Request* node, enable **Retry on Failure** (max 3 attempts, exponential back‑off). |
| **Invalid JSON response** | Conditional check | Add a *Function* node that verifies `response` is a non‑empty string; if empty, route to an *Error* branch that logs to a file or Slack. |
| **Database write error** | Transactional fallback | Wrap *Save Ticket* in a *Try / Catch* (use *Error Trigger* node) and push failed rows to a dead‑letter queue (e.g., a CSV file). |
| **Unexpected sentiment label** | Validation node | Use an *If* node that checks `sentiment` ∈ {Positive, Neutral, Negative}; otherwise default to *Neutral* and log a warning. |

**Logging** – n8n provides a built‑in **Execution Log** UI. For external observability, add a *Webhook* node at the end of each branch that forwards a JSON payload to a logging service like **Logflare** or **Datadog**.

---

<a name="performance"></a>

## 8. Performance Tips & Scaling Strategies

| Aspect | Recommendation | Reason |
|--------|----------------|--------|
| **Model size** | Start with 7‑8 B parameters for classification/sentiment; use a larger 13‑34 B model only for generation. | Smaller models are faster and consume less VRAM, suitable for high‑frequency calls. |
| **Batching** | If you expect bursts of tickets, batch them (e.g., 5 tickets per LLM call) using *SplitInBatches* node. | Reduces per‑call overhead and improves GPU utilization. |
| **GPU sharing** | Run multiple n8n workers (Docker `replicas`) that share the same GPU via NVIDIA Docker multi‑process service (MPS). | Allows parallel inference without spawning separate containers per request. |
| **Cache** | Store recent classification results in Redis (`Set`/`Get` nodes). | Sentiment of identical tickets rarely changes; caching cuts down inference cost. |
| **Streaming** | Ollama supports `stream=true`. Use n8n’s *WebSocket* node to stream partial responses if you need immediate user feedback. | Improves perceived latency for interactive UIs. |

---

<a name="real-world"></a>

## 9. Real‑World Use Cases

1. **Customer Support Automation** – As demonstrated, triage tickets, draft replies, and route escalations.  
2. **Content Moderation Pipelines** – Agents: language detection → toxicity classification → auto‑removal or flagging.  
3. **Document Processing** – Agents: OCR → entity extraction → summarization → storage in a knowledge base.  
4. **Sales Lead Qualification** – Agents: intent detection → scoring → assignment to a sales rep.  

In each scenario the pattern stays the same: *n8n* orchestrates, *LLMs* provide intelligence, and *stateful services* (DB, cache) hold the results.

---

<a name="conclusion"></a>

## 10. Conclusion

Orchestrating multi‑agent workflows with **n8n** and **local large language models** unlocks a sweet spot between flexibility and control. By decomposing a complex task into focused agents, you gain:

* **Modularity** – swap or fine‑tune individual prompts without breaking the whole pipeline.  
* **Speed & Cost Efficiency** – run lightweight classification locally; reserve heavy generation for occasional calls.  
* **Transparency** – every step is logged, making debugging and compliance straightforward.  

The technical guide above walked you through installing a local LLM server, configuring n8n, designing the agent architecture, building a full‑featured ticket‑triage workflow, and scaling it for production use. Armed with this knowledge, you can now experiment with other domains, integrate additional tools (e.g., vector stores, LangChain), and push the boundaries of what autonomous AI pipelines can achieve.

Happy automating!

---

<a name="resources"></a>

## Resources

1. **n8n Documentation** – Comprehensive guide to nodes, credentials, and workflow design.  
   <https://docs.n8n.io/>

2. **Ollama – Run LLMs Locally** – Official site with model catalog and API reference.  
   <https://ollama.com/>

3. **Hugging Face Text Generation Inference** – Dockerized inference server for any HF model.  
   <https://github.com/huggingface/text-generation-inference>

4. **LangChain – Building LLM‑Centric Applications** – Helpful patterns for prompting and chaining agents.  
   <https://python.langchain.com/>

5. **OpenAI Cookbook – Prompt Engineering** – Best practices that apply to any LLM, not just OpenAI.  
   <https://github.com/openai/openai-cookbook>

---