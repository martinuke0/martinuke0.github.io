---
title: "Agentic Workflows in 2026: A Zero-to-Hero Guide to Building Autonomous AI Systems"
date: "2026-03-03T11:28:43Z"
draft: false
tags: ["AI", "Agentic-Workflows", "LLM", "Automation", "Python"]
description: "A comprehensive guide to building agentic workflows using modern LLM frameworks and orchestration patterns. Learn to create autonomous AI systems that plan, execute, and adapt through practical code examples and real-world architectures."
---

## Table of Contents

- [Introduction](#introduction)
- [Understanding Agentic Workflows: Core Concepts](#understanding-agentic-workflows-core-concepts)
- [Setting Up Your Development Environment](#setting-up-your-development-environment)
- [Building Your First Agent: The ReAct Pattern](#building-your-first-agent-the-react-pattern)
- [Tool Integration and Function Calling](#tool-integration-and-function-calling)
- [Memory Systems for Stateful Agents](#memory-systems-for-stateful-agents)
- [Multi-Agent Orchestration Patterns](#multi-agent-orchestration-patterns)
- [Error Handling and Reliability Patterns](#error-handling-and-reliability-patterns)
- [Observability and Debugging Agentic Systems](#observability-and-debugging-agentic-systems)
- [Production Deployment Strategies](#production-deployment-strategies)
- [Advanced Patterns: Graph-Based Workflows](#advanced-patterns-graph-based-workflows)
- [Security and Safety Considerations](#security-and-safety-considerations)
- [Performance Optimization Techniques](#performance-optimization-techniques)
- [Conclusion](#conclusion)
- [Top 10 Resources](#top-10-resources)

## Introduction

Agentic workflows represent the next evolution in AI application development. Unlike traditional request-response systems, agents autonomously plan, execute, and adapt their actions to achieve complex goals. In 2026, the landscape has matured significantly—LLM providers offer robust function calling, frameworks have standardized on proven patterns, and production deployments are increasingly common.

This tutorial takes you from fundamental concepts to production-ready implementations. You'll build multiple agent systems, from simple ReAct loops to sophisticated multi-agent orchestrations. We'll use modern frameworks like LangGraph, LlamaIndex Workflows, and OpenAI's Assistants API, focusing on patterns that work reliably in production environments.

By the end, you'll understand how to design autonomous systems that handle real-world complexity: tool usage, memory management, error recovery, and multi-step reasoning. You'll have working code for common patterns and the knowledge to architect custom solutions. Whether you're building research assistants, data analysis pipelines, or customer service automation, this guide provides the foundation you need.

## Understanding Agentic Workflows: Core Concepts

Agentic workflows differ fundamentally from traditional AI applications. Instead of predicting the next token or classifying input, agents operate in a perception-action loop: they observe their environment, decide on actions, execute them, and adjust based on results.

### The Agent Loop

At its core, an agent follows this cycle:

```python
# Pseudocode for the fundamental agent loop
while not task_complete:
    # 1. Perceive: Gather current state
    state = observe_environment()
    
    # 2. Think: Decide what to do next
    action = llm.decide(state, goal, history)
    
    # 3. Act: Execute the chosen action
    result = execute_action(action)
    
    # 4. Reflect: Update understanding
    history.append((action, result))
    task_complete = evaluate_completion(result, goal)
```

This simple loop enables surprisingly complex behavior. The agent isn't following a predetermined script—it's continuously adapting based on what it observes.

### Key Components

Every agentic system comprises four essential elements:

```python
from typing import Protocol, List, Dict, Any
from dataclasses import dataclass

@dataclass
class AgentState:
    """Current state of the agent's execution"""
    goal: str
    history: List[Dict[str, Any]]
    context: Dict[str, Any]
    iteration: int

class Tool(Protocol):
    """Tools agents can use to interact with the world"""
    def execute(self, **kwargs) -> Any:
        """Execute the tool with given parameters"""
        ...
    
    def describe(self) -> Dict[str, Any]:
        """Return tool description for LLM"""
        ...

class Memory(Protocol):
    """Storage for agent experience"""
    def store(self, key: str, value: Any) -> None:
        ...
    
    def retrieve(self, query: str, k: int = 5) -> List[Any]:
        ...

class Planner:
    """Decides what action to take next"""
    def __init__(self, llm, tools: List[Tool]):
        self.llm = llm
        self.tools = tools
    
    def next_action(self, state: AgentState) -> Dict[str, Any]:
        """Given current state, decide next action"""
        tool_descriptions = [t.describe() for t in self.tools]
        prompt = self._build_prompt(state, tool_descriptions)
        return self.llm.generate(prompt)
```

### ReAct: Reasoning and Acting

The ReAct (Reasoning and Acting) pattern emerged as a breakthrough in 2022 and remains foundational in 2026. Agents alternate between reasoning (thinking about what to do) and acting (executing tools):

```python
# ReAct prompting template
REACT_PROMPT = """
You are an agent solving tasks step by step.
For each step, you must:
1. Thought: Reason about what to do next
2. Action: Choose a tool and its inputs
3. Observation: See the result

Available tools:
{tool_descriptions}

Current task: {task}
History:
{history}

Thought:"""

# Example ReAct trace
trace = """
Thought: I need to find the current weather in Tokyo
Action: weather_api(city="Tokyo")
Observation: Temperature: 18°C, Conditions: Partly cloudy

Thought: Now I should convert this to Fahrenheit for the user
Action: calculator(expression="18 * 9/5 + 32")
Observation: 64.4

Thought: I have all the information needed
Action: finish(answer="The weather in Tokyo is 64.4°F and partly cloudy")
"""
```

This explicit reasoning chain dramatically improves success rates on complex tasks by making the agent's thinking transparent and debuggable.

## Setting Up Your Development Environment

Let's establish a production-quality development environment for building agentic workflows.

### Core Dependencies

```bash
# Create a new Python 3.11+ environment
python -m venv agentic-env
source agentic-env/bin/activate  # On Windows: agentic-env\Scripts\activate

# Install core dependencies
pip install openai anthropic langchain langgraph pydantic httpx tenacity

# Observability and monitoring
pip install langsmith wandb prometheus-client

# Vector stores and memory
pip install chromadb qdrant-client redis

# Development tools
pip install python-dotenv pytest pytest-asyncio black ruff mypy
```

### Project Structure

```bash
agentic-workflows/
├── .env                    # API keys and configuration
├── pyproject.toml         # Project metadata
├── src/
│   ├── agents/            # Agent implementations
│   │   ├── __init__.py
│   │   ├── base.py        # Base agent classes
│   │   ├── react.py       # ReAct agent
│   │   └── planner.py     # Planning agent
│   ├── tools/             # Tool definitions
│   │   ├── __init__.py
│   │   ├── web_search.py
│   │   ├── calculator.py
│   │   └── filesystem.py
│   ├── memory/            # Memory systems
│   │   ├── __init__.py
│   │   ├── vector.py
│   │   └── conversation.py
│   └── orchestration/     # Multi-agent coordination
│       ├── __init__.py
│       └── coordinator.py
├── tests/                 # Test suite
│   ├── test_agents.py
│   └── test_tools.py
└── examples/              # Example workflows
    ├── research_assistant.py
    └── data_analyst.py
```

### Configuration Management

```python
# src/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    """Application configuration from environment"""
    
    # LLM API Keys
    openai_api_key: str
    anthropic_api_key: str | None = None
    
    # Model Selection
    default_model: str = "gpt-4-turbo-2024-04-09"
    fast_model: str = "gpt-3.5-turbo"
    
    # Agent Configuration
    max_iterations: int = 15
    temperature: float = 0.1
    timeout_seconds: int = 300
    
    # Memory Configuration
    vector_db_path: str = "./data/vectors"
    redis_url: str = "redis://localhost:6379"
    
    # Observability
    langsmith_api_key: str | None = None
    enable_tracing: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()
```

### Base Agent Infrastructure

```python
# src/agents/base.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class Message:
    """Individual message in agent conversation"""
    role: str  # 'user', 'assistant', 'system', 'tool'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentResult:
    """Result of agent execution"""
    success: bool
    output: Any
    messages: List[Message]
    tool_calls: List[Dict[str, Any]]
    iterations: int
    total_tokens: int
    error: Optional[str] = None

class BaseAgent(ABC):
    """Abstract base class for all agents"""
    
    def __init__(
        self,
        name: str,
        llm_client: Any,
        tools: List[Any],
        max_iterations: int = 15,
        verbose: bool = False
    ):
        self.name = name
        self.llm = llm_client
        self.tools = {tool.name: tool for tool in tools}
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.messages: List[Message] = []
        
    @abstractmethod
    async def run(self, task: str, context: Dict[str, Any] = None) -> AgentResult:
        """Execute the agent on a given task"""
        pass
    
    def _log(self, message: str, level: str = "info"):
        """Internal logging"""
        if self.verbose:
            print(f"[{self.name}] {message}")
        getattr(logger, level)(f"{self.name}: {message}")
    
    def _add_message(self, role: str, content: str, **metadata):
        """Add message to conversation history"""
        msg = Message(role=role, content=content, metadata=metadata)
        self.messages.append(msg)
        return msg
```

This foundation provides type safety, observability, and a consistent interface for all agent implementations.

## Building Your First Agent: The ReAct Pattern

Let's implement a fully functional ReAct agent from scratch.

### Tool Definition System

First, we need a robust way to define and execute tools:

```python
# src/tools/base.py
from typing import Callable, Any, Dict, Optional
from pydantic import BaseModel, Field
from inspect import signature, Parameter
import json

class ToolParameter(BaseModel):
    """Schema for a single tool parameter"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None

class ToolSchema(BaseModel):
    """Complete schema for a tool"""
    name: str
    description: str
    parameters: list[ToolParameter]
    
    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format"""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description
            }
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }

class Tool:
    """Base tool class with automatic schema generation"""
    
    def __init__(
        self,
        name: str,
        description: str,
        func: Callable,
        param_descriptions: Optional[Dict[str, str]] = None
    ):
        self.name = name
        self.description = description
        self.func = func
        self.schema = self._build_schema(func, param_descriptions or {})
    
    def _build_schema(self, func: Callable, param_desc: Dict[str, str]) -> ToolSchema:
        """Auto-generate schema from function signature"""
        sig = signature(func)
        parameters = []
        
        for param_name, param in sig.parameters.items():
            # Map Python types to JSON schema types
            type_mapping = {
                int: "integer",
                float: "number",
                str: "string",
                bool: "boolean",
                list: "array",
                dict: "object"
            }
            
            param_type = type_mapping.get(param.annotation, "string")
            required = param.default == Parameter.empty
            
            parameters.append(ToolParameter(
                name=param_name,
                type=param_type,
                description=param_desc.get(param_name, f"Parameter {param_name}"),
                required=required,
                default=param.default if not required else None
            ))
        
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=parameters
        )
    
    def execute(self, **kwargs) -> Any:
        """Execute the tool with given parameters"""
        try:
            result = self.func(**kwargs)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

# Example tool implementations
def calculator(expression: str) -> float:
    """Evaluate a mathematical expression"""
    # Safe evaluation - only allow math operations
    allowed = set("0123456789+-*/()., ")
    if not all(c in allowed for c in expression):
        raise ValueError("Invalid characters in expression")
    return eval(expression)

def web_search(query: str, num_results: int = 5) -> list[Dict[str, str]]:
    """Search the web for information (mock implementation)"""
    # In production, integrate with Brave, Serper, or Tavily
    return [
        {
            "title": f"Result {i+1} for '{query}'",
            "url": f"https://example.com/{i}",
            "snippet": f"Mock search result snippet {i+1}"
        }
        for i in range(num_results)
    ]

# Create tool instances
calculator_tool = Tool(
    name="calculator",
    description="Evaluate mathematical expressions",
    func=calculator,
    param_descriptions={"expression": "Mathematical expression to evaluate"}
)

search_tool = Tool(
    name="web_search",
    description="Search the web for current information",
    func=web_search,
    param_descriptions={
        "query": "Search query string",
        "num_results": "Number of results to return (default: 5)"
    }
)
```

### ReAct Agent Implementation

Now we build the complete ReAct agent:

```python
# src/agents/react.py
from typing import Dict, Any, List, Optional
from openai import OpenAI
import json
import re
from .base import BaseAgent, AgentResult, Message

class ReActAgent(BaseAgent):
    """
    ReAct (Reasoning + Acting) agent implementation.
    Alternates between reasoning and tool execution.
    """
    
    REACT_PROMPT = """You are a helpful AI agent that solves tasks step-by-step.

For each step, follow this exact format:
Thought: [Your reasoning about what to do next]
Action: [tool_name]
Action Input: [JSON object with tool parameters]
Observation: [Tool execution result - will be filled by the system]

After receiving observations, continue thinking and acting until you can provide a final answer.

When you have the final answer, use:
Thought: I now have enough information to answer
Action: finish
Action Input: {{"answer": "your final answer here"}}

Available tools:
{tools}

Begin! Remember to think step-by-step.

Task: {task}"""
    
    def __init__(self, llm_client: OpenAI, tools: List[Any], **kwargs):
        super().__init__(
            name="ReActAgent",
            llm_client=llm_client,
            tools=tools,
            **kwargs
        )
        
    def _format_tools(self) -> str:
        """Format tool descriptions for the prompt"""
        descriptions = []
        for tool in self.tools.values():
            params = ", ".join([
                f"{p.name}: {p.type}" 
                for p in tool.schema.parameters
            ])
            descriptions.append(
                f"- {tool.name}({params}): {tool.description}"
            )
        return "\n".join(descriptions)
    
    def _parse_action(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract action and parameters from LLM response"""
        # Look for Action: and Action Input: patterns
        action_match = re.search(r'Action:\s*(\w+)', text)
        input_match = re.search(r'Action Input:\s*({.*?}|\{[^}]*\})', text, re.DOTALL)
        
        if not action_match:
            return None
        
        action_name = action_match.group(1)
        
        # Parse action input JSON
        action_input = {}
        if input_match:
            try:
                action_input = json.loads(input_match.group(1))
            except json.JSONDecodeError:
                # Try to extract key-value pairs if JSON parsing fails
                input_text = input_match.group(1)
                self._log(f"Failed to parse JSON, attempting fallback: {input_text}", "warning")
                
        return {
            "action": action_name,
            "action_input": action_input,
            "full_text": text
        }
    
    async def run(self, task: str, context: Dict[str, Any] = None) -> AgentResult:
        """Execute the ReAct loop"""
        self._log(f"Starting task: {task}")
        
        # Initialize prompt
        system_prompt = self.REACT_PROMPT.format(
            tools=self._format_tools(),
            task=task
        )
        
        conversation = [{"role": "system", "content": system_prompt}]
        tool_calls = []
        iterations = 0
        total_tokens = 0
        
        for iteration in range(self.max_iterations):
            iterations += 1
            self._log(f"Iteration {iteration + 1}/{self.max_iterations}")
            
            # Get LLM response
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo-2024-04-09",
                messages=conversation,
                temperature=0.1,
                max_tokens=1000
            )
            
            assistant_message = response.choices[0].message.content
            total_tokens += response.usage.total_tokens
            
            conversation.append({"role": "assistant", "content": assistant_message})
            self._add_message("assistant", assistant_message)
            
            if self.verbose:
                print(f"\n{assistant_message}\n")
            
            # Parse action
            action_data = self._parse_action(assistant_message)
            
            if not action_data:
                # No valid action found, prompt for continuation
                conversation.append({
                    "role": "user",
                    "content": "Please provide your next action in the correct format."
                })
                continue
            
            action_name = action_data["action"]
            action_input = action_data["action_input"]
            
            # Check for finish action
            if action_name == "finish":
                final_answer = action_input.get("answer", "Task completed")
                self._log(f"Task completed: {final_answer}")
                
                return AgentResult(
                    success=True,
                    output=final_answer,
                    messages=self.messages,
                    tool_calls=tool_calls,
                    iterations=iterations,
                    total_tokens=total_tokens
                )
            
            # Execute tool
            if action_name not in self.tools:
                observation = f"Error: Tool '{action_name}' not found. Available tools: {list(self.tools.keys())}"
            else:
                tool = self.tools[action_name]
                self._log(f"Executing {action_name} with {action_input}")
                
                result = tool.execute(**action_input)
                tool_calls.append({
                    "tool": action_name,
                    "input": action_input,
                    "result": result
                })
                
                observation = json.dumps(result, indent=2)
            
            # Add observation to conversation
            observation_text = f"Observation: {observation}"
            conversation.append({"role": "user", "content": observation_text})
            self._add_message("tool", observation, tool=action_name)
            
            if self.verbose:
                print(f"{observation_text}\n")
        
        # Max iterations reached
        return AgentResult(
            success=False,
            output=None,
            messages=self.messages,
            tool_calls=tool_calls,
            iterations=iterations,
            total_tokens=total_tokens,
            error="Maximum iterations reached without completion"
        )

# Usage example
async def main():
    from openai import OpenAI
    from src.tools.base import calculator_tool, search_tool
    
    client = OpenAI(api_key="your-api-key")
    
    agent = ReActAgent(
        llm_client=client,
        tools=[calculator_tool, search_tool],
        max_iterations=10,
        verbose=True
    )
    
    result = await agent.run(
        "What is 15% of 2,847, and what's a fun fact about that number?"
    )
    
    print(f"\nFinal Result: {result.output}")
    print(f"Iterations: {result.iterations}")
    print(f"Total Tokens: {result.total_tokens}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

This implementation demonstrates the complete ReAct pattern with proper error handling, token tracking, and conversation management.

## Tool Integration and Function Calling

Modern LLMs support native function calling, which is more reliable than prompt-based tool use. Let's implement both approaches.

### Native Function Calling with OpenAI

```python
# src/agents/function_calling_agent.py
from typing import Dict, Any, List
from openai import OpenAI
import json
from .base import BaseAgent, AgentResult

class FunctionCallingAgent(BaseAgent):
    """
    Agent using native OpenAI function calling.
    More reliable than prompt-based approaches.
    """
    
    def __init__(self, llm_client: OpenAI, tools: List[Any], **kwargs):
        super().__init__(
            name="FunctionCallingAgent",
            llm_client=llm_client,
            tools=tools,
            **kwargs
        )
        # Convert tools to OpenAI format
        self.functions = [
            tool.schema.to_openai_format() 
            for tool in self.tools.values()
        ]
    
    async def run(self, task: str, context: Dict[str, Any] = None) -> AgentResult:
        """Execute using native function calling"""
        messages = [
            {
                "role": "system",
                "content": "You are a helpful AI assistant. Use the provided functions to help answer questions."
            },
            {
                "role": "user",
                "content": task
            }
        ]
        
        tool_calls = []
        iterations = 0
        total_tokens = 0
        
        for iteration in range(self.max_iterations):
            iterations += 1
            self._log(f"Iteration {iteration + 1}")
            
            # Call LLM with function definitions
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo-2024-04-09",
                messages=messages,
                tools=self.functions,
                tool_choice="auto",  # Let model decide when to call functions
                temperature=0.1
            )
            
            total_tokens += response.usage.total_tokens
            message = response.choices[0].message
            
            # Check if there are function calls
            if not message.tool_calls:
                # No more function calls - we have final answer
                final_answer = message.content
                self._log(f"Final answer: {final_answer}")
                
                return AgentResult(
                    success=True,
                    output=final_answer,
                    messages=[Message("assistant", msg["content"]) for msg in messages],
                    tool_calls=tool_calls,
                    iterations=iterations,
                    total_tokens=total_tokens
                )
            
            # Add assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            })
            
            # Execute each function call
            for tool_call in message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                self._log(f"Calling {function_name} with {function_args}")
                
                # Execute the tool
                if function_name in self.tools:
                    result = self.tools[function_name].execute(**function_args)
                else:
                    result = {"success": False, "error": f"Unknown function: {function_name}"}
                
                tool_calls.append({
                    "tool": function_name,
                    "input": function_args,
                    "result": result
                })
                
                # Add function result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })
        
        return AgentResult(
            success=False,
            output=None,
            messages=[Message("assistant", str(msg)) for msg in messages],
            tool_calls=tool_calls,
            iterations=iterations,
            total_tokens=total_tokens,
            error="Maximum iterations reached"
        )
```

### Advanced Tool Patterns

```python
# src/tools/advanced.py
from typing import Any, Dict, List, Optional
import httpx
import json
from datetime import datetime

class APITool:
    """Generic API calling tool with retry logic"""
    
    def __init__(
        self,
        name: str,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30
    ):
        self.name = name
        self.base_url = base_url
        self.headers = headers or {}
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers=self.headers,
            timeout=timeout
        )
    
    async def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute GET request"""
        try:
            response = await self.client.get(endpoint, params=params)
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute POST request"""
        try:
            response = await self.client.post(endpoint, json=data)
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

class DatabaseTool:
    """SQL database interaction tool with safety checks"""
    
    def __init__(self, connection_string: str, read_only: bool = True):
        self.connection_string = connection_string
        self.read_only = read_only
        # In production, use SQLAlchemy or similar
        
    def query(self, sql: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute SQL query with safety checks"""
        # Validate query is read-only if required
        if self.read_only:
            sql_lower = sql.lower().strip()
            if any(keyword in sql_lower for keyword in ['insert', 'update', 'delete', 'drop', 'alter']):
                return {
                    "success": False,
                    "error": "Write operations not allowed in read-only mode"
                }
        
        try:
            # Execute query (placeholder - implement actual DB logic)
            results = self._execute_query(sql, params)
            return {
                "success": True,
                "data": results,
                "row_count": len(results)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _execute_query(self, sql: str, params: Optional[Dict]) -> List[Dict]:
        """Placeholder for actual database execution"""
        return []

class FileSystemTool:
    """Sandboxed file system operations"""
    
    def __init__(self, sandbox_dir: str):
        self.sandbox_dir = sandbox_dir
        
    def read_file(self, filepath: str) -> Dict[str, Any]:
        """Read file contents (within sandbox)"""
        full_path = self._validate_path(filepath)
        if not full_path:
            return {"success": False, "error": "Path outside sandbox"}
        
        try:
            with open(full_path, 'r') as f:
                content = f.read()
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def write_file(self, filepath: str, content: str) -> Dict[str, Any]:
        """Write file contents (within sandbox)"""
        full_path = self._validate_path(filepath)
        if not full_path:
            return {"success": False, "error": "Path outside sandbox"}
        
        try:
            with open(full_path, 'w') as f:
                f.write(content)
            return {"success": True, "bytes_written": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def list_directory(self, dirpath: str = ".") -> Dict[str, Any]:
        """List directory contents"""
        import os
        full_path = self._validate_path(dirpath)
        if not full_path:
            return {"success": False, "error": "Path outside sandbox"}
        
        try:
            entries = os.listdir(full_path)
            return {"success": True, "entries": entries}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _validate_path(self, filepath: str) -> Optional[str]:
        """Ensure path is within sandbox"""
        import os
        full_path = os.path.abspath(os.path.join(self.sandbox_dir, filepath))
        if not full_path.startswith(os.path.abspath(self.sandbox_dir)):
            return None
        return full_path
```

### Tool Composition and Pipelines

```python
# src/tools/composition.py
from typing import List, Callable, Any, Dict
from dataclasses import dataclass

@dataclass
class ToolPipeline:
    """Chain multiple tools together"""
    steps: List[Dict[str, Any]]
    
    async def execute(self, initial_input: Any) -> Dict[str, Any]:
        """Execute pipeline sequentially"""
        result = initial_input
        outputs = []
        
        for step in self.steps:
            tool = step["tool"]
            transform = step.get("transform", lambda x: x)
            
            # Transform previous output for this tool
            tool_input = transform(result)
            
            # Execute tool
            result = await tool.execute(**tool_input)
            outputs.append(result)
            
            # Check for errors
            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error"),
                    "partial_outputs": outputs
                }
        
        return {
            "success": True,
            "final_result": result,
            "all_outputs": outputs
        }

# Example: Research pipeline
async def research_pipeline(query: str) -> Dict[str, Any]:
    """
    Multi-step research workflow:
    1. Search web for information
    2. Extract key facts
    3. Summarize findings
    """
    from .base import search_tool
    
    pipeline = ToolPipeline(steps=[
        {
            "tool": search_tool,
            "transform": lambda x: {"query": x, "num_results": 10}
        },
        {
            "tool": extract_facts_tool,  # Hypothetical tool
            "transform": lambda x: {"search_results": x["result"]}
        },
        {
            "tool": summarizer_tool,  # Hypothetical tool
            "transform": lambda x: {"facts": x["result"]}
        }
    ])
    
    return await pipeline.execute(query)
```

## Memory Systems for Stateful Agents

Agents need memory to maintain context across interactions and learn from experience.

### Conversation Memory

```python
# src/memory/conversation.py
from typing import List, Dict, Any, Optional
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class ConversationTurn:
    """Single turn in a conversation"""
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

class ConversationMemory:
    """
    Manages conversation history with sliding window.
    Prevents context overflow while maintaining coherence.
    """
    
    def __init__(
        self,
        max_turns: int = 10,
        max_tokens: Optional[int] = 4000,
        summary_threshold: int = 8
    ):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.summary_threshold = summary_threshold
        self.turns: deque[ConversationTurn] = deque(maxlen=max_turns)
        self.summary: Optional[str] = None
    
    def add_turn(self, role: str, content: str, **metadata):
        """Add a conversation turn"""
        turn = ConversationTurn(role=role, content=content, metadata=metadata)
        self.turns.append(turn)
        
        # Check if we need to summarize
        if len(self.turns) >= self.summary_threshold:
            self._maybe_summarize()
    
    def get_messages(self, include_summary: bool = True) -> List[Dict[str, str]]:
        """Get messages in LLM format"""
        messages = []
        
        # Add summary if available
        if include_summary and self.summary:
            messages.append({
                "role": "system",
                "content": f"Previous conversation summary: {self.summary}"
            })
        
        # Add recent turns
        for turn in self.turns:
            messages.append({
                "role": turn.role,
                "content": turn.content
            })
        
        return messages
    
    def _maybe_summarize(self):
        """Summarize older conversations to save tokens"""
        if len(self.turns) < self.summary_threshold:
            return
        
        # Take oldest half of turns
        turns_to_summarize = list(self.turns)[:len(self.turns)//2]
        
        # Create summary prompt
        conversation_text = "\n".join([
            f"{turn.role}: {turn.content}"
            for turn in turns_to_summarize
        ])
        
        # In production, use LLM to generate summary
        # For now, simple truncation
        self.summary = f"Earlier discussion covered: {conversation_text[:500]}..."
    
    def clear(self):
        """Clear all conversation history"""
        self.turns.clear()
        self.summary = None
    
    def get_token_count(self) -> int:
        """Estimate token count (rough approximation)"""
        total_chars = sum(len(turn.content) for turn in self.turns)
        return total_chars // 4  # Rough estimate: 1 token ≈ 4 characters

class SessionMemory:
    """
    Manages multiple conversation sessions.
    Useful for multi-user applications.
    """
    
    def __init__(self):
        self.sessions: Dict[str, ConversationMemory] = {}
    
    def get_session(self, session_id: str) -> ConversationMemory:
        """Get or create a session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationMemory()
        return self.sessions[session_id]
    
    def delete_session(self, session_id: str):
        """Remove a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def list_sessions(self) -> List[str]:
        """List all active sessions"""
        return list(self.sessions.keys())
```

### Vector-Based Semantic Memory

```python
# src/memory/vector.py
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
import hashlib
from datetime import datetime

class VectorMemory:
    """
    Semantic memory using vector embeddings.
    Retrieves relevant past experiences based on similarity.
    """
    
    def __init__(
        self,
        collection_name: str = "agent_memory",
        persist_directory: str = "./data/chroma",
        embedding_function: Optional[Any] = None
    ):
        self.client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False
        ))
        
        # Create or get collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function
        )
    
    def store(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None
    ) -> str:
        """Store a memory"""
        if doc_id is None:
            # Generate deterministic ID from content
            doc_id = hashlib.md5(content.encode()).hexdigest()
        
        metadata = metadata or {}
        metadata["timestamp"] = datetime.now().isoformat()
        
        self.collection.add(
            documents=[content],
            metadatas=[metadata],
            ids=[doc_id]
        )
        
        return doc_id
    
    def retrieve(
        self,
        query: str,
        k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve k most relevant memories"""
        results = self.collection.query(
            query_texts=[query],
            n_results=k,
            where=filter_metadata
        )
        
        # Format results
        memories = []
        for i in range(len(results['ids'][0])):
            memories.append({
                "id": results['ids'][0][i],
                "content": results['documents'][0][i],
                "metadata": results['metadatas'][0][i],
                "distance": results['distances'][0][i] if 'distances' in results else None
            })
        
        return memories
    
    def delete(self, doc_id: str):
        """Delete a specific memory"""
        self.collection.delete(ids=[doc_id])
    
    def clear_all(self):
        """Clear all memories"""
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.create_collection(
            name=self.collection.name
        )

class HybridMemory:
    """
    Combines conversation memory and vector memory.
    Short-term: Recent conversation
    Long-term: Semantic retrieval from past experiences
    """
    
    def __init__(
        self,
        session_id: str,
        vector_memory: VectorMemory,
        conversation_memory: ConversationMemory
    ):
        self.session_id = session_id
        self.vector = vector_memory
        self.conversation = conversation_memory
    
    def add_interaction(
        self,
        user_message: str,
        assistant_response: str,
        importance: float = 0.5
    ):
        """Store an interaction in both memory systems"""
        # Add to conversation memory
        self.conversation.add_turn("user", user_message)
        self.conversation.add_turn("assistant", assistant_response)
        
        # If important, also store in long-term vector memory
        if importance > 0.7:
            combined = f"User: {user_message}\nAssistant: {assistant_response}"
            self.vector.store(
                content=combined,
                metadata={
                    "session_id": self.session_id,
                    "importance": importance,
                    "type": "interaction"
                }
            )
    
    def get_context(self, current_query: str, k_longterm: int = 3) -> Dict[str, Any]:
        """
        Get full context for a query:
        - Recent conversation history
        - Relevant past experiences
        """
        # Get recent conversation
        recent_messages = self.conversation.get_messages()
        
        # Retrieve relevant long-term memories
        relevant_memories = self.vector.retrieve(
            query=current_query,
            k=k_longterm,
            filter_metadata={"session_id": self.session_id}
        )
        
        return {
            "recent_conversation": recent_messages,
            "relevant_memories": relevant_memories,
            "total_context_items": len(recent_messages) + len(relevant_memories)
        }
```

### Episodic Memory for Learning

```python
# src/memory/episodic.py
from typing import List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import json

@dataclass
class Episode:
    """
    A complete task episode with outcomes.
    Used for learning and improvement.
    """
    task: str
    actions: List[Dict[str, Any]]
    outcome: str
    success: bool
    timestamp: datetime = field(default_factory=datetime.now)
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "actions": self.actions,
            "outcome": self.outcome,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
            "metrics": self.metrics
        }

class EpisodicMemory:
    """
    Stores complete task episodes for learning.
    Agents can reflect on past successes and failures.
    """
    
    def __init__(self, persist_path: str = "./data/episodes.jsonl"):
        self.persist_path = persist_path
        self.episodes: List[Episode] = []
        self._load_episodes()
    
    def _load_episodes(self):
        """Load episodes from disk"""
        try:
            with open(self.persist_path, 'r') as f:
                for line in f:
                    data = json.loads(line)
                    episode = Episode(**data)
                    self.episodes.append(episode)
        except FileNotFoundError:
            pass
    
    def store_episode(self, episode: Episode):
        """Store a new episode"""
        self.episodes.append(episode)
        
        # Persist to disk
        with open(self.persist_path, 'a') as f:
            f.write(json.dumps(episode.to_dict()) + '\n')
    
    def get_similar_episodes(
        self,
        task: str,
        k: int = 5,
        success_only: bool = False
    ) -> List[Episode]:
        """
        Retrieve similar past episodes.
        In production, use semantic similarity.
        """
        filtered = self.episodes
        
        if success_only:
            filtered = [ep for ep in filtered if ep.success]
        
        # Simple keyword matching (use embeddings in production)
        task_words = set(task.lower().split())
        
        scored_episodes = []
        for episode in filtered:
            episode_words = set(episode.task.lower().split())
            similarity = len(task_words & episode_words) / len(task_words | episode_words)
            scored_episodes.append((similarity, episode))
        
        # Sort by similarity and return top k
        scored_episodes.sort(reverse=True, key=lambda x: x[0])
        return [ep for _, ep in scored_episodes[:k]]
    
    def get_success_rate(self, task_pattern: str = None) -> float:
        """Calculate success rate, optionally filtered by task pattern"""
        episodes = self.episodes
        
        if task_pattern:
            episodes = [
                ep for ep in episodes 
                if task_pattern.lower() in ep.task.lower()
            ]
        
        if not episodes:
            return 0.0
        
        successes = sum(1 for ep in episodes if ep.success)
        return successes / len(episodes)
```

## Multi-Agent Orchestration Patterns

Complex tasks often require multiple specialized agents working together.

### Hierarchical Agent Architecture

```python
# src/orchestration/hierarchical.py
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

class AgentRole(Enum):
    """Predefined agent roles"""
    COORDINATOR = "coordinator"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    CRITIC = "critic"

@dataclass
class Task:
    """Task specification"""
    description: str
    assigned_to: Optional[str] = None
    dependencies: List[str] = None
    result: Any = None
    status: str = "pending"  # pending, in_progress, completed, failed

class HierarchicalOrchestrator:
    """
    Coordinates multiple agents in a hierarchical structure.
    Manager agent delegates to specialist agents.
    """
    
    def __init__(
        self,
        manager_agent: Any,
        specialist_agents: Dict[str, Any],
        max_delegation_depth: int = 3
    ):
        self.manager = manager_agent
        self.specialists = specialist_agents
        self.max_depth = max_delegation_depth
        self.task_graph: List[Task] = []
    
    async def execute(self, goal: str) -> Dict[str, Any]:
        """Execute a complex goal using hierarchical delegation"""
        
        # Phase 1: Planning - Manager breaks down the goal
        plan = await self._create_plan(goal)
        
        # Phase 2: Delegation - Assign tasks to specialists
        results = {}
        for task in plan:
            result = await self._execute_task(task)
            results[task.description] = result
        
        # Phase 3: Integration - Manager synthesizes results
        final_output = await self._synthesize_results(goal, results)
        
        return {
            "goal": goal,
            "plan": [t.description for t in plan],
            "results": results,
            "final_output": final_output
        }
    
    async def _create_plan(self, goal: str) -> List[Task]:
        """Manager agent creates task breakdown"""
        planning_prompt = f"""
        Break down this goal into specific subtasks:
        Goal: {goal}
        
        Available specialists:
        {self._format_specialists()}
        
        Create a list of subtasks, each with:
        - Description
        - Which specialist should handle it
        - Dependencies (if any)
        """
        
        # Manager generates plan
        response = await self.manager.run(planning_prompt)
        
        # Parse plan into Task objects
        tasks = self._parse_plan(response.output)
        return tasks
    
    async def _execute_task(self, task: Task) -> Any:
        """Execute a single task with appropriate specialist"""
        if task.assigned_to not in self.specialists:
            raise ValueError(f"Unknown specialist: {task.assigned_to}")
        
        specialist = self.specialists[task.assigned_to]
        task.status = "in_progress"
        
        try:
            result = await specialist.run(task.description)
            task.status = "completed"
            task.result = result.output
            return result.output
        except Exception as e:
            task.status = "failed"
            return {"error": str(e)}
    
    async def _synthesize_results(
        self,
        goal: str,
        results: Dict[str, Any]
    ) -> str:
        """Manager synthesizes all results into final answer"""
        synthesis_prompt = f"""
        Original goal: {goal}
        
        Results from specialists:
        {self._format_results(results)}
        
        Synthesize these results into a comprehensive final answer.
        """
        
        response = await self.manager.run(synthesis_prompt)
        return response.output
    
    def _format_specialists(self) -> str:
        """Format specialist descriptions for planning"""
        descriptions = []
        for name, agent in self.specialists.items():
            descriptions.append(f"- {name}: {agent.description}")
        return "\n".join(descriptions)
    
    def _format_results(self, results: Dict[str, Any]) -> str:
        """Format results for synthesis"""
        formatted = []
        for task, result in results.items():
            formatted.append(f"\nTask: {task}\nResult: {result}\n")
        return "\n".join(formatted)
    
    def _parse_plan(self, plan_text: str) -> List[Task]:
        """Parse manager's plan into Task objects"""
        # Simplified parsing - in production, use structured output
        tasks = []
        lines = plan_text.split('\n')
        
        for line in lines:
            if line.strip().startswith('-'):
                # Extract task description and assignment
                # This is simplified - implement proper parsing
                tasks.append(Task(
                    description=line.strip('- '),
                    dependencies=[]
                ))
        
        return tasks
```

### Parallel Agent Execution

```python
# src/orchestration/parallel.py
import asyncio
from typing import List, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ParallelTask:
    """Task for parallel execution"""
    agent: Any
    prompt: str
    priority: int = 0
    timeout: int = 300

class ParallelOrchestrator:
    """
    Executes multiple agents in parallel.
    Useful for gathering diverse perspectives or speeding up independent tasks.
    """
    
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_parallel(
        self,
        tasks: List[ParallelTask]
    ) -> Dict[str, Any]:
        """Execute tasks in parallel with concurrency limit"""
        
        start_time = datetime.now()
        
        # Create async tasks
        async_tasks = [
            self._execute_single(task)
            for task in tasks
        ]
        
        # Wait for all to complete
        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Package results
        return {
            "results": results,
            "total_tasks": len(tasks),
            "successful": sum(1 for r in results if not isinstance(r, Exception)),
            "failed": sum(1 for r in results if isinstance(r, Exception)),
            "duration_seconds": duration
        }
    
    async def _execute_single(self, task: ParallelTask) -> Any:
        """Execute single task with semaphore"""
        async with self.semaphore:
            try:
                result = await asyncio.wait_for(
                    task.agent.run(task.prompt),
                    timeout=task.timeout
                )
                return result.output
            except asyncio.TimeoutError:
                return {"error": "Task timeout"}
            except Exception as e:
                return {"error": str(e)}
    
    async def consensus_voting(
        self,
        agents: List[Any],
        prompt: str,
        voting_fn: Callable = None
    ) -> Dict[str, Any]:
        """
        Run multiple agents on same task and vote on best answer.
        Useful for critical decisions.
        """
        
        # Execute all agents
        tasks = [
            ParallelTask(agent=agent, prompt=prompt)
            for agent in agents
        ]
        
        results = await self.execute_parallel(tasks)
        
        # Default voting: most common answer
        if voting_fn is None:
            voting_fn = self._majority_vote
        
        winner = voting_fn(results["results"])
        
        return {
            "consensus": winner,
            "all_responses": results["results"],
            "agreement_score": self._calculate_agreement(results["results"])
        }
    
    def _majority_vote(self, responses: List[Any]) -> Any:
        """Simple majority voting"""
        from collections import Counter
        
        # Convert to strings for comparison
        str_responses = [str(r) for r in responses if not isinstance(r, Exception)]
        
        if not str_responses:
            return None
        
        counter = Counter(str_responses)
        return counter.most_common(1)[0][0]
    
    def _calculate_agreement(self, responses: List[Any]) -> float:
        """Calculate how much agents agree (0-1)"""
        from collections import Counter
        
        str_responses = [str(r) for r in responses if not isinstance(r, Exception)]
        
        if not str_responses:
            return 0.0
        
        counter = Counter(str_responses)
        most_common_count = counter.most_common(1)[0][1]
        
        return most_common_count / len(str_responses)
```

### Sequential Pipeline Pattern

```python
# src/orchestration/pipeline.py
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class PipelineStage:
    """Single stage in processing pipeline"""
    name: str
    agent: Any
    transform_input: Optional[Any] = None
    validate_output: Optional[Any] = None

class AgentPipeline:
    """
    Sequential agent pipeline where each agent processes
    the output of the previous agent.
    """
    
    def __init__(self, stages: List[PipelineStage]):
        self.stages = stages
    
    async def execute(self, initial_input: str) -> Dict[str, Any]:
        """Execute complete pipeline"""
        
        current_input = initial_input
        stage_outputs = []
        
        for i, stage in enumerate(self.stages):
            print(f"\n=== Stage {i+1}: {stage.name} ===")
            
            # Transform input if needed
            if stage.transform_input:
                current_input = stage.transform_input(current_input)
            
            # Execute stage
            result = await stage.agent.run(current_input)
            
            # Validate output if needed
            if stage.validate_output:
                is_valid, error = stage.validate_output(result.output)
                if not is_valid:
                    return {
                        "success": False,
                        "failed_stage": stage.name,
                        "error": error,
                        "partial_outputs": stage_outputs
                    }
            
            # Store output
            stage_outputs.append({
                "stage": stage.name,
                "output": result.output,
                "tokens": result.total_tokens
            })
            
            # Output becomes input for next stage
            current_input = result.output
        
        return {
            "success": True,
            "final_output": current_input,
            "stage_outputs": stage_outputs,
            "total_tokens": sum(s["tokens"] for s in stage_outputs)
        }

# Example: Research Report Pipeline
async def create_research_pipeline():
    """
    Multi-stage research pipeline:
    1. Research: Gather information
    2. Analysis: Extract insights
    3. Writing: Create report
    4. Review: Critique and refine
    """
    
    from src.agents.react import ReActAgent
    from openai import OpenAI
    
    client = OpenAI()
    
    # Create specialized agents
    researcher = ReActAgent(
        llm_client=client,
        tools=[search_tool],
        name="Researcher"
    )
    
    analyst = ReActAgent(
        llm_client=client,
        tools=[calculator_tool],
        name="Analyst"
    )
    
    # Define pipeline stages
    pipeline = AgentPipeline(stages=[
        PipelineStage(
            name="Research",
            agent=researcher,
            transform_input=lambda x: f"Research this topic thoroughly: {x}"
        ),
        PipelineStage(
            name="Analysis",
            agent=analyst,
            transform_input=lambda x: f"Analyze this research and extract key insights:\n{x}"
        ),
        PipelineStage(
            name="Writing",
            agent=writer,  # Hypothetical writer agent
            transform_input=lambda x: f"Write a comprehensive report based on:\n{x}"
        )
    ])
    
    return pipeline
```

## Error Handling and Reliability Patterns

Production agents must handle failures gracefully and maintain reliability.

### Retry and Fallback Strategies

```python
# src/reliability/retry.py
from typing import Callable, Any, Optional, Type
import asyncio
from functools import wraps
import logging

logger = logging.getLogger(__name__)

class RetryConfig:
    """Configuration for retry behavior"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        backoff_factor: float = 2.0,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exceptions: tuple = (Exception,)
    ):
        self.max_attempts = max_attempts
        self.backoff_factor = backoff_factor
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exceptions = exceptions

async def retry_with_backoff(
    func: Callable,
    config: RetryConfig,
    *args,
    **kwargs
) -> Any:
    """Execute function with exponential backoff retry"""
    
    delay = config.initial_delay
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            logger.info(f"Attempt {attempt + 1}/{config.max_attempts}")
            result = await func(*args, **kwargs)
            return result
            
        except config.exceptions as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
            
            if attempt < config.max_attempts - 1:
                logger.info(f"Retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay = min(delay * config.backoff_factor, config.max_delay)
            else:
                logger.error(f"All {config.max_attempts} attempts failed")
    
    raise last_exception

def with_retry(config: RetryConfig):
    """Decorator for automatic retry"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_with_backoff(func, config, *args, **kwargs)
        return wrapper
    return decorator

# Example usage
retry_config = RetryConfig(
    max_attempts=3,
    backoff_factor=2.0,
    initial_delay=1.0
)

@with_retry(retry_config)
async def call_llm_with_retry(prompt: str) -> str:
    """LLM call with automatic retry"""
    # This will retry on failures
    response = await llm.chat.completions.create(
        model="gpt-4-turbo-2024-04-09",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
```

### Circuit Breaker Pattern

```python
# src/reliability/circuit_breaker.py
from enum import Enum
from datetime import datetime, timedelta
from typing import Callable, Any
import asyncio

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered

class CircuitBreaker:
    """
    Circuit breaker for external service calls.
    Prevents cascading failures by failing fast.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type[Exception] = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED
    
    async def call(self