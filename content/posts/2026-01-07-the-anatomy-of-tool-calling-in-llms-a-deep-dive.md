---
title: "The Anatomy of Tool Calling in LLMs: A Deep Dive"
date: "2026-01-07T11:54:14.014"
draft: false
tags: ["LLM", "tool calling", "AI engineering", "agents", "APIs"]
---

## Introduction

Tool calling (also called **function calling** or **plugins**) is the capability that turns large language models from text predictors into **general-purpose controllers** for software.

Instead of only generating natural language, an LLM can:

- Decide **when** to call a tool (e.g., “get_weather”, “run_sql_query”)
- Decide **which** tool to call
- Construct **arguments** for that tool
- Use the **result** of the tool to continue its reasoning or response

This post is a deep dive into the **anatomy** of tool calling: the moving parts, how they interact, what can go wrong, and how to design reliable systems on top of them.

We’ll cover:

- Conceptual model: what tool calling really is under the hood  
- The **lifecycle** of a tool call in an LLM interaction  
- How schemas, prompts, and middleware work together  
- Error handling, security, and performance concerns  
- Concrete implementation patterns in Python and JavaScript  

If you’re building agentic systems, workflows, or “AI features” that integrate with your stack, understanding this anatomy is essential.

---

## 1. What Is Tool Calling, Really?

At a high level, tool calling is:

> A protocol for letting an LLM **propose structured actions** that your code then **validates, executes, and feeds back** into the conversation.

You can think of it as a **contract** between:

- The **LLM** (planner / reasoner)
- Your **tools** (actual capabilities / APIs)
- The **orchestrator** (middleware that glues them together)

### 1.1. Tools vs. plain text

Without tools, an LLM:

- Reads: previous messages (system, user, assistant)
- Writes: more text (assistant message)

With tools, an LLM additionally:

- **Writes**: structured tool calls (e.g., JSON describing `{"name": "get_weather", "arguments": {...}}`)
- **Reads**: tool results injected back into the conversation (e.g., “tool response: { … }”)

### 1.2. In-band vs. API-native tool calling

There are two common patterns:

1. **API-native tool calling** (e.g., OpenAI `tools`, Anthropic `tool_use`):
   - Tool definitions are passed as structured JSON
   - The LLM returns structured tool call objects
   - The client library helps orchestrate the loop

2. **In-band tool calling** (prompt-only / custom protocol):
   - Tool descriptions are written into the prompt as text
   - The LLM is instructed to output special JSON or markers
   - Your code parses that text, runs tools, and re-prompts

Functionally they’re similar; the difference is how much structure the **API** itself enforces for you.

---

## 2. The Tool Calling Lifecycle

Every tool call passes through a common lifecycle, even if the implementation details differ:

1. **Context preparation**
   - System and user messages
   - Tool definitions & capabilities
   - Optional planning instructions

2. **Decision phase**
   - LLM decides whether to call a tool
   - If yes, which tool(s) and in what order

3. **Argument construction**
   - LLM generates structured arguments for the chosen tool(s)
   - Middleware validates, coerces, or rejects invalid arguments

4. **Execution**
   - Your code executes the tool against real systems
   - Handles errors, timeouts, side effects

5. **Observation injection**
   - Results (success or failure) are turned into “tool result” messages
   - Fed back into the model as context

6. **Continuation**
   - LLM uses those observations to:
     - Produce a final user-facing answer, or
     - Plan additional tool calls (iterative / agent loops)

Let’s unpack each part.

---

## 3. Defining Tools: Schemas and Contracts

Tools are **functions with metadata**.

### 3.1. Core metadata

Typical fields:

- `name`: Unique identifier, stable over time  
- `description`: Natural language explanation of what it does and when to use it  
- `parameters`: JSON schema describing arguments and types  
- (Sometimes) `returns`: JSON schema for the result

For example, in OpenAI’s tool schema:

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get the current weather for a given city.",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {
          "type": "string",
          "description": "City name, e.g., 'San Francisco'"
        },
        "units": {
          "type": "string",
          "enum": ["metric", "imperial"],
          "description": "Units for temperature"
        }
      },
      "required": ["city"],
      "additionalProperties": false
    }
  }
}
```

This schema acts as both:

- A **typing contract** for your implementation
- A **teaching tool** for the model about how to use it

### 3.2. Schema design best practices

To get reliable tool usage:

- **Be specific** in descriptions: when to use the tool, and when not to
- Use **enums** and **constraints** where possible:
  - Avoid free-form strings for things that are really categories
- Add **examples** in descriptions:
  - “Example: for a user asking about ‘today’s weather in Berlin’, call this tool.”
- Set `additionalProperties: false`:
  - Reduces hallucinated arguments

### 3.3. Tool namespaces and grouping

As systems grow, you’ll have many tools. Consider:

- Grouping related tools (e.g., `calendar_`, `email_`)  
- Using names that reflect responsibility boundaries:
  - `contacts_search` vs. `search_contacts_and_also_email_them`  
- Having a smaller set of **high-quality, well-described tools** beats dozens of vague ones

---

## 4. Decision Phase: Should the Model Call a Tool?

The LLM’s first job is to **decide whether a tool is needed** and, if so, which one(s).

### 4.1. Decision signals

The model uses:

- The **user request**  
- The **tool descriptions** in context  
- Any **system instructions** (e.g., “prefer tools when external data is needed”)

Modern APIs expose this as options like:

- `tool_choice: "auto"` (let the model decide)  
- `tool_choice: { "type": "function", "function": { "name": "get_weather" } }` (force a specific tool)  
- `tool_choice: "none"` (prohibit tools)

### 4.2. Controlling tool usage

Patterns you might use:

- **“Always use tools”** mode:
  - Wrap the user query and force a tool, then do a second LLM call to summarize results
- **“Prefer tools but allow fallback”** mode:
  - Default `auto`, but warn the model not to invent data if no suitable tool exists
- **Tool routing**:
  - Pre-classify the query into high-level domains, then only expose the relevant subset of tools

> Key point: The decision is still **probabilistic**; you shape it with prompts, schema, and `tool_choice`, but you don’t program it like a deterministic rules engine.

---

## 5. Argument Construction: How LLMs Build Calls

Once a tool is chosen, the LLM generates the arguments according to your schema.

### 5.1. How models “see” your schema

From the model’s perspective, your schema is:

- Text describing:
  - Field names
  - Types
  - Descriptions
  - Required/optional behavior

Even if it’s sent in a structured parameter (e.g., `tools`), the model effectively ingests it as **tokenized text**.

That’s why:

- Good naming (`start_date` vs. `sd1`) helps  
- Descriptions that include **user-intent mapping** help (“Use `start_date` when the user’s trip begins”)  
- Overly-nested or generic schemas (“data1”, “data2”) hurt performance

### 5.2. Typical failure modes

Common argument-generation issues:

- Incorrect types (string instead of number)  
- Missing required fields  
- Hallucinated fields not in schema  
- Poor parsing of dates, times, or IDs  
- Overspecified arguments (e.g., adding constraints your backend doesn’t support)

You mitigate these in the **middleware**.

### 5.3. Validation in middleware

Your orchestrator should:

- **Validate** arguments against the JSON schema  
- **Coerce** common formats where safe (e.g., `"42"` → `42`)  
- **Reject** invalid calls and send an error back to the model

Example (Python):

```python
from jsonschema import validate, ValidationError

def validate_tool_args(tool_schema, args):
    try:
        validate(instance=args, schema=tool_schema["parameters"])
        return args, None
    except ValidationError as e:
        return None, str(e)
```

If invalid, you convert the error into a tool result message:

```json
{
  "error": "ValidationError: 'Berlin' is not of type 'integer' for field 'user_id'"
}
```

And feed that back into the model so it can correct itself.

---

## 6. Execution: Running the Actual Tool

Once you have a validated tool call, your code executes the corresponding function.

### 6.1. Execution layer responsibilities

The execution layer should:

- Map `tool.name` → **actual function** or service  
- Handle **timeouts** and **cancellation**  
- Catch and classify errors:
  - Transient (timeouts, network)
  - Permanent (invalid business logic, permission denied)
- Avoid dangerous side effects unless:
  - Explicitly allowed by the user
  - Properly guarded (auth, confirmation, limits)

### 6.2. Idempotency and side effects

For tools that **change state** (e.g., “send_email”, “charge_card”):

- Consider including **idempotency keys** in arguments  
- Ask the LLM to:
  - Confirm irreversible actions
  - Provide clear reasons for performing the action
- Log all calls with:
  - User ID / session
  - Tool name
  - Arguments
  - Result / error

You can even design tools as:

- **Safe preview tools** (e.g., `preview_email`)  
- **Commit tools** (e.g., `send_email`)  

and require explicit transitions controlled by the model or user.

---

## 7. Observation Injection: Feeding Results Back

After the tool runs, its result needs to become **part of the conversation**.

### 7.1. Tool result messages

Most APIs model this as an intermediate message type, e.g.:

- `role: "tool"` with `tool_call_id` and `content`  
- `role: "assistant"` with `tool_use` / `tool_result` blocks (Anthropic-style)

Example (conceptual):

```json
[
  { "role": "user", "content": "What's the weather in Berlin right now?" },
  {
    "role": "assistant",
    "tool_calls": [
      {
        "id": "call_1",
        "name": "get_weather",
        "arguments": { "city": "Berlin", "units": "metric" }
      }
    ]
  },
  {
    "role": "tool",
    "tool_call_id": "call_1",
    "content": {
      "temp_c": 21,
      "description": "Sunny",
      "humidity": 40
    }
  }
]
```

The model then sees the tool result as part of its context in the next turn.

### 7.2. Formatting results

You have design choices:

- Return **raw data structures** (JSON):
  - Good for chaining into more tools / reasoning
- Return **user-ready strings**:
  - Good if the model just needs to present them
- Return both:
  - `{"raw": {...}, "summary": "Sunny, 21°C in Berlin"}`

For complex tools (e.g., SQL queries, multi-step operations), it’s often best to:

- Return **raw structured data**, and
- Let the **LLM summarize** for the user in the next step

---

## 8. Continuation and Agent Loops

After a tool result is injected, the model must decide:

- Should it make **more tool calls**?
- Or produce a **final answer**?

### 8.1. Single-shot vs. multi-step patterns

Two broad patterns:

1. **Single-shot tool call**:
   - A single LLM call decides on a tool, builds arguments, and then you:
     - Execute the tool
     - Run a second LLM call to summarize results
   - No recursive planning or loops

2. **Multi-step agent loop**:
   - LLM iteratively:
     - Plans tool usage
     - Executes tools
     - Reflects on results
   - Continues until stopping condition (max steps, explicit “done”)

### 8.2. Architecting the loop

A typical loop:

```python
MAX_STEPS = 5
messages = [{"role": "user", "content": user_input}]

for step in range(MAX_STEPS):
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        tools=TOOLS
    )

    assistant_msg = response.choices[0].message
    messages.append(assistant_msg)

    tool_calls = assistant_msg.tool_calls
    if not tool_calls:
        # No more tools; this is the final answer
        break

    for call in tool_calls:
        tool_name = call.function.name
        tool_args = json.loads(call.function.arguments)
        result = execute_tool(tool_name, tool_args)

        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result)
        })
```

You then present the latest assistant message that **doesn’t** contain tool calls as the final answer.

### 8.3. Stopping conditions

Common strategies:

- Max tool-call steps per user request (to prevent loops)  
- Explicit “I’m done” marker:
  - Instruct model to end with `"status": "done"` or a phrase like “Final answer:”  
- External constraints:
  - Time budget, token budget, or cost ceilings

---

## 9. Concrete Examples (Python & JavaScript)

### 9.1. Python: OpenAI-style tool calling

```python
import json
from openai import OpenAI

client = OpenAI()

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g., 'Berlin'"
                    },
                    "units": {
                        "type": "string",
                        "enum": ["metric", "imperial"],
                        "description": "Units for temperature"
                    }
                },
                "required": ["city"],
                "additionalProperties": False
            }
        }
    }
]

def get_weather(city: str, units: str = "metric"):
    # Stub implementation; replace with real API
    return {
        "city": city,
        "units": units,
        "temp": 21,
        "description": "Sunny",
    }

def execute_tool(name, args):
    if name == "get_weather":
        return get_weather(**args)
    raise ValueError(f"Unknown tool: {name}")

def chat_with_tools(user_input: str):
    messages = [{"role": "user", "content": user_input}]

    for _ in range(5):  # max 5 tool iterations
        resp = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            tools=tools
        )

        msg = resp.choices[0].message
        messages.append(msg)

        tool_calls = msg.tool_calls or []
        if not tool_calls:
            # Final answer
            return msg.content

        # Execute each tool call
        for call in tool_calls:
            tool_name = call.function.name
            tool_args = json.loads(call.function.arguments)
            result = execute_tool(tool_name, tool_args)

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result)
            })

# Example usage
if __name__ == "__main__":
    answer = chat_with_tools("What's the weather in Berlin?")
    print(answer)
```

### 9.2. JavaScript: Manual in-band protocol

For providers without native tool support, you can roll your own protocol.

```js
import OpenAI from "openai";
const client = new OpenAI();

const TOOL_SPEC = `
You can call tools using the following JSON format on a single line:

{"tool": "get_weather", "args": {"city": "Berlin", "units": "metric"}}

If you are answering normally, do NOT use this JSON. Only use it when you need a tool.
Available tools:
- get_weather(city: string, units: "metric" | "imperial"): Get current weather.
`;

async function getWeather({ city, units = "metric" }) {
  // Replace with real API call
  return {
    city,
    units,
    temp: 21,
    description: "Sunny"
  };
}

async function callLLM(messages) {
  const completion = await client.chat.completions.create({
    model: "gpt-4.1-mini",
    messages
  });
  return completion.choices[0].message.content;
}

function tryParseToolCall(text) {
  // Simple heuristic: look for a JSON object line
  const match = text.match(/\{.*"tool"\s*:\s*".*".*\}/);
  if (!match) return null;
  try {
    return JSON.parse(match[0]);
  } catch {
    return null;
  }
}

async function chat(userInput) {
  let messages = [
    { role: "system", content: TOOL_SPEC },
    { role: "user", content: userInput }
  ];

  for (let i = 0; i < 5; i++) {
    const response = await callLLM(messages);
    const toolCall = tryParseToolCall(response);

    if (!toolCall) {
      // No tool; final answer
      return response;
    }

    const { tool, args } = toolCall;
    let result;

    if (tool === "get_weather") {
      result = await getWeather(args);
    } else {
      result = { error: `Unknown tool: ${tool}` };
    }

    messages.push({ role: "assistant", content: response });
    messages.push({
      role: "user",
      content: `Tool result: ${JSON.stringify(result)}`
    });
  }
}

chat("What's the weather in Berlin?").then(console.log);
```

This demonstrates the same lifecycle—decision, arguments, execution, observation—but purely via prompt instructions and custom parsing.

---

## 10. Reliability and Error Handling

Tool calling increases capability, but also **failure modes**. You should treat tool integration as a distributed system problem, not a pure ML problem.

### 10.1. Classes of errors

1. **LLM errors**
   - Calls the wrong tool  
   - Omits required arguments  
   - Misinterprets units or formats  

2. **Tool errors**
   - API timeouts  
   - Validation failures  
   - Permission issues  

3. **Orchestrator errors**
   - Parsing failures  
   - Schema mismatches  
   - Infinite loops or runaway tool calls  

### 10.2. Strategies

- **Strict schema validation** + clear error messages back to the model  
- **Retries** with backoff for transient tool failures  
- **Guardrails**:
  - Max tool calls per interaction  
  - Token / time budget  
- **Fallback paths**:
  - “I couldn’t access the calendar service, but here’s what you can try manually.”

### 10.3. Self-correction loops

You can sometimes let the model correct its own mistakes:

1. On validation error, send a tool result like:
   ```json
   { "error": "ValidationError: 'tomorrow morning' is not an ISO date. Please provide an ISO date like '2026-01-09'." }
   ```
2. The LLM often learns to re-call the same tool with corrected arguments.

Just be careful to:

- Distinguish **user-facing** vs. **model-facing** error messages  
- Not leak sensitive backend details in error strings

---

## 11. Security and Governance

A tool is effectively **remote code execution** controlled by a stochastic model. Treat it accordingly.

### 11.1. Threats

- **Prompt injection**:
  - Malicious content tries to coerce the model into abusing tools
- **Escalation of privilege**:
  - Model tries to access tools beyond the user’s permissions
- **Data exfiltration**:
  - Model uses tools to read sensitive data and exfiltrate it through the answer
- **Cost and resource abuse**:
  - Infinite loops or expensive tool calls

### 11.2. Defenses

- **Per-user tool authorization**:
  - Don’t just expose all tools to all sessions
  - Build a mapping: user → allowed tools → scopes
- **Parameter-level checks**:
  - Validate that `user_id` in tool args matches the authenticated user
- **Sandbox & rate-limit tools**:
  - Especially anything that writes or accesses external networks
- **Robust system prompts**:
  - Make the model treat untrusted content as untrusted
  - Explicitly forbid following instructions from tools or external pages that override your system-level rules
- **Explainability and logging**:
  - Log all tool calls and responses
  - Provide admin tooling to inspect suspicious sessions

---

## 12. Performance Considerations

Tool calling can easily multiply latency and cost if not designed carefully.

### 12.1. Latency

Drivers of latency:

- Multiple LLM rounds (plan → tool → reflect → answer)  
- High-latency tools (network calls, DB queries)  
- Serialization overhead (large tool results)

Mitigations:

- **Parallel tool calls** when possible:
  - Execute multiple independent tool calls in the same step  
- **Limit result size**:
  - Paginate or sample large results before returning to the model  
- **Use smaller models** for simple routing / extraction:
  - Reserve large models for complex reasoning

### 12.2. Cost

Cost can explode with:

- Many tool steps per interaction  
- Large-context replay of full tool results  
- Use of top-tier models for trivial operations

Mitigations:

- **Summarize tool results** before reinserting them:
  - “Summarize the 1000-row SQL result into key insights.”  
- **Hybrid architectures**:
  - Use cheaper models for:
    - Intent detection
    - Entity extraction
    - Simple tools
- **Caching**:
  - Cache tool results for repeated queries  
  - Cache LLM outputs for frequent patterns

---

## 13. Testing and Evaluation

To move beyond demos, you need systematic testing of tool calling behavior.

### 13.1. Types of tests

- **Unit tests**:
  - Tool implementation and argument validation  
- **Contract tests**:
  - Ensure `parameters` schema matches actual function signature  
- **Behavioral tests**:
  - Given a user input, does the model:
    - Choose the right tool?
    - Fill arguments correctly?
    - Avoid unsafe actions?

### 13.2. Synthetic and real data

- Create **synthetic scenarios**:
  - “User asks to schedule a meeting during blocked hours”  
  - “User without permission requests admin-only report”
- Log **real traffic**, label outcomes, and:
  - Measure tool selection accuracy
  - Identify common failure patterns  
  - Iterate on tool descriptions and prompts

---

## 14. Summary and Key Takeaways

Tool calling turns LLMs into **orchestrators of software**, but it’s not magic. It’s a protocol with defined moving parts:

- **Schemas and descriptions** teach the model what tools exist and how to use them  
- The model’s job is to:
  - Decide **if** and **which** tool to call
  - Construct **arguments**
- Your middleware’s job is to:
  - Validate, execute, and log tool calls
  - Inject results back as **observations**
  - Control loops, errors, and security
- Reliability comes from:
  - Strong schemas
  - Clear system prompts
  - Strict validation and authorization
  - Thoughtful error handling and evaluation

If you treat tool calling as a **distributed system interface** rather than a black-box “agent”, you can build AI features that are both powerful and trustworthy.

---

## Further Resources

If you want to go deeper, explore:

- Official tool/function calling docs from major providers (OpenAI, Anthropic, etc.)  
- Papers and blog posts on:
  - ReAct (Reasoning + Acting) patterns  
  - Agent architectures and planning strategies  
- Libraries / frameworks:
  - LangChain, LlamaIndex, Semantic Kernel, and others that provide higher-level abstractions over tool calling  

Use these as **reference implementations**, but always understand and control the underlying anatomy described here—that’s where reliability and safety truly live.