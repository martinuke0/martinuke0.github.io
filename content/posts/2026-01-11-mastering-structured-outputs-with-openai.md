---
title: "Mastering Structured Outputs with OpenAI"
date: "2026-01-11T13:24:23.150"
draft: false
tags: ["openai", "structured-outputs", "json-schema", "function-calling", "developers"]
---

## Introduction

OpenAI’s **Structured Outputs** fundamentally change how developers build reliable applications on top of large language models. Instead of coaxing models with elaborate prompts to “return valid JSON,” you can now **guarantee** that responses conform to a **precise JSON Schema** or typed model, drastically reducing parsing errors, retries, and brittle post-processing.[1][2][7]

This article explains **very detailed structured outputs with OpenAI**: what they are, how they differ from older patterns (like plain JSON mode), how to design robust schemas, integration patterns (Node, Python, Azure OpenAI, LangChain, third‑party helpers), and where to find the most useful **documentation and learning resources**.

---

## 1. What Are Structured Outputs?

**Structured Outputs** are an OpenAI API feature that ensures model responses always match a supplied **JSON Schema**, or equivalent type definition, when `strict: true` is enabled.[1][2][7]

Key points:

- You provide a **schema** (JSON Schema, Zod, Pydantic, etc.).
- The model is constrained so the response **must** match that schema.
- If the model needs to refuse for safety reasons, this happens in a **schema-respecting** way that is programmatically detectable.[2][5]
- Works for:
  - **Response formats** (direct response schema)[1][7]
  - **Tools / function calling** with `strict: true`[2][4][7]

This is unlike earlier approaches where you had to parse free-form text or rely only on “valid JSON” promises.

---

## 2. Structured Outputs vs JSON Mode vs Plain Text

OpenAI’s evolution of output control can be summarized as:

| Approach          | What you get                                                 | Problem it solves                         | Limitations                                           |
|-------------------|--------------------------------------------------------------|-------------------------------------------|-------------------------------------------------------|
| Plain text        | Natural language only                                        | Human-readable answers                    | No machine-readable structure                         |
| JSON mode         | Guaranteed **valid JSON**, but not strict schema adherence[2][4] | Easier parsing                            | Keys/types may not match your expectations           |
| Structured Outputs| JSON that **must match your JSON Schema** exactly[1][2][7]   | Strong type safety, fewer retries         | Requires schema design; slightly more setup effort    |

**Structured Outputs** solve the common issue where JSON was syntactically valid but **semantically wrong**: missing fields, wrong types, or extra keys.[2][4][7]

---

## 3. Core Concepts: JSON Schema & `strict: true`

### 3.1 JSON Schema as the contract

The central idea: you define a **contract** that the model must follow, using JSON Schema (or a higher-level typing system that compiles to JSON Schema).[1][2][4][7]

Examples of schema elements:

- `type`: `"string"`, `"number"`, `"boolean"`, `"object"`, `"array"`…
- `properties`: fields for objects
- `required`: mandatory fields
- `additionalProperties`: control extra keys (`false` to disallow)[1][2][4]
- `enum`: allowed fixed values
- Nested schemas: arrays of objects, objects of objects, etc.[1][7]

The model is trained and constrained to obey this schema **exactly**, including nested structures and required properties.[1][2][7]

### 3.2 Enabling strict mode

There are **two main ways** to get structured outputs in OpenAI’s API:[2][7]

1. **Response format / `response_format`**  
   - Provide a JSON Schema in the `response_format` parameter and set `strict: true`.[1][7]

2. **Function calling / tools**  
   - Provide tool definitions with JSON Schema for parameters and set `strict: true` in the tool definition.[2][4][7]

In both cases, `strict: true` is what upgrades normal JSON mode into **Structured Outputs**.[2][7]

---

## 4. Using Structured Outputs in OpenAI’s Chat Completions API

### 4.1 Node.js with Zod helper

OpenAI’s official docs show a Node.js helper using **Zod** to define schemas and automatically parse responses.[1][7]

```ts
import OpenAI from "openai";
import { zodResponseFormat } from "openai/helpers/zod";
import { z } from "zod";

const client = new OpenAI();

const Step = z.object({
  explanation: z.string(),
  output: z.string(),
});

const MathReasoning = z.object({
  steps: z.array(Step),
  final_answer: z.string(),
});

async function solveMath() {
  const completion = await client.chat.completions.create({
    model: "gpt-4o-2024-08-06",
    messages: [      { role: "user", content: "What is (12 + 8) * 3?" }
    ],
    response_format: zodResponseFormat(MathReasoning, "math_reasoning"),
  });

  const result = completion.choices.message;
  // With helpers, you can access `message.parsed` as a typed object in supported flows[1]
}
```

Here:

- `MathReasoning` is a Zod schema, which is converted to JSON Schema behind the scenes.[1]
- The response is guaranteed to have `steps` (array) and `final_answer` (string), with no extra properties.[1][7]

### 4.2 Raw JSON Schema in `response_format`

You don’t have to use Zod. You can pass a JSON Schema directly.[1][2][7]

```ts
const schema = {
  type: "object",
  properties: {
    reasoning_steps: {
      type: "array",
      items: { type: "string" },
      description: "Reasoning steps leading to the final conclusion."
    },
    answer: {
      type: "string",
      description: "The final answer."
    }
  },
  required: ["reasoning_steps", "answer"],
  additionalProperties: false
};

const completion = await client.chat.completions.create({
  model: "gpt-4.1-mini",
  messages: [{ role: "user", content: "Explain photosynthesis in 3 steps." }],
  response_format: {
    type: "json_schema",
    json_schema: {
      name: "explanation",
      schema,
      strict: true
    }
  }
});
```

This ensures:

- The result is always an object with:
  - `reasoning_steps`: array of strings
  - `answer`: string
- No extra fields (because `additionalProperties: false`).[1][2][4]

---

## 5. Function Calling + Structured Outputs (`tools`)

Structured Outputs also enhance **function calling** by ensuring tool arguments conform exactly to the specified schema when `strict: true` is set.[2][4][7]

### 5.1 Strict tool definition

```ts
const tools = [  {
    type: "function",
    function: {
      name: "create_task",
      strict: true,
      parameters: {
        type: "object",
        properties: {
          title: { type: "string" },
          due_date: { type: "string", format: "date-time" },
          priority: { type: "string", enum: ["low", "medium", "high"] }
        },
        required: ["title", "priority"],
        additionalProperties: false
      }
    }
  }
];
```

When the model calls `create_task`, the `arguments` field:

- Must include `title` and `priority`.
- Must not include any extra keys.
- Must use one of the allowed values for `priority`.[2][4][5]

This significantly reduces brittle JSON parsing in agent workflows.

---

## 6. Designing Very Detailed, Robust Schemas

If your goal is **very detailed structured outputs**, schema design is critical. Below are practical patterns for complex schemas.

### 6.1 Nested objects with strong typing

Example: A content extraction schema:

```json
{
  "type": "object",
  "properties": {
    "title": { "type": "string" },
    "summary": { "type": "string" },
    "sections": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "heading": { "type": "string" },
          "key_points": {
            "type": "array",
            "items": { "type": "string" }
          }
        },
        "required": ["heading", "key_points"],
        "additionalProperties": false
      }
    }
  },
  "required": ["title", "summary", "sections"],
  "additionalProperties": false
}
```

Benefits:

- Predictable, hierarchical structure enabling downstream processing.
- No surprise fields that break your serializers or UI.[1][2][4]

### 6.2 Enums for controlled vocabularies

Use `enum` to enforce specific labels:

```json
{
  "type": "object",
  "properties": {
    "sentiment": {
      "type": "string",
      "enum": ["positive", "neutral", "negative"]
    },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
  },
  "required": ["sentiment", "confidence"],
  "additionalProperties": false
}
```

The model must pick only one of the enum values, allowing safe downstream logic (e.g., database constraints, analytics).[1][2]

### 6.3 Optional vs required fields

Use `required` carefully:

- Put **core contract fields** in `required`.
- Leave optional fields out of `required`.  

For instance:

```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string" },
    "description": { "type": "string" },
    "tags": {
      "type": "array",
      "items": { "type": "string" }
    }
  },
  "required": ["name"],
  "additionalProperties": false
}
```

This allows flexibility while still ensuring a stable minimal shape.

### 6.4 Disallowing unknown fields

Set `additionalProperties: false` at each relevant object level to avoid any extra keys.[1][2][4]

- Great for strict contracts and generated client types.
- If you need forward-compatibility, you can leave this as `true` or omit it.

### 6.5 Multi-step reasoning structures

Many examples show **step-by-step** reasoning captured structurally.[1][4][7]

```json
{
  "type": "object",
  "properties": {
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "explanation": { "type": "string" },
          "output": { "type": "string" }
        },
        "required": ["explanation", "output"],
        "additionalProperties": false
      }
    },
    "final_answer": { "type": "string" }
  },
  "required": ["steps", "final_answer"],
  "additionalProperties": false
}
```

This is ideal for:

- Educational apps (show reasoning).
- Debugging agents or pipelines.
- Auditing decisions.

OpenAI and Azure examples use very similar schemas to show structured math reasoning.[1][4][7]

---

## 7. Error Handling, Refusals, and Validation

### 7.1 Safety refusals in structured form

Structured Outputs ensure **refusals** also conform to the schema.[2][5]

Patterns include:

- Having a `status` enum: `"ok"` or `"refused"`.
- Pairing with `refusal_reason` when not `"ok"`.

```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["ok", "refused"]
    },
    "result": { "type": "string" },
    "refusal_reason": { "type": "string" }
  },
  "required": ["status"],
  "additionalProperties": false
}
```

Your code can then:

- Check `status`.
- Branch logic accordingly without trying to parse natural-language refusal messages.

### 7.2 Validating responses on the client

Even though the model guarantees schema adherence, it is still good practice to validate on the client when using your own schema tooling:

- **Zod** in Node.[1]
- **Pydantic** in Python.[3][6]
- **JSON Schema validators** in your language of choice.

Libraries like `openai-structured` (Python) build this in, returning already-validated Pydantic models.[3]

---

## 8. Ecosystem Integrations and Helper Libraries

### 8.1 OpenAI Cookbook

The **OpenAI Cookbook** has a dedicated “Introduction to Structured Outputs” guide, with examples in Python and JavaScript showing:[7]

- Response format schemas and `strict: true`.
- Multi-step reasoning schemas.
- How to parse and use structured responses.

### 8.2 Azure OpenAI

Azure’s **Structured Outputs** support mirrors OpenAI’s, using the same JSON Schema approach and `strict: true` semantics.[4]

The Azure docs show:

- Python and C# examples with schemas.
- Use cases like event extraction and multi-step reasoning.[4]

### 8.3 LangChain structured output support

LangChain exposes structured output as first-class via the `response_format` argument and supports multiple schema types:[6]

- Pydantic models (`BaseModel` subclasses).
- Dataclasses.
- `TypedDict`.
- Raw JSON Schema dicts.
- Union types (model chooses the best fit schema).[6]

Example (Python, Pydantic-style schema):

```python
from pydantic import BaseModel, Field
from typing import Literal
from langchain import create_agent

class MeetingAction(BaseModel):
    task: str = Field(description="Action item to perform")
    assignee: str = Field(description="Person responsible for the task")
    priority: Literal["low", "medium", "high"] = Field(description="Priority level")

agent = create_agent(
    model="gpt-5",
    tools=[],
    response_format=MeetingAction
)

result = agent.invoke({
    "messages": [        {"role": "user", "content": "Sarah needs to update the project timeline as soon as possible"}
    ]
})

structured = result["structured_response"]
```

LangChain handles schema construction, validation, and returning a typed result.[6]

### 8.4 `openai-structured` (Python)

The `openai-structured` library focuses specifically on OpenAI Structured Outputs with Pydantic:[3]

- Maps Pydantic models to JSON Schema automatically.
- Validates responses and returns typed models.
- Supports streaming and non-streaming APIs.
- Adds robust error handling and buffer management.[3]

This is useful if you want deep integration with Pydantic and do not need a full agent framework like LangChain.

### 8.5 Betalgo.OpenAI (.NET)

The Betalgo.OpenAI client library includes Structured Outputs support and documentation:[5]

- Guarantees adherence to JSON Schema.
- Highlights benefits like reliable type safety, explicit refusals, and simpler prompting.[5]

This is particularly helpful for .NET developers who want first‑class structured responses.

---

## 9. Practical Design Patterns & Use Cases

### 9.1 Data extraction / ETL

Example: extracting contact information from free-form text.

Schema:

```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string" },
    "email": { "type": "string" },
    "phone": { "type": "string" },
    "company": { "type": "string" }
  },
  "required": ["name"],
  "additionalProperties": false
}
```

Use cases:

- CRM enrichment.
- Invoice parsing.
- Support ticket structuring.

### 9.2 Agent workflows and tool orchestration

Using Structured Outputs for tool arguments ensures that:

- Router agents get a clear, structured description of what to do.
- Each tool invocation is valid by schema, reducing runtime failures.[2][4][6]

Example: multi-step agent that:

1. Classifies a user inquiry into intent.
2. Based on intent, calls one of several tools using strict schemas.
3. Aggregates results into a structured final output with reasoning steps.

### 9.3 Content generation pipelines

You can use structured outputs to create multi-part content:

- Title, subtitle, outline, sections, metadata.
- SEO fields: target keywords, audience, reading level.

Example schema skeleton:

```json
{
  "type": "object",
  "properties": {
    "title": { "type": "string" },
    "slug": { "type": "string" },
    "meta_description": { "type": "string" },
    "keywords": {
      "type": "array",
      "items": { "type": "string" }
    },
    "outline": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "heading": { "type": "string" },
          "summary": { "type": "string" }
        },
        "required": ["heading", "summary"],
        "additionalProperties": false
      }
    }
  },
  "required": ["title", "outline"],
  "additionalProperties": false
}
```

### 9.4 Evaluation & grading frameworks

Define schemas for:

- Rubrics.
- Score breakdowns.
- Explanations and suggestions.

Example:

```json
{
  "type": "object",
  "properties": {
    "score": { "type": "number", "minimum": 0, "maximum": 10 },
    "criteria": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "score": { "type": "number", "minimum": 0, "maximum": 10 },
          "feedback": { "type": "string" }
        },
        "required": ["name", "score"],
        "additionalProperties": false
      }
    },
    "overall_feedback": { "type": "string" }
  },
  "required": ["score", "criteria"],
  "additionalProperties": false
}
```

This is ideal for automatic grading, QA evaluations, and alignment checks.

---

## 10. Common Pitfalls and Best Practices

### 10.1 Overly rigid schemas

If you make everything required and disallow additional properties everywhere, you might:

- Make the contract hard to evolve.
- Force the model into awkward behavior for borderline inputs.

**Best practice:** keep the core minimal and stable; use optional fields and nested objects to isolate changeable areas.

### 10.2 Under-specified schemas

If your schema is too loose (e.g. `type: "object"` with no `properties`), you lose structured-output benefits.

**Best practice:** specify:

- Types for each field.
- `required` for core fields.
- `enum` for classification-like fields.
- `additionalProperties: false` where you need strictness.

### 10.3 Mixing natural language parsing with structured outputs

Do not rely on parsing the text of the structured fields if you can encode structure directly:

- Prefer an array of objects over a comma-separated string.
- Prefer `enum` and typed fields over open-ended text where discrete labels are needed.

### 10.4 Forgetting downstream consumer constraints

Design the schema with:

- Database schema.
- Frontend interfaces.
- Analytics pipelines.

in mind, so that your structured output slots cleanly into your existing infrastructure.

---

## 11. Key Documentation & Learning Resources

Below is a curated list of **high‑value resources** to go deeper. You can search for these by name:

- **OpenAI Platform Docs – Structured Outputs**  
  Official guide explaining how to enable Structured Outputs, with examples for JSON Schema, Zod helpers, and response_format usage.[1]

- **OpenAI Blog – “Introducing Structured Outputs in the API”**  
  High-level overview, motivations, and differences from JSON mode, plus function calling integration details and example schemas.[2]

- **OpenAI Cookbook – “Introduction to Structured Outputs”**  
  Practical examples in Python/JS showing how to use `strict: true`, response_format, and multi-step reasoning schemas.[7]

- **Azure OpenAI – “How to use structured outputs with Azure OpenAI”**  
  Azure-specific documentation showing similar patterns with Python and C#, especially useful for Azure environments.[4]

- **LangChain Docs – Structured Output**  
  Shows how to use structured outputs with Pydantic, dataclasses, TypedDict, JSON Schema, and union types in agent workflows.[6]

- **`openai-structured` Documentation**  
  Python library that wraps OpenAI Structured Outputs with Pydantic integration, streaming, and error handling.[3]

- **Betalgo.OpenAI GitHub Wiki – Structured Outputs**  
  .NET-focused guide for using Structured Outputs with the Betalgo OpenAI client, including benefits and examples.[5]

- **YouTube – “OpenAI Structured Output – All You Need to Know”**  
  Video walkthrough explaining structured output concepts, examples, and nested data structures.[8]

- **vLLM Docs – Structured Outputs**  
  If you work with vLLM, their docs show how to generate structured outputs using xgrammar or guidance backends.[9]

---

## Conclusion

Very detailed structured outputs in OpenAI enable you to treat LLMs as **strongly typed, schema-respecting components** rather than unpredictable text generators. By:

- Defining precise JSON Schemas (or typed models),
- Enabling `strict: true` via response formats or tools,
- Integrating with ecosystem helpers like Zod, Pydantic, LangChain, and specialized libraries,

you can build **robust, production-grade** workflows for data extraction, agents, reasoning, evaluation, and complex content generation with far fewer parsing headaches.

Start small: define a simple schema for one task, enable Structured Outputs, and then evolve toward more complex nested schemas as your application demands grow. The resources listed above provide concrete examples and patterns to follow as you scale.