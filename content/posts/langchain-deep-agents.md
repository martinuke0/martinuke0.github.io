---
title: "LangChain Zero to Hero: From Basic Chains to Deep Agents"
date: 2025-12-04T15:00:00+02:00
description: "Complete guide to LangChain from fundamentals to advanced deep agents with Python examples"
tags: ["langchain", "python", "ai", "agents", "machine-learning", "llm"]
categories: ["Technology", "AI", "Programming"]
---

# LangChain Zero to Hero: From Basic Chains to Deep Agents

Welcome to your comprehensive journey through LangChain, the powerful framework for building applications powered by large language models. This guide will take you from the absolute basics to building sophisticated deep agents that can tackle complex, multi-step problems.

> **🚀 Practical Integration**: Throughout this tutorial, we'll use real-world tools and services mentioned in the resources section, showing you exactly how to integrate them into your LangChain applications.

## Table of Contents

1. [Getting Started with LangChain](#getting-started)
2. [Core Concepts and Building Blocks](#core-concepts)
3. [Building Your First Chain](#first-chain)
4. [Advanced Chain Patterns](#advanced-chains)
5. [Introduction to Agents](#agents-intro)
6. [Building Custom Tools](#custom-tools)
7. [Deep Agents Architecture](#deep-agents)
8. [Production Deployment](#production)
9. [Best Practices and Tips](#best-practices)
10. [Resources and Next Steps](#resources)

---

## Getting Started with LangChain {#getting-started}

### Installation and Setup

Let's start by installing LangChain and setting up our environment:

```bash
# Install LangChain core package
pip install langchain

# Install OpenAI integration (most common LLM provider)
pip install langchain-openai

# Install additional packages we'll need
pip install python-dotenv tiktoken faiss-cpu
pip install langchain-community langchain-experimental
```

### Environment Configuration

Create a `.env` file to store your API keys securely:

```bash
OPENAI_API_KEY=your_openai_api_key_here
LANGCHAIN_API_KEY=your_langchain_api_key_here  # Optional for LangSmith
LANGCHAIN_TRACING_V2=true
```

Load environment variables in Python:

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Verify API key is loaded
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not found in environment variables")
```

### Basic LLM Setup

Let's start with a simple LLM interaction:

```python
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

# Initialize the model
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0.7,
    openai_api_key=os.getenv("OPENAI_API_KEY")
)

# Basic interaction
messages = [
    SystemMessage(content="You are a helpful AI assistant."),
    HumanMessage(content="Explain quantum computing in simple terms.")
]

response = llm.invoke(messages)
print(response.content)
```

---

## Core Concepts and Building Blocks {#core-concepts}

### Understanding LangChain Components

LangChain is built around several key components:

1. **Models**: The LLMs that power your applications
2. **Prompts**: Templates for structuring inputs to models
3. **Chains**: Sequences of calls to models and other components
4. **Agents**: Systems that use models to decide which actions to take
5. **Memory**: Systems for persisting state between calls
6. **Indexes**: Structures for organizing and retrieving external data

### Prompt Templates

Prompt templates help you create reusable, dynamic prompts:

```python
from langchain.prompts import PromptTemplate, ChatPromptTemplate

# Simple prompt template
simple_template = PromptTemplate(
    input_variables=["topic", "level"],
    template="Explain {topic} at a {level} level."
)

# Chat prompt template with multiple roles
chat_template = ChatPromptTemplate.from_messages([
    ("system", "You are an expert {subject} teacher."),
    ("human", "Explain {concept} in {difficulty} terms."),
    ("human", "Provide a {example_type} example.")
])

# Use the template
prompt = chat_template.format_messages(
    subject="physics",
    concept="relativity",
    difficulty="simple",
    example_type="practical"
)

response = llm.invoke(prompt)
print(response.content)
```

### Output Parsers

Output parsers structure the model's output into usable formats:

```python
from langchain.output_parsers import CommaSeparatedListOutputParser
from langchain.output_parsers import StructuredOutputParser, ResponseSchema

# List output parser
list_parser = CommaSeparatedListOutputParser()
list_prompt = PromptTemplate(
    template="List 5 key concepts in {topic}.\n{format_instructions}",
    input_variables=["topic"],
    partial_variables={"format_instructions": list_parser.get_format_instructions()}
)

# Structured output parser
response_schemas = [
    ResponseSchema(name="definition", description="A clear definition of the concept"),
    ResponseSchema(name="importance", description="Why this concept matters"),
    ResponseSchema(name="example", description="A practical example")
]
structured_parser = StructuredOutputParser.from_response_schemas(response_schemas)

structured_prompt = PromptTemplate(
    template="Analyze the concept {concept}.\n{format_instructions}",
    input_variables=["concept"],
    partial_variables={"format_instructions": structured_parser.get_format_instructions()}
)

# Use structured parser
prompt = structured_prompt.format(concept="machine learning")
response = llm.invoke(prompt)
parsed_output = structured_parser.parse(response.content)
print(parsed_output)
```

---

## Building Your First Chain {#first-chain}

### Simple LLM Chain

Let's create our first basic chain:

```python
from langchain.chains import LLMChain

# Create a prompt template
template = """
Question: {question}
Helpful Answer:"""

prompt = PromptTemplate(template=template, input_variables=["question"])

# Create the chain
chain = LLMChain(llm=llm, prompt=prompt)

# Run the chain
question = "What are the main benefits of using LangChain?"
response = chain.run(question)
print(response)
```

### Sequential Chains

Combine multiple chains to process complex tasks:

```python
from langchain.chains import SequentialChain, LLMChain

# First chain: Generate outline
outline_template = """
Topic: {topic}
Create a detailed outline for a blog post about this topic.
Outline:"""

outline_prompt = PromptTemplate(template=outline_template, input_variables=["topic"])
outline_chain = LLMChain(llm=llm, prompt=outline_prompt, output_key="outline")

# Second chain: Write introduction
intro_template = """
Outline:
{outline}

Based on this outline, write an engaging introduction:
Introduction:"""

intro_prompt = PromptTemplate(template=intro_template, input_variables=["outline"])
intro_chain = LLMChain(llm=llm, prompt=intro_prompt, output_key="introduction")

# Combine chains
overall_chain = SequentialChain(
    chains=[outline_chain, intro_chain],
    input_variables=["topic"],
    output_variables=["outline", "introduction"]
)

# Run the sequential chain
result = overall_chain({"topic": "The Future of Artificial Intelligence"})
print("Outline:", result["outline"])
print("Introduction:", result["introduction"])
```

### Router Chains

Route inputs to different chains based on content:

```python
from langchain.chains.router import MultiPromptChain
from langchain.chains.router.llm_router import LLMRouterChain, RouterOutputParser

# Define different prompt templates
physics_template = """You are a physics expert. 
Question: {input}
Answer:"""

math_template = """You are a mathematics expert.
Question: {input}
Answer:"""

history_template = """You are a history expert.
Question: {input}
Answer:"""

# Create prompt infos for routing
prompt_infos = [
    {
        "name": "physics",
        "description": "Good for answering questions about physics",
        "prompt_template": physics_template
    },
    {
        "name": "math", 
        "description": "Good for answering math questions",
        "prompt_template": math_template
    },
    {
        "name": "history",
        "description": "Good for answering historical questions", 
        "prompt_template": history_template
    }
]

# Create destination chains
destination_chains = {}
for p_info in prompt_infos:
    name = p_info["name"]
    prompt_template = p_info["prompt_template"]
    chain = LLMChain(llm=llm, prompt=PromptTemplate(template=prompt_template, input_variables=["input"]))
    destination_chains[name] = chain

# Create router chain
router_template = """Given a user question, route it to the appropriate expert.

{destinations}

Question: {input}
Destination:"""

router_prompt = PromptTemplate(
    template=router_template,
    input_variables=["input", "destinations"],
    output_parser=RouterOutputParser()
)

router_chain = LLMRouterChain.from_llm(llm, router_prompt)

# Create the main chain
chain = MultiPromptChain(
    router_chain=router_chain,
    destination_chains=destination_chains,
    default_chain=LLMChain(llm=llm, prompt=PromptTemplate.from_template("{input}"))
)

# Test the router
questions = [
    "What is the speed of light?",
    "How do you solve quadratic equations?",
    "When did World War II end?"
]

for question in questions:
    print(f"Question: {question}")
    print(f"Answer: {chain.run(question)}\n")
```

---

## Advanced Chain Patterns {#advanced-chains}

### Transform Chain

Process and transform data before passing to LLM:

```python
from langchain.chains import TransformChain

def text_cleanup(inputs: dict) -> dict:
    """Clean and preprocess text input."""
    text = inputs["text"]
    # Remove extra whitespace
    text = " ".join(text.split())
    # Convert to lowercase for analysis
    cleaned = text.lower()
    return {"cleaned_text": cleaned}

transform_chain = TransformChain(
    input_variables=["text"],
    output_variables=["cleaned_text"], 
    transform=text_cleanup
)

# Combine with LLM chain
analysis_template = """
Analyze the following text for sentiment and key themes:

Text: {cleaned_text}

Analysis:"""

analysis_prompt = PromptTemplate(template=analysis_template, input_variables=["cleaned_text"])
analysis_chain = LLMChain(llm=llm, prompt=analysis_prompt)

# Create combined chain
from langchain.chains import SimpleSequentialChain

combined_chain = SimpleSequentialChain(chains=[transform_chain, analysis_chain])

# Test the combined chain
sample_text = "    I absolutely LOVE this new feature!   It's amazing and works perfectly.    "
result = combined_chain.run(sample_text)
print(result)
```

### Document Chain

Work with documents and question-answering:

```python
from langchain.chains.question_answering import load_qa_chain
from langchain.docstore.document import Document

# Create sample documents
docs = [
    Document(page_content="Python is a high-level programming language created by Guido van Rossum.", 
             metadata={"source": "wiki"}),
    Document(page_content="LangChain is a framework for building applications with large language models.",
             metadata={"source": "docs"}),
    Document(page_content="Machine learning is a subset of artificial intelligence that focuses on algorithms.",
             metadata={"source": "textbook"})
]

# Load QA chain
qa_chain = load_qa_chain(llm, chain_type="stuff")

# Ask questions about the documents
question = "Who created Python and what is LangChain?"
result = qa_chain.run(input_documents=docs, question=question)
print(result)
```

### Summarization Chain

Create powerful summarization capabilities:

```python
from langchain.chains.summarize import load_summarize_chain

# Load summarization chain
summarize_chain = load_summarize_chain(llm, chain_type="map_reduce")

# Summarize documents
long_text = """
[Insert a long article or document here for summarization]
"""

# Create document from text
doc = Document(page_content=long_text)

# Generate summary
summary = summarize_chain.run([doc])
print("Summary:", summary)
```

---

## Introduction to Agents {#agents-intro}

### What are Agents?

Agents are systems that use LLMs to decide which actions to take and in what order. They can:
- Access external tools and APIs
- Make decisions based on context
- Handle complex, multi-step tasks
- Learn from feedback

### Basic Agent Setup

Let's create a simple agent with access to basic tools:

```python
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain.tools import Tool
from langchain_openai import ChatOpenAI

# Define custom tools
def calculator(expression: str) -> str:
    """Simple calculator for basic math expressions."""
    try:
        # Safe evaluation of math expressions
        import math
        # Replace common math functions
        expression = expression.replace('^', '**')
        result = eval(expression)
        return str(result)
    except:
        return "Error: Invalid expression"

def get_current_time() -> str:
    """Get the current date and time."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def search_wikipedia(query: str) -> str:
    """Search Wikipedia for information."""
    try:
        import wikipedia
        wikipedia.set_lang("en")
        summary = wikipedia.summary(query, sentences=3)
        return summary
    except:
        return f"Could not find information about '{query}' on Wikipedia."

# Create tool instances
tools = [
    Tool(
        name="Calculator",
        func=calculator,
        description="Useful for mathematical calculations. Input should be a mathematical expression."
    ),
    Tool(
        name="CurrentTime",
        func=get_current_time,
        description="Returns the current date and time."
    ),
    Tool(
        name="Wikipedia",
        func=search_wikipedia,
        description="Search Wikipedia for information about a topic. Input should be a search query."
    )
]

# Create the prompt template
from langchain import hub
prompt = hub.pull("hwchase17/openai-tools-agent")

# Create the agent
agent = create_openai_tools_agent(llm, tools, prompt)

# Create the agent executor
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# Test the agent
questions = [
    "What is 15 * 24 + 100?",
    "What time is it now?",
    "Tell me about Albert Einstein."
]

for question in questions:
    print(f"Question: {question}")
    result = agent_executor.invoke({"input": question})
    print(f"Answer: {result['output']}\n")
```

### Conversational Agent with Memory

Add memory to maintain conversation context:

```python
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.memory import ConversationBufferMemory

# Create memory
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

# Create conversational prompt
from langchain.prompts import MessagesPlaceholder

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant with access to tools. Use tools when necessary."),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# Create the agent
agent = create_openai_functions_agent(llm, tools, prompt)

# Create executor with memory
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    verbose=True
)

# Test conversational capabilities
print("Starting conversation with memory...")
agent_executor.invoke({"input": "Hi, my name is Alice."})
agent_executor.invoke({"input": "What's my name?"})
agent_executor.invoke({"input": "Calculate 25 * 4 and then add 100 to the result."})
```

---

## Building Custom Tools {#custom-tools}

### Creating Advanced Tools

Let's build more sophisticated tools for specific tasks:

```python
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import requests
import json

class WeatherInput(BaseModel):
    location: str = Field(description="Location to get weather for")

class WeatherTool(BaseTool):
    name = "weather"
    description = "Get current weather information for a location"
    args_schema: Type[BaseModel] = WeatherInput
    
    def _run(self, location: str) -> str:
        """Get weather for a location."""
        # This is a mock implementation - in production, use a real weather API
        weather_data = {
            "New York": {"temp": "72°F", "condition": "Sunny", "humidity": "45%"},
            "London": {"temp": "59°F", "condition": "Cloudy", "humidity": "70%"},
            "Tokyo": {"temp": "68°F", "condition": "Partly Cloudy", "humidity": "60%"},
        }
        
        if location in weather_data:
            data = weather_data[location]
            return f"Weather in {location}: {data['temp']}, {data['condition']}, Humidity: {data['humidity']}"
        else:
            return f"Weather data not available for {location}"

class EmailInput(BaseModel):
    recipient: str = Field(description="Email address of the recipient")
    subject: str = Field(description="Subject of the email")
    body: str = Field(description="Body content of the email")

class EmailTool(BaseTool):
    name = "email_sender"
    description = "Send an email to a recipient"
    args_schema: Type[BaseModel] = EmailInput
    
    def _run(self, recipient: str, subject: str, body: str) -> str:
        """Send an email (mock implementation)."""
        # In production, integrate with actual email service
        return f"Email sent to {recipient} with subject '{subject}'. Body: {body[:50]}..."

class CodeExecutorInput(BaseModel):
    code: str = Field(description="Python code to execute")

class CodeExecutorTool(BaseTool):
    name = "code_executor"
    description = "Execute Python code safely"
    args_schema: Type[BaseModel] = CodeExecutorInput
    
    def _run(self, code: str) -> str:
        """Safely execute Python code."""
        try:
            # Create a safe execution environment
            safe_globals = {
                '__builtins__': {
                    'print': print,
                    'len': len,
                    'range': range,
                    'sum': sum,
                    'max': max,
                    'min': min,
                    'abs': abs,
                    'round': round,
                },
                'math': __import__('math'),
                'datetime': __import__('datetime'),
            }
            
            # Capture output
            import io
            import sys
            old_stdout = sys.stdout
            sys.stdout = captured_output = io.StringIO()
            
            # Execute the code
            exec(code, safe_globals)
            
            # Get output
            sys.stdout = old_stdout
            output = captured_output.getvalue()
            
            return output if output else "Code executed successfully (no output)"
            
        except Exception as e:
            return f"Error executing code: {str(e)}"

# Create advanced tools list
advanced_tools = [
    WeatherTool(),
    EmailTool(),
    CodeExecutorTool(),
    Tool(
        name="calculator",
        func=lambda x: str(eval(x)),
        description="Calculate mathematical expressions"
    )
]
```

### Tool Integration with Agent

```python
# Create advanced agent with custom tools
advanced_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an advanced AI assistant with access to various tools. 
    Use the appropriate tool for each task. Be helpful and accurate."""),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

advanced_agent = create_openai_functions_agent(llm, advanced_tools, advanced_prompt)
advanced_executor = AgentExecutor(
    agent=advanced_agent,
    tools=advanced_tools,
    memory=ConversationBufferMemory(memory_key="chat_history", return_messages=True),
    verbose=True
)

# Test advanced capabilities
test_queries = [
    "What's the weather like in London?",
    "Send an email to john@example.com with subject 'Meeting' and body 'Let's meet tomorrow'",
    "Calculate the factorial of 5 using Python code"
]

for query in test_queries:
    print(f"Query: {query}")
    result = advanced_executor.invoke({"input": query})
    print(f"Result: {result['output']}\n")
```

---

## Deep Agents Architecture {#deep-agents}

### Understanding Deep Agents

Deep Agents represent the next evolution in AI agent architecture, incorporating:

1. **Hierarchical Planning**: Breaking complex tasks into subtasks
2. **Self-Reflection**: Agents that can evaluate and improve their own performance
3. **Tool Composition**: Combining multiple tools in sophisticated ways
4. **Learning from Experience**: Adapting based on past interactions
5. **Multi-Agent Collaboration**: Multiple agents working together

### 🚀 Practical Integration: Using LangSmith for Monitoring

Let's enhance our deep agent with LangSmith integration for better observability and debugging:

```python
# Add LangSmith integration
from langchain.smith import LangSmith

# Configure LangSmith
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "langchain-deep-agents-tutorial"

# Create enhanced deep agent with LangSmith
deep_agent_with_smith = AutoGPT.from_llm_and_tools(
    ai_name="DeepAgent",
    ai_role="An advanced AI assistant with LangSmith monitoring",
    tools=deep_tools,
    llm=llm,
    memory=create_knowledge_base(),
    human_in_the_loop=False,
    max_iterations=5,
    # LangSmith will automatically trace and log all agent runs
    verbose=True
)

# Test with LangSmith integration
print("Testing deep agent with LangSmith monitoring...")
result = deep_agent_with_smith.run([task])
print("Result:", result)
```

### 🔧 LangSmith Dashboard Integration

After running your agent with LangSmith enabled, you can:

1. **View Traces**: Visit https://smith.langchain.com to see detailed execution traces
2. **Monitor Performance**: Track token usage, costs, and execution times
3. **Debug Failures**: Identify where and why agents fail
4. **Compare Runs**: A/B test different agent configurations
5. **Export Data**: Download agent data for further analysis

### 📊 Production Deployment with LangSmith

For production deployment, LangSmith provides:

```python
from langchain.smith import Client

# Initialize LangSmith client
client = Client()

# Create a monitored agent for production
production_agent = ProductionAgent(
    agent_executor=advanced_executor,
    monitor=AgentMonitor(log_file="production.log")
)

# Deploy with LangSmith tracking
def deploy_with_monitoring(task):
    """Deploy agent with comprehensive monitoring."""
    start_time = datetime.now()
    
    try:
        result = production_agent.run_with_monitoring(task)
        
        # Log to LangSmith dashboard
        client.create_run(
            name="Agent Execution",
            input=task,
            output=result,
            start_time=start_time,
            end_time=datetime.now(),
            tags=["production", "deep-agent"]
        )
        
        print(f"✅ Agent executed successfully")
        print(f"📊 View details: https://smith.langchain.com")
        
        return result
        
    except Exception as e:
        print(f"❌ Agent failed: {str(e)}")
        
        # Log failure to LangSmith
        client.create_run(
            name="Agent Execution",
            input=task,
            output=str(e),
            start_time=start_time,
            end_time=datetime.now(),
            tags=["production", "error", "deep-agent"]
        )
        
        raise

# Example usage
if __name__ == "__main__":
    deploy_with_monitoring("Analyze market trends for Q4 2024")
```

### 🎯 Best Practices for LangSmith Integration

1. **Environment Variables**: Always set `LANGCHAIN_TRACING_V2=true` in production
2. **Project Naming**: Use descriptive project names in `LANGCHAIN_PROJECT`
3. **Tagging**: Consistent tags help organize runs in the dashboard
4. **Error Handling**: Log all exceptions for better debugging
5. **Cost Monitoring**: Track token usage and set alerts if thresholds exceeded

This integration provides enterprise-grade observability for your LangChain applications!

Let's build a sophisticated deep agent system based on the LangChain Deep Agents framework:

```python
from langchain_experimental.autonomous_agents import AutoGPT
from langchain.vectorstores import FAISS
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.docstore import InMemoryDocstore
from langchain.tools import DuckDuckGoSearchRun
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Create a knowledge base
def create_knowledge_base():
    """Create a vector store for the agent's knowledge base."""
    embeddings = OpenAIEmbeddings()
    vector_store = FAISS(embeddings, InMemoryDocstore(), {})
    return vector_store

# Create search tool
search = DuckDuckGoSearchRun()

# Define specialized tools for deep agent
deep_tools = [
    search,
    Tool(
        name="python_repl",
        description="A Python shell. Use this to execute python commands. Input should be a valid python command. If you want to see the output of a value, you should print it out with `print(...)`.",
        func=lambda x: str(eval(x))
    ),
    Tool(
        name="text_analyzer",
        description="Analyze text for sentiment, entities, and key themes",
        func=lambda text: f"Analysis of text: {text[:100]}... (Mock analysis)"
    )
]

# Create the deep agent
deep_agent = AutoGPT.from_llm_and_tools(
    ai_name="DeepAgent",
    ai_role="An advanced AI assistant capable of complex problem-solving and tool composition",
    tools=deep_tools,
    llm=llm,
    memory=create_knowledge_base(),
    human_in_the_loop=False,
    max_iterations=5
)

# Set up the agent with a specific goal
deep_agent.chain.verbose = True

# Example: Research and analysis task
task = """
Research the latest developments in quantum computing and create a comprehensive summary.
Include:
1. Key breakthroughs in the last 6 months
2. Major companies and their contributions
3. Potential applications
4. Challenges and limitations
"""

# Run the deep agent
result = deep_agent.run([task])
print("Deep Agent Result:", result)
```

### Hierarchical Agent System

Create a system of specialized agents that work together:

```python
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

class SpecialistAgent:
    def __init__(self, name, role, tools, system_prompt):
        self.name = name
        self.role = role
        self.tools = tools
        self.system_prompt = system_prompt
        self.agent = self._create_agent()
    
    def _create_agent(self):
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        agent = create_openai_functions_agent(llm, self.tools, prompt)
        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            memory=ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        )
    
    def run(self, task):
        return self.agent.invoke({"input": task})

# Create specialist agents
researcher = SpecialistAgent(
    name="Researcher",
    role="Gathers and analyzes information",
    tools=[search, Tool(name="summarize", func=lambda x: f"Summary: {x[:200]}...", description="Summarize text")],
    system_prompt="You are a research specialist. Your job is to gather comprehensive information and provide detailed analysis."
)

analyzer = SpecialistAgent(
    name="Analyzer", 
    role="Analyzes data and provides insights",
    tools=[Tool(name="analyze", func=lambda x: f"Analysis: {x}", description="Analyze data")],
    system_prompt="You are a data analyst. Your job is to analyze information and provide deep insights."
)

writer = SpecialistAgent(
    name="Writer",
    role="Creates well-structured content",
    tools=[Tool(name="write", func=lambda x: f"Written content: {x}", description="Write content")],
    system_prompt="You are a professional writer. Your job is to create clear, well-structured content based on analysis."
)

# Coordinator agent that manages the specialists
def coordinate_agents(task):
    """Coordinate multiple specialist agents to complete a complex task."""
    
    # Step 1: Research
    print("Step 1: Research Phase")
    research_result = researcher.run(f"Research: {task}")
    
    # Step 2: Analysis  
    print("\nStep 2: Analysis Phase")
    analysis_result = analyzer.run(f"Analyze this research: {research_result['output']}")
    
    # Step 3: Writing
    print("\nStep 3: Writing Phase")
    final_result = writer.run(f"Create a comprehensive report based on: {analysis_result['output']}")
    
    return final_result['output']

# Test the hierarchical system
complex_task = "Create a comprehensive report on the impact of AI on healthcare"
result = coordinate_agents(complex_task)
print("\nFinal Result:", result)
```

### Self-Reflecting Agent

Create an agent that can evaluate and improve its own performance:

```python
class SelfReflectingAgent:
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = tools
        self.reflection_prompt = ChatPromptTemplate.from_template("""
        Evaluate the following response based on:
        1. Accuracy: Is the information correct?
        2. Completeness: Does it fully answer the question?
        3. Clarity: Is the response clear and well-structured?
        
        Original Question: {question}
        Response: {response}
        
        Provide a score (1-10) for each criterion and suggest improvements:
        """)
        
        self.improvement_prompt = ChatPromptTemplate.from_template("""
        Based on this feedback, improve the original response:
        
        Original Question: {question}
        Original Response: {response}
        Feedback: {feedback}
        
        Provide an improved response:
        """)
    
    def reflect_and_improve(self, question, initial_response):
        """Reflect on and improve an initial response."""
        
        # Get reflection
        reflection_chain = LLMChain(llm=self.llm, prompt=self.reflection_prompt)
        feedback = reflection_chain.run(
            question=question,
            response=initial_response
        )
        
        # Generate improved response
        improvement_chain = LLMChain(llm=self.llm, prompt=self.improvement_prompt)
        improved_response = improvement_chain.run(
            question=question,
            response=initial_response,
            feedback=feedback
        )
        
        return {
            "original": initial_response,
            "feedback": feedback,
            "improved": improved_response
        }

# Create and test self-reflecting agent
reflecting_agent = SelfReflectingAgent(llm, advanced_tools)

# Test with a complex question
question = "Explain the implications of quantum computing on cybersecurity"
initial_answer = "Quantum computers could break current encryption."

result = reflecting_agent.reflect_and_improve(question, initial_answer)
print("Original Answer:", result["original"])
print("\nFeedback:", result["feedback"])
print("\nImproved Answer:", result["improved"])
```

---

## Production Deployment {#production}

### Error Handling and Retry Logic

Implement robust error handling for production use:

```python
from langchain.retry import RetryCallbackHandler
from langchain.callbacks import get_openai_callback
import time
import random

class ProductionAgent:
    def __init__(self, agent_executor, max_retries=3, base_delay=1):
        self.agent = agent_executor
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    def run_with_retry(self, input_text, context=None):
        """Execute agent with retry logic and error handling."""
        
        for attempt in range(self.max_retries + 1):
            try:
                # Track usage and costs
                with get_openai_callback() as cb:
                    if context:
                        result = self.agent.invoke({
                            "input": input_text,
                            "context": context
                        })
                    else:
                        result = self.agent.invoke({"input": input_text})
                    
                    # Log usage metrics
                    print(f"Tokens used: {cb.total_tokens}")
                    print(f"Total cost: ${cb.total_cost}")
                    
                    return result["output"]
                    
            except Exception as e:
                if attempt == self.max_retries:
                    # Final attempt failed
                    error_msg = f"Failed after {self.max_retries + 1} attempts: {str(e)}"
                    print(error_msg)
                    return f"I apologize, but I encountered an error: {error_msg}"
                
                # Exponential backoff with jitter
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"Attempt {attempt + 1} failed. Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
    
    def safe_execute(self, task, timeout=30):
        """Execute with timeout protection."""
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Operation timed out")
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)
        
        try:
            result = self.run_with_retry(task)
            signal.alarm(0)  # Cancel timeout
            return result
        except TimeoutError:
            signal.alarm(0)
            return "I apologize, but the operation took too long to complete."

# Create production-ready agent
production_agent = ProductionAgent(advanced_executor)

# Test production features
print("Testing production agent with retry logic:")
result = production_agent.safe_execute("What is the meaning of life?")
print(result)
```

### Monitoring and Logging

Implement comprehensive monitoring:

```python
import logging
from datetime import datetime
import json

class AgentMonitor:
    def __init__(self, log_file="agent_activity.log"):
        self.setup_logging(log_file)
        self.session_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "total_cost": 0.0
        }
    
    def setup_logging(self, log_file):
        """Set up structured logging."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def log_request(self, request_data, response_data, metrics, success=True):
        """Log agent interaction."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "request": request_data,
            "response": response_data[:500] + "..." if len(response_data) > 500 else response_data,
            "metrics": metrics,
            "success": success
        }
        
        if success:
            self.logger.info(f"Agent request successful: {json.dumps(log_entry, indent=2)}")
            self.session_stats["successful_requests"] += 1
        else:
            self.logger.error(f"Agent request failed: {json.dumps(log_entry, indent=2)}")
            self.session_stats["failed_requests"] += 1
        
        self.session_stats["total_requests"] += 1
        self.session_stats["total_tokens"] += metrics.get("tokens", 0)
        self.session_stats["total_cost"] += metrics.get("cost", 0.0)
    
    def get_session_stats(self):
        """Get current session statistics."""
        return self.session_stats.copy()
    
    def reset_stats(self):
        """Reset session statistics."""
        self.session_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "total_cost": 0.0
        }

# Create monitored agent
monitor = AgentMonitor()

class MonitoredAgent(ProductionAgent):
    def __init__(self, agent_executor, monitor):
        super().__init__(agent_executor)
        self.monitor = monitor
    
    def run_with_monitoring(self, task):
        """Execute agent with monitoring."""
        start_time = datetime.now()
        
        try:
            with get_openai_callback() as cb:
                result = self.run_with_retry(task)
                
                metrics = {
                    "tokens": cb.total_tokens,
                    "cost": cb.total_cost,
                    "response_time": (datetime.now() - start_time).total_seconds()
                }
                
                self.monitor.log_request(
                    request_data={"task": task},
                    response_data=result,
                    metrics=metrics,
                    success=True
                )
                
                return result
                
        except Exception as e:
            metrics = {
                "error": str(e),
                "response_time": (datetime.now() - start_time).total_seconds()
            }
            
            self.monitor.log_request(
                request_data={"task": task},
                response_data=str(e),
                metrics=metrics,
                success=False
            )
            
            raise

# Test monitored agent
monitored_agent = MonitoredAgent(advanced_executor, monitor)
result = monitored_agent.run_with_monitoring("Explain the concept of machine learning")
print("Result:", result)
print("Session Stats:", monitor.get_session_stats())
```

---

## Best Practices and Tips {#best-practices}

### Prompt Engineering Best Practices

1. **Be Specific and Clear**
```python
# Bad prompt
prompt = "Tell me about AI"

# Good prompt
prompt = """
Explain artificial intelligence for a business audience. Focus on:
1. Current business applications
2. ROI considerations
3. Implementation challenges
4. Future trends
Keep the response under 500 words.
"""
```

2. **Use Few-Shot Examples**
```python
few_shot_prompt = """
Classify the sentiment of the following text as Positive, Negative, or Neutral.

Examples:
Text: "I love this new feature!" -> Sentiment: Positive
Text: "The service was terrible." -> Sentiment: Negative  
Text: "The product works as expected." -> Sentiment: Neutral

Text: "{text}" -> Sentiment:
"""
```

3. **Chain of Thought Reasoning**
```python
cot_prompt = """
Solve this step-by-step:
Problem: {problem}

Step 1: Understand what the problem is asking
Step 2: Identify the key information
Step 3: Plan the solution approach
Step 4: Execute the solution
Step 5: Verify the answer

Answer:
"""
```

### Performance Optimization

1. **Caching Responses**
```python
from langchain.cache import InMemoryCache
from langchain.globals import set_llm_cache

# Enable caching
set_llm_cache(InMemoryCache())

# Subsequent identical calls will be cached
response1 = llm.invoke("What is LangChain?")
response2 = llm.invoke("What is LangChain?")  # Cached response
```

2. **Batch Processing**
```python
# Process multiple inputs efficiently
batch_prompts = [
    "Explain quantum computing",
    "What is machine learning?", 
    "How does blockchain work?"
]

batch_responses = llm.batch(batch_prompts)
```

3. **Model Selection**
```python
# Choose appropriate model for the task
simple_llm = ChatOpenAI(model="gpt-3.5-turbo")  # For simple tasks
complex_llm = ChatOpenAI(model="gpt-4")  # For complex reasoning
```

### Security Considerations

1. **Input Validation**
```python
def validate_input(user_input):
    """Validate user input for security."""
    # Check for injection attempts
    dangerous_patterns = ["system:", "ignore previous", "new instruction"]
    
    for pattern in dangerous_patterns:
        if pattern.lower() in user_input.lower():
            raise ValueError("Invalid input detected")
    
    return True
```

2. **Output Sanitization**
```python
def sanitize_output(output):
    """Sanitize model output."""
    # Remove any potential code execution
    import re
    output = re.sub(r'```python.*?```', '', output, flags=re.DOTALL)
    return output
```

---

## Resources and Next Steps {#resources}

### Official Documentation

1. **LangChain Documentation**: https://python.langchain.com/docs/get_started/introduction
2. **Deep Agents Framework**: https://docs.langchain.com/oss/python/deepagents/overview
3. **LangSmith for Monitoring**: https://smith.langchain.com/

### GitHub Repositories

1. **LangChain Core**: https://github.com/langchain-ai/langchain
2. **Deep Agents**: https://github.com/langchain-ai/deepagents
3. **Deep Agents Quickstarts**: https://github.com/langchain-ai/deepagents-quickstarts
4. **Community Examples**: https://github.com/langchain-ai/langchain/tree/master/cookbook

### Learning Resources

1. **LangChain YouTube Channel**: https://www.youtube.com/@LangChain
2. **LangChain Discord Community**: https://discord.gg/langchain
3. **Official Blog**: https://blog.langchain.dev/
4. **Tutorial Series**: https://python.langchain.com/docs/tutorials/

### Advanced Topics to Explore

1. **Multi-Modal Agents**: Working with images, audio, and video
2. **Federated Learning**: Distributed agent systems
3. **Real-time Processing**: Streaming and WebSocket integration
4. **Custom Model Integration**: Using local or custom models
5. **Enterprise Integration**: Connecting to enterprise systems

### Production Tools and Services

1. **LangSmith**: Debugging, monitoring, and testing platform
2. **LangServe**: Deploy chains and agents as REST APIs
3. **Vector Databases**: Pinecone, Weaviate, Chroma for memory
4. **Monitoring Tools**: Langfuse, Arize AI for observability

### Community and Support

1. **Stack Overflow**: Tag questions with `langchain`
2. **Reddit**: r/LangChain community
3. **Twitter/X**: Follow @LangChainAI for updates
4. **Weekly Office Hours**: Join community calls

---

## Conclusion

You've now journeyed from LangChain basics to building sophisticated deep agents! Here's what we've covered:

✅ **Fundamentals**: Setting up LangChain and understanding core components
✅ **Chains**: Building simple to complex chain patterns  
✅ **Agents**: Creating intelligent agents with tool access
✅ **Deep Agents**: Implementing hierarchical and self-reflecting systems
✅ **Production**: Error handling, monitoring, and deployment strategies
✅ **Best Practices**: Optimization, security, and performance tips

### Your Next Steps

1. **Build a Project**: Apply what you've learned to a real problem
2. **Explore the Community**: Join discussions and learn from others
3. **Contribute**: Consider contributing to open-source projects
4. **Stay Updated**: Follow LangChain's rapid development

The field of AI agents is evolving rapidly, and LangChain provides the perfect foundation to build the next generation of intelligent applications. Keep experimenting, learning, and building!

---

*This guide represents a comprehensive journey through LangChain's capabilities. As the framework continues to evolve, new features and patterns will emerge. Stay curious and keep building!*