---
title: "The Power of the React Loop: Zero-to-Production Guide"
date: "2025-12-28T04:50:00+02:00"
draft: false
tags: ["react loop", "agentic loops", "ai agents", "llm", "production ai", "planning"]
---

## Introduction

Most LLM systems are fundamentally reactive: you ask a question, they generate an answer, and that's it. If the first answer is wrong, there's no self-correction. If the task requires multiple steps, there's no iteration. If results don't meet expectations, there's no refinement.

**The React Loop** changes this paradigm entirely. It transforms a static, one-shot LLM system into a dynamic, iterative agent that can:
- **Sense** its environment and gather context
- **Reason** about what actions to take
- **Act** by executing tools and generating responses
- **Observe** the results of its actions
- **Evaluate** whether it succeeded or needs to try again
- **Learn** from outcomes to improve future iterations

**The core insight:**
> Real-world problems rarely have single-shot solutions. They require iteration, feedback, and refinement—exactly what the React Loop provides.

**Think of it as:**
- A closed-loop control system for AI agents
- The OODA loop (Observe-Orient-Decide-Act) for LLMs
- Test-driven development for AI reasoning
- Continuous integration for agent decision-making

**Why this matters:**

Traditional approaches are fundamentally limited:

| Single-Shot LLM | RAG System | React Loop Agent |
|-----------------|------------|------------------|
| Generate once, hope it's right | Retrieve once, generate | Iterate until successful |
| No error recovery | No retrieval refinement | Self-correcting |
| Linear execution | Static retrieval | Dynamic planning |
| Not auditable | Limited observability | Full traceability |

**When React Loops shine:**
- Complex multi-step tasks (system debugging, data analysis)
- Uncertain environments (incomplete information, changing requirements)
- Quality-critical outputs (code generation, research synthesis)
- Multi-tool orchestration (file operations, API calls, database queries)

**What you'll learn:**
1. The six-layer architecture of React Loops
2. Three production implementation patterns (planning, RAG, multi-agent)
3. Loop control logic and termination conditions
4. Memory integration for cross-iteration consistency
5. Safety, observability, and failure mode handling
6. Complete Python implementation with real examples

This guide takes you from understanding the fundamentals to deploying production-grade React Loop agents that can solve complex problems autonomously.

## 1. Why the React Loop Matters

### The limitations of traditional LLM workflows

Traditional LLM systems suffer from fundamental architectural constraints:

**1. Linear execution**

```python
# Traditional approach: One-shot generation
query = "Debug why the authentication service is failing"
response = llm.generate(query)
# If response is incomplete or wrong, you're stuck
```

**Problem:** No mechanism to gather more information, try different approaches, or refine the answer.

**2. Single-shot responses**

```python
# Traditional RAG
query = "What caused the production outage yesterday?"
context = vector_db.search(query, top_k=5)
answer = llm.generate(f"Context: {context}\nQuestion: {query}")

# What if the retrieved context doesn't contain the root cause?
# What if you need to search logs, then metrics, then recent deployments?
# Traditional system: Give up or return incomplete answer
```

**Problem:** Cannot iterate on retrieval or explore multiple sources.

**3. Hard to debug**

```python
# Traditional system
result = black_box_llm(query)

# Why did it produce this output?
# What information did it consider?
# Where did reasoning go wrong?
# → No visibility into decision process
```

**Problem:** Opaque reasoning, no audit trail, impossible to debug failures.

**4. Poor at iterative problem-solving**

```python
# Traditional approach to complex task
query = "Find all security vulnerabilities in this codebase and fix them"
response = llm.generate(query)

# Requires:
# 1. Understand codebase structure
# 2. Identify vulnerability patterns
# 3. Check each file
# 4. Generate fixes
# 5. Verify fixes don't break functionality
# → Too complex for single-shot generation
```

**Problem:** Multi-step tasks require planning, execution, validation, and refinement—impossible in one shot.

### What the React Loop solves

**1. Iteration over actions**

```python
# React Loop approach
loop = ReactLoop(max_iterations=10)

iteration = 0
while not loop.is_complete():
    # Try, evaluate, refine, repeat
    action = loop.plan_next_action()
    result = loop.execute(action)
    evaluation = loop.evaluate(result)

    if evaluation.success:
        break
    else:
        loop.refine_approach(evaluation.feedback)
```

**Benefit:** Can try multiple approaches until success.

**2. Feedback incorporation**

```python
# Iteration 1
action = "Search logs for 'error'"
result = "Found 1000 errors"
evaluation = "Too broad, need to filter"

# Iteration 2 (refined based on feedback)
action = "Search logs for 'authentication error' in last hour"
result = "Found 3 relevant errors"
evaluation = "Specific enough, proceed with analysis"
```

**Benefit:** Each iteration improves based on previous results.

**3. Dynamic planning**

```python
# React Loop adjusts plan based on what it discovers
initial_plan = ["Check service health", "Review logs", "Analyze metrics"]

# After checking service health, discovers unexpected issue
revised_plan = [
    "Investigate database connection pool exhaustion",  # New priority
    "Check recent configuration changes",
    "Review resource utilization"
]
```

**Benefit:** Adapts strategy as new information emerges.

**4. Self-monitoring**

```python
# React Loop tracks its own progress
loop_state = {
    "iterations": 3,
    "confidence": 0.65,  # Not yet confident
    "actions_taken": ["search_logs", "query_database", "check_config"],
    "findings": ["connection_timeout", "pool_exhausted"],
    "next_action": "investigate_pool_configuration"
}

# Can make meta-decisions: "I'm not making progress, try different approach"
```

**Benefit:** Awareness of progress, ability to change strategy when stuck.

### The result: Autonomous, auditable agents

**Autonomous:**
```python
# Agent handles complex task end-to-end
task = "Find and fix the production authentication bug"

agent = ReactLoopAgent(task)
result = agent.run()

# Agent internally:
# - Checked logs (iteration 1)
# - Found error pattern (iteration 2)
# - Traced to configuration (iteration 3)
# - Generated fix (iteration 4)
# - Validated fix (iteration 5)
# - Deployed (iteration 6)
```

**Auditable:**
```python
# Full audit trail of decision process
print(agent.get_trace())

"""
Iteration 1: Searched logs for authentication errors
  Action: search_logs(pattern='auth', time_range='1h')
  Result: Found 47 errors
  Evaluation: Too many, need to narrow down

Iteration 2: Filtered to critical errors
  Action: search_logs(pattern='auth AND severity:critical')
  Result: Found 3 errors, all from auth-service
  Evaluation: Specific, proceed to root cause

Iteration 3: Analyzed auth-service configuration
  Action: read_config('auth-service')
  Result: Found misconfigured JWT secret rotation
  Evaluation: Root cause identified

...
"""
```

## 2. Mental Model

### The six-phase control loop

Think of the React Loop as a closed-loop control system for AI agents:

```
┌─────────────────────────────────────────────────────────┐
│                    React Loop Cycle                     │
└─────────────────────────────────────────────────────────┘

   ┌──────────────┐
   │  Perception  │  ← Sense environment, gather context
   └──────┬───────┘
          ↓
   ┌──────────────┐
   │   Reasoning  │  ← Plan next action, prioritize
   └──────┬───────┘
          ↓
   ┌──────────────┐
   │    Action    │  ← Execute tools, generate output
   └──────┬───────┘
          ↓
   ┌──────────────┐
   │ Observation  │  ← Gather results, logs, metrics
   └──────┬───────┘
          ↓
   ┌──────────────┐
   │  Evaluation  │  ← Check success, identify issues
   └──────┬───────┘
          ↓
   ┌──────────────┐
   │Memory Update │  ← Store learnings, update state
   └──────┬───────┘
          ↓
          ↺ (Repeat until complete or max iterations)
```

### The six layers explained

**Layer 1: Perception**
- **Purpose:** Understand current state
- **Inputs:** User query, environment state, memory, tool outputs
- **Outputs:** Normalized context for reasoning

**Layer 2: Reasoning**
- **Purpose:** Decide what to do next
- **Inputs:** Perception context, goal, past actions
- **Outputs:** Structured action plan

**Layer 3: Action**
- **Purpose:** Execute decisions
- **Inputs:** Action plan from reasoning
- **Outputs:** Tool results, generated responses

**Layer 4: Observation**
- **Purpose:** Gather execution results
- **Inputs:** Action outputs, logs, metrics
- **Outputs:** Structured observations

**Layer 5: Evaluation**
- **Purpose:** Assess progress toward goal
- **Inputs:** Observations, goal, success criteria
- **Outputs:** Success/failure signal, confidence score, feedback

**Layer 6: Memory Update**
- **Purpose:** Learn from iteration
- **Inputs:** Actions taken, results, evaluation
- **Outputs:** Updated memory state

### Concrete example: Debugging workflow

```python
# Task: "Find why API response time increased"

# Iteration 1
Perception: User reports slow API, no other context
Reasoning: Need to gather metrics first
Action: query_metrics(service='api', metric='latency', time_range='24h')
Observation: Latency increased from 100ms to 800ms at 2pm
Evaluation: Found when, but not why. Need to investigate further.
Memory Update: Store timestamp of latency spike

# Iteration 2
Perception: Latency spike at 2pm, need to find cause
Reasoning: Check what changed around 2pm
Action: query_deployment_log(time_range='1pm-3pm')
Observation: Deployment of v2.3.1 at 1:55pm
Evaluation: Correlation found, but need to confirm causation
Memory Update: Store deployment as potential cause

# Iteration 3
Perception: Deployment v2.3.1 correlates with latency increase
Reasoning: Compare v2.3.1 changes to v2.3.0
Action: git_diff(from='v2.3.0', to='v2.3.1')
Observation: Added synchronous database call in hot path
Evaluation: Root cause identified! Synchronous call blocks requests.
Memory Update: Store root cause: synchronous DB call added

# Iteration 4
Perception: Root cause is synchronous DB call
Reasoning: Need to fix by making it asynchronous
Action: generate_fix(issue='synchronous_db_call', approach='async')
Observation: Generated code patch using async/await
Evaluation: Fix looks correct, need to validate
Memory Update: Store proposed fix

# Iteration 5
Perception: Have proposed fix, need validation
Reasoning: Run tests to ensure fix works
Action: run_tests(patch='async_db_fix.patch')
Observation: All tests pass, latency reduced to 120ms in staging
Evaluation: Fix validated! Ready to deploy.
Memory Update: Mark task complete
```

**Key insight:** Each iteration builds on previous learnings, progressively narrowing toward the solution.

## 3. Core Components of a React Loop

### 3.1 Perception Layer

**Purpose:** Collect and normalize all relevant context for decision-making.

**Implementation:**

```python
class PerceptionLayer:
    def __init__(self, memory: AgentMemory, tools: ToolRegistry):
        self.memory = memory
        self.tools = tools

    async def perceive(
        self,
        user_input: str,
        iteration: int
    ) -> PerceptionContext:
        """
        Gather all context needed for reasoning
        """
        # 1. User input (current query or feedback)
        normalized_input = self.normalize_input(user_input)

        # 2. Memory (what agent knows)
        working_memory = self.memory.get_working_memory()
        long_term_memory = self.memory.relevant_memories(user_input)

        # 3. Environment state (tool availability, system status)
        available_tools = self.tools.list_available()
        system_state = self.get_system_state()

        # 4. Past actions (what's been tried)
        action_history = self.memory.get_action_history()

        return PerceptionContext(
            input=normalized_input,
            working_memory=working_memory,
            long_term_memory=long_term_memory,
            available_tools=available_tools,
            system_state=system_state,
            action_history=action_history,
            iteration=iteration
        )
```

**Example perception context:**

```python
perception = PerceptionContext(
    input="Find security vulnerabilities in authentication code",
    working_memory={
        "task": "security_audit",
        "target": "auth_service",
        "files_checked": ["auth.py", "jwt.py"],
        "findings": ["weak_password_hash"]
    },
    long_term_memory=[
        "User prefers detailed security reports",
        "Previous audit found XSS vulnerabilities"
    ],
    available_tools=[
        "read_file", "grep", "static_analysis", "run_tests"
    ],
    system_state={
        "codebase": "/app/auth",
        "language": "python"
    },
    action_history=[
        {"action": "read_file", "file": "auth.py", "result": "success"},
        {"action": "static_analysis", "tool": "bandit", "result": "3 issues"}
    ],
    iteration=2
)
```

### 3.2 Reasoning Layer

**Purpose:** Generate the next action plan based on current context.

**Implementation:**

```python
class ReasoningLayer:
    def __init__(self, llm: LLM):
        self.llm = llm

    async def reason(
        self,
        context: PerceptionContext
    ) -> ActionPlan:
        """
        Decide what to do next
        """
        prompt = f"""
        You are an autonomous agent working on a task.

        Current situation:
        Task: {context.input}
        Iteration: {context.iteration}
        Working memory: {context.working_memory}
        Past actions: {context.action_history}

        Available tools: {context.available_tools}

        Based on this context, what should be the next action?

        Respond in JSON format:
        {{
            "reasoning": "Why this action makes sense",
            "action": "tool_name",
            "parameters": {{}},
            "expected_outcome": "What we expect to learn/achieve",
            "confidence": 0.0-1.0
        }}
        """

        response = await self.llm.generate(prompt)
        plan = ActionPlan.from_json(response)

        return plan
```

**Example reasoning output:**

```python
plan = ActionPlan(
    reasoning="Found weak password hashing in auth.py. Need to check if JWT implementation has timing vulnerabilities.",
    action="static_analysis",
    parameters={
        "tool": "semgrep",
        "rules": "jwt-security",
        "target": "jwt.py"
    },
    expected_outcome="Identify timing attack vulnerabilities in JWT validation",
    confidence=0.85
)
```

### 3.3 Action Layer

**Purpose:** Execute the planned action safely and return results.

**Implementation:**

```python
class ActionLayer:
    def __init__(self, tools: ToolRegistry, safety: SafetyChecker):
        self.tools = tools
        self.safety = safety

    async def execute(
        self,
        plan: ActionPlan
    ) -> ActionResult:
        """
        Execute action with safety checks
        """
        # 1. Pre-execution safety check
        if not self.safety.is_safe(plan):
            return ActionResult(
                success=False,
                error="Action blocked by safety policy",
                details=self.safety.explain_block(plan)
            )

        # 2. Execute tool
        try:
            tool = self.tools.get(plan.action)
            result = await tool.execute(**plan.parameters)

            return ActionResult(
                success=True,
                data=result,
                execution_time=result.elapsed_ms,
                logs=result.logs
            )

        except Exception as e:
            return ActionResult(
                success=False,
                error=str(e),
                exception_type=type(e).__name__
            )
```

**Example action execution:**

```python
# Action: Run security analysis
action_result = ActionResult(
    success=True,
    data={
        "tool": "semgrep",
        "findings": [
            {
                "rule": "jwt-timing-attack",
                "severity": "high",
                "file": "jwt.py",
                "line": 42,
                "message": "JWT signature comparison vulnerable to timing attacks"
            }
        ]
    },
    execution_time=1250,  # ms
    logs=["Scanned jwt.py", "Applied 15 security rules", "Found 1 high severity issue"]
)
```

### 3.4 Observation Layer

**Purpose:** Standardize action results for evaluation.

**Implementation:**

```python
class ObservationLayer:
    async def observe(
        self,
        action: ActionPlan,
        result: ActionResult
    ) -> Observation:
        """
        Structure results for evaluation
        """
        return Observation(
            action_taken=action.action,
            parameters=action.parameters,
            success=result.success,
            data=result.data,
            error=result.error if not result.success else None,
            execution_time=result.execution_time,
            logs=result.logs,
            timestamp=datetime.utcnow()
        )
```

### 3.5 Evaluation Layer

**Purpose:** Assess whether the action moved us closer to the goal.

**Implementation:**

```python
class EvaluationLayer:
    def __init__(self, llm: LLM):
        self.llm = llm

    async def evaluate(
        self,
        goal: str,
        observation: Observation,
        memory: AgentMemory
    ) -> Evaluation:
        """
        Determine if we're making progress
        """
        prompt = f"""
        Goal: {goal}

        Action taken: {observation.action_taken}
        Parameters: {observation.parameters}
        Result: {observation.data}
        Success: {observation.success}

        Previous findings: {memory.get_findings()}

        Evaluate:
        1. Did this action help achieve the goal?
        2. What did we learn?
        3. Should we continue, refine approach, or stop?
        4. Confidence in current progress (0-1)

        Respond in JSON format:
        {{
            "progress_made": true/false,
            "learnings": ["key insight 1", "key insight 2"],
            "next_step": "continue" / "refine" / "stop",
            "confidence": 0.0-1.0,
            "feedback": "What to do differently next time"
        }}
        """

        response = await self.llm.generate(prompt)
        evaluation = Evaluation.from_json(response)

        return evaluation
```

**Example evaluation:**

```python
evaluation = Evaluation(
    progress_made=True,
    learnings=[
        "JWT implementation has timing attack vulnerability on line 42",
        "Using string comparison instead of constant-time comparison"
    ],
    next_step="continue",  # Found issue, now need to generate fix
    confidence=0.90,
    feedback="Found critical security issue. Next: generate fix using constant-time comparison."
)
```

### 3.6 Memory Update Layer

**Purpose:** Store learnings and update state for next iteration.

**Implementation:**

```python
class MemoryUpdateLayer:
    def __init__(self, memory: AgentMemory):
        self.memory = memory

    async def update(
        self,
        action: ActionPlan,
        observation: Observation,
        evaluation: Evaluation
    ) -> None:
        """
        Update agent memory with new information
        """
        # 1. Update action history
        self.memory.add_action(
            action=action.action,
            parameters=action.parameters,
            result=observation.data,
            success=observation.success
        )

        # 2. Store learnings
        for learning in evaluation.learnings:
            self.memory.add_learning(learning)

        # 3. Update working memory
        if evaluation.progress_made:
            self.memory.update_working_memory(
                findings=evaluation.learnings,
                confidence=evaluation.confidence
            )

        # 4. Store for long-term if significant
        if evaluation.confidence > 0.8:
            self.memory.store_long_term(
                task_type="security_audit",
                finding=evaluation.learnings,
                confidence=evaluation.confidence
            )
```

## 4. Loop Control Logic

### 4.1 Iteration Rules

**Critical:** React Loops must have bounded execution to prevent runaway behavior.

**Implementation:**

```python
class LoopController:
    def __init__(
        self,
        max_iterations: int = 10,
        success_threshold: float = 0.9,
        timeout_seconds: int = 300
    ):
        self.max_iterations = max_iterations
        self.success_threshold = success_threshold
        self.timeout_seconds = timeout_seconds
        self.start_time = None

    def should_continue(
        self,
        iteration: int,
        evaluation: Evaluation
    ) -> Tuple[bool, str]:
        """
        Determine if loop should continue

        Returns: (should_continue, reason)
        """
        # 1. Check max iterations
        if iteration >= self.max_iterations:
            return False, f"Max iterations reached ({self.max_iterations})"

        # 2. Check success threshold
        if evaluation.confidence >= self.success_threshold:
            return False, f"Success threshold met (confidence: {evaluation.confidence:.2%})"

        # 3. Check timeout
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed > self.timeout_seconds:
                return False, f"Timeout reached ({elapsed:.1f}s)"

        # 4. Check evaluation signal
        if evaluation.next_step == "stop":
            return False, "Agent decided to stop"

        # 5. Check repeated failures
        if self._detect_stagnation(evaluation):
            return False, "No progress in last 3 iterations"

        # Continue iterating
        return True, "Continuing iteration"

    def _detect_stagnation(self, evaluation: Evaluation) -> bool:
        """Detect if agent is stuck"""
        # Track last N evaluations
        recent_evaluations = self.evaluation_history[-3:]

        if len(recent_evaluations) < 3:
            return False

        # All recent iterations made no progress
        no_progress = all(not e.progress_made for e in recent_evaluations)

        # Confidence not improving
        confidence_flat = (
            recent_evaluations[-1].confidence - recent_evaluations[0].confidence < 0.05
        )

        return no_progress and confidence_flat
```

**Example usage:**

```python
controller = LoopController(
    max_iterations=10,
    success_threshold=0.90,
    timeout_seconds=300  # 5 minutes
)

iteration = 0
while True:
    # Execute iteration
    evaluation = agent.iterate()

    # Check if should continue
    should_continue, reason = controller.should_continue(iteration, evaluation)

    if not should_continue:
        print(f"Loop terminating: {reason}")
        break

    iteration += 1
```

### 4.2 Decision Criteria

**Factors that influence loop termination:**

**1. Confidence levels**

```python
class ConfidenceBasedControl:
    def __init__(self):
        self.confidence_thresholds = {
            "critical_task": 0.95,  # High stakes, need high confidence
            "exploratory": 0.70,    # Discovery mode, lower threshold
            "routine": 0.85         # Standard tasks
        }

    def should_stop(
        self,
        task_type: str,
        current_confidence: float
    ) -> bool:
        threshold = self.confidence_thresholds.get(task_type, 0.85)
        return current_confidence >= threshold
```

**2. Task completeness**

```python
class TaskCompletenessChecker:
    def __init__(self, goal: str):
        self.goal = goal
        self.required_steps = self.decompose_goal(goal)
        self.completed_steps = set()

    def is_complete(self) -> bool:
        """Check if all required steps are done"""
        return self.completed_steps >= set(self.required_steps)

    def mark_complete(self, step: str):
        """Mark step as completed"""
        if step in self.required_steps:
            self.completed_steps.add(step)
```

**3. Resource limits**

```python
class ResourceLimits:
    def __init__(
        self,
        max_cost_usd: float = 1.0,
        max_api_calls: int = 50,
        max_time_seconds: int = 600
    ):
        self.max_cost = max_cost_usd
        self.max_api_calls = max_api_calls
        self.max_time = max_time_seconds

        self.current_cost = 0.0
        self.current_api_calls = 0
        self.start_time = time.time()

    def check_limits(self) -> Tuple[bool, Optional[str]]:
        """Returns (within_limits, violation_message)"""
        if self.current_cost > self.max_cost:
            return False, f"Cost limit exceeded (${self.current_cost:.2f})"

        if self.current_api_calls > self.max_api_calls:
            return False, f"API call limit exceeded ({self.current_api_calls})"

        elapsed = time.time() - self.start_time
        if elapsed > self.max_time:
            return False, f"Time limit exceeded ({elapsed:.1f}s)"

        return True, None

    def record_call(self, cost: float):
        """Record API call and cost"""
        self.current_cost += cost
        self.current_api_calls += 1
```

## 5. Implementation Patterns

### Pattern 1: Agentic Planning Loop

**Use case:** Complex tasks requiring dynamic planning and execution.

**Architecture:**

```python
class AgenticPlanningLoop:
    def __init__(self, llm: LLM, tools: ToolRegistry):
        self.llm = llm
        self.tools = tools
        self.memory = AgentMemory()

    async def run(self, goal: str) -> Result:
        """
        Execute agentic planning loop
        """
        # Initialize
        self.memory.set_goal(goal)
        iteration = 0
        max_iterations = 10

        while iteration < max_iterations:
            # 1. Perceive current state
            context = await self.perceive(goal, iteration)

            # 2. Generate plan for next action
            plan = await self.plan(context)

            # 3. Check plan feasibility
            if not self.is_feasible(plan):
                plan = await self.revise_plan(plan, "infeasible")

            # 4. Execute action
            result = await self.execute(plan)

            # 5. Evaluate outcome
            evaluation = await self.evaluate(goal, result)

            # 6. Update memory
            await self.update_memory(plan, result, evaluation)

            # 7. Check if done
            if evaluation.task_complete:
                return Result(
                    success=True,
                    output=evaluation.final_output,
                    trace=self.memory.get_trace()
                )

            # 8. Revise plan if needed
            if not evaluation.on_track:
                await self.revise_strategy(evaluation.feedback)

            iteration += 1

        # Max iterations reached
        return Result(
            success=False,
            error="Max iterations reached without completing goal",
            trace=self.memory.get_trace()
        )

    async def plan(self, context: Context) -> Plan:
        """Generate next action plan"""
        prompt = f"""
        Goal: {context.goal}
        Current progress: {context.progress}
        Available tools: {context.tools}
        Past actions: {context.history}

        What should be the next action to achieve the goal?
        Provide plan in JSON: {{"action": "...", "parameters": {{...}}, "reasoning": "..."}}
        """

        response = await self.llm.generate(prompt)
        return Plan.from_json(response)

    def is_feasible(self, plan: Plan) -> bool:
        """Check if plan can be executed"""
        # Check tool availability
        if plan.action not in self.tools.available():
            return False

        # Check parameter validity
        tool = self.tools.get(plan.action)
        if not tool.validate_parameters(plan.parameters):
            return False

        # Check resource constraints
        if not self.resources.can_afford(plan.estimated_cost):
            return False

        return True

    async def revise_plan(self, plan: Plan, reason: str) -> Plan:
        """Revise infeasible plan"""
        prompt = f"""
        Original plan: {plan}
        Issue: {reason}

        Provide alternative plan that addresses the issue.
        """

        response = await self.llm.generate(prompt)
        return Plan.from_json(response)
```

**Example execution:**

```python
# Task: "Analyze security vulnerabilities and generate fixes"

loop = AgenticPlanningLoop(llm=gpt4, tools=security_tools)
result = await loop.run("Find and fix all security vulnerabilities in auth module")

# Trace shows:
# Iteration 1: Plan: scan_codebase() → Found 5 files
# Iteration 2: Plan: static_analysis(tool='bandit') → Found 3 issues
# Iteration 3: Plan: analyze_issue(issue_id=1) → SQL injection risk
# Iteration 4: Plan: generate_fix(issue_id=1) → Parameterized queries
# Iteration 5: Plan: test_fix(fix_id=1) → Tests pass
# Iteration 6: Plan: analyze_issue(issue_id=2) → XSS vulnerability
# ...
```

### Pattern 2: RAG React Loop

**Use case:** Iterative retrieval and answer generation.

**Architecture:**

```python
class RAGReactLoop:
    def __init__(
        self,
        llm: LLM,
        vector_store: VectorStore,
        graph_store: Optional[GraphStore] = None
    ):
        self.llm = llm
        self.vector_store = vector_store
        self.graph_store = graph_store

    async def run(self, query: str) -> Answer:
        """
        Iteratively retrieve and generate until confident
        """
        iteration = 0
        max_iterations = 5
        retrieved_context = []

        while iteration < max_iterations:
            # 1. Retrieve relevant information
            if iteration == 0:
                # Initial semantic search
                docs = await self.vector_store.search(query, top_k=5)
            else:
                # Refined search based on gaps
                refined_query = self.refine_query(query, gaps)
                docs = await self.vector_store.search(refined_query, top_k=5)

            retrieved_context.extend(docs)

            # 2. Generate answer from context
            answer = await self.generate_answer(query, retrieved_context)

            # 3. Evaluate quality
            evaluation = await self.evaluate_answer(query, answer, retrieved_context)

            # 4. Check if good enough
            if evaluation.confidence > 0.85 and not evaluation.has_gaps:
                return Answer(
                    text=answer,
                    sources=retrieved_context,
                    confidence=evaluation.confidence,
                    iterations=iteration + 1
                )

            # 5. Identify gaps and iterate
            gaps = evaluation.identified_gaps

            # Optional: Use graph traversal for missing info
            if self.graph_store and gaps:
                graph_docs = await self.graph_traverse(gaps)
                retrieved_context.extend(graph_docs)

            iteration += 1

        # Return best effort
        return Answer(
            text=answer,
            sources=retrieved_context,
            confidence=evaluation.confidence,
            iterations=iteration,
            warning="Max iterations reached, answer may be incomplete"
        )

    def refine_query(self, original_query: str, gaps: List[str]) -> str:
        """Reformulate query to address gaps"""
        prompt = f"""
        Original query: {original_query}
        Information gaps: {gaps}

        Reformulate the query to better retrieve missing information.
        """

        return self.llm.generate(prompt)

    async def evaluate_answer(
        self,
        query: str,
        answer: str,
        context: List[Doc]
    ) -> Evaluation:
        """Evaluate answer quality and identify gaps"""
        prompt = f"""
        Query: {query}
        Generated answer: {answer}
        Retrieved context: {context}

        Evaluate:
        1. Does the answer fully address the query?
        2. Is the answer grounded in the retrieved context?
        3. What information is missing (gaps)?
        4. Confidence level (0-1)?

        Return JSON: {{"confidence": 0.8, "has_gaps": false, "identified_gaps": []}}
        """

        response = await self.llm.generate(prompt)
        return Evaluation.from_json(response)
```

### Pattern 3: Multi-Agent Loops

**Use case:** Complex tasks requiring coordination of specialized agents.

**Architecture:**

```python
class MultiAgentLoop:
    def __init__(
        self,
        master: LLM,
        sub_agents: Dict[str, Agent]
    ):
        self.master = master
        self.sub_agents = sub_agents

    async def run(self, task: str) -> Result:
        """
        Master coordinates sub-agents to complete task
        """
        # 1. Master decomposes task
        subtasks = await self.decompose_task(task)

        # 2. Assign subtasks to specialized agents
        assignments = self.assign_subtasks(subtasks)

        # 3. Execute sub-agents in parallel or sequence
        results = {}
        for agent_name, subtask in assignments.items():
            agent = self.sub_agents[agent_name]
            result = await agent.run(subtask)
            results[agent_name] = result

        # 4. Master evaluates results
        evaluation = await self.evaluate_results(task, results)

        # 5. If incomplete, iterate
        if not evaluation.complete:
            # Identify what's missing
            missing = evaluation.missing_elements

            # Re-assign or refine
            refined_assignments = self.refine_assignments(missing)
            additional_results = await self.execute_agents(refined_assignments)

            # Merge results
            results.update(additional_results)

        # 6. Master synthesizes final output
        final = await self.synthesize(task, results)

        return Result(
            success=True,
            output=final,
            sub_results=results
        )

    async def decompose_task(self, task: str) -> List[Subtask]:
        """Master decomposes complex task"""
        prompt = f"""
        Task: {task}

        Decompose into subtasks that can be handled by specialized agents:
        - Code analysis agent
        - Research agent
        - Testing agent
        - Documentation agent

        Return JSON list of subtasks with assigned agent.
        """

        response = await self.master.generate(prompt)
        return [Subtask.from_json(s) for s in response]

    def assign_subtasks(self, subtasks: List[Subtask]) -> Dict[str, Subtask]:
        """Map subtasks to agents"""
        assignments = {}
        for subtask in subtasks:
            agent_name = subtask.assigned_agent
            if agent_name in self.sub_agents:
                assignments[agent_name] = subtask

        return assignments
```

**Example multi-agent execution:**

```python
# Task: "Conduct full security audit of web application"

master = GPT4()
sub_agents = {
    "code_analyzer": CodeAnalysisAgent(),
    "penetration_tester": PenTestAgent(),
    "compliance_checker": ComplianceAgent(),
    "report_generator": ReportAgent()
}

loop = MultiAgentLoop(master, sub_agents)
result = await loop.run("Security audit of web app")

# Master decomposes:
# 1. Static code analysis → code_analyzer
# 2. Dynamic pen testing → penetration_tester
# 3. Compliance verification → compliance_checker
# 4. Report generation → report_generator

# Each agent runs its own React Loop
# Master synthesizes results into final audit report
```

## 6. Memory & State Integration

### Memory types in React Loops

**1. Working Memory (Current Task)**

```python
class WorkingMemory:
    """Tracks current task state"""
    def __init__(self):
        self.goal = None
        self.current_step = None
        self.completed_steps = []
        self.findings = []
        self.confidence = 0.0

    def update(self, step: str, result: Any, confidence: float):
        """Update after each iteration"""
        self.completed_steps.append(step)
        if result:
            self.findings.append(result)
        self.confidence = max(self.confidence, confidence)

    def get_state(self) -> Dict:
        """Get current state for next iteration"""
        return {
            "goal": self.goal,
            "progress": f"{len(self.completed_steps)} steps completed",
            "findings": self.findings,
            "confidence": self.confidence
        }
```

**2. Long-Term Memory (Knowledge Base)**

```python
class LongTermMemory:
    """Stores accumulated knowledge"""
    def __init__(self, vector_db: VectorStore):
        self.vector_db = vector_db

    async def store(self, knowledge: str, metadata: Dict):
        """Store for future retrieval"""
        await self.vector_db.insert(
            text=knowledge,
            metadata={
                **metadata,
                "timestamp": datetime.utcnow(),
                "task_type": metadata.get("task_type")
            }
        )

    async def recall(self, query: str) -> List[str]:
        """Retrieve relevant past knowledge"""
        results = await self.vector_db.search(query, top_k=3)
        return [r.text for r in results]
```

**3. Procedural Memory (How-To Knowledge)**

```python
class ProceduralMemory:
    """Stores learned procedures"""
    def __init__(self):
        self.procedures = {}

    def learn_procedure(self, task_type: str, steps: List[str]):
        """Learn successful procedure"""
        self.procedures[task_type] = steps

    def get_procedure(self, task_type: str) -> Optional[List[str]]:
        """Retrieve known procedure"""
        return self.procedures.get(task_type)
```

**Integrated memory system:**

```python
class IntegratedMemory:
    def __init__(self):
        self.working = WorkingMemory()
        self.long_term = LongTermMemory(vector_db)
        self.procedural = ProceduralMemory()

    async def prepare_context(self, task: str) -> MemoryContext:
        """Gather all relevant memory for iteration"""
        return MemoryContext(
            working_state=self.working.get_state(),
            relevant_knowledge=await self.long_term.recall(task),
            known_procedures=self.procedural.get_procedure(task)
        )
```

**Why memory matters:**

```python
# Without memory: Each iteration starts from scratch
# Iteration 1: Finds issue A
# Iteration 2: Forgets about A, finds issue B
# Iteration 3: Finds issue A again (duplicate work)

# With memory: Cumulative progress
# Iteration 1: Finds issue A, stores in memory
# Iteration 2: Remembers A, finds issue B, stores both
# Iteration 3: Remembers A and B, finds issue C
# → Builds comprehensive understanding
```

## 7. Safety, Logging, and Observability

### 7.1 Structured Logging

**Implementation:**

```python
class ReactLoopLogger:
    def __init__(self):
        self.iterations = []

    def log_iteration(
        self,
        iteration: int,
        perception: PerceptionContext,
        reasoning: ActionPlan,
        action_result: ActionResult,
        evaluation: Evaluation
    ):
        """Log complete iteration"""
        self.iterations.append({
            "iteration": iteration,
            "timestamp": datetime.utcnow().isoformat(),
            "perception": {
                "input": perception.input,
                "working_memory": perception.working_memory,
                "available_tools": perception.available_tools
            },
            "reasoning": {
                "reasoning": reasoning.reasoning,
                "action": reasoning.action,
                "parameters": reasoning.parameters,
                "confidence": reasoning.confidence
            },
            "action": {
                "success": action_result.success,
                "execution_time_ms": action_result.execution_time,
                "error": action_result.error
            },
            "evaluation": {
                "progress_made": evaluation.progress_made,
                "confidence": evaluation.confidence,
                "next_step": evaluation.next_step
            }
        })

    def export_trace(self) -> str:
        """Export human-readable trace"""
        trace = []
        for it in self.iterations:
            trace.append(f"""
Iteration {it['iteration']}:
  Reasoning: {it['reasoning']['reasoning']}
  Action: {it['reasoning']['action']}({it['reasoning']['parameters']})
  Success: {it['action']['success']}
  Progress: {it['evaluation']['progress_made']}
  Confidence: {it['evaluation']['confidence']:.2%}
            """)

        return "\n".join(trace)
```

### 7.2 Safety Mechanisms

**Pre-execution safety checks:**

```python
class SafetyChecker:
    def __init__(self, policies: List[SafetyPolicy]):
        self.policies = policies

    def is_safe(self, plan: ActionPlan) -> Tuple[bool, Optional[str]]:
        """Check if action is safe to execute"""
        for policy in self.policies:
            is_safe, reason = policy.check(plan)
            if not is_safe:
                return False, f"Blocked by {policy.name}: {reason}"

        return True, None

# Example policies
class NoDestructiveActions(SafetyPolicy):
    def check(self, plan: ActionPlan) -> Tuple[bool, Optional[str]]:
        destructive = ["delete", "drop", "rm", "remove"]
        if any(word in plan.action.lower() for word in destructive):
            return False, "Destructive actions not allowed"
        return True, None

class RateLimitPolicy(SafetyPolicy):
    def __init__(self, max_per_minute: int = 10):
        self.max_per_minute = max_per_minute
        self.call_times = deque()

    def check(self, plan: ActionPlan) -> Tuple[bool, Optional[str]]:
        now = time.time()

        # Remove calls older than 1 minute
        while self.call_times and self.call_times[0] < now - 60:
            self.call_times.popleft()

        if len(self.call_times) >= self.max_per_minute:
            return False, f"Rate limit exceeded ({self.max_per_minute}/min)"

        self.call_times.append(now)
        return True, None
```

### 7.3 Observability

**Metrics to track:**

```python
class ReactLoopMetrics:
    def __init__(self):
        self.metrics = {
            "total_iterations": 0,
            "successful_completions": 0,
            "timeout_failures": 0,
            "max_iteration_failures": 0,
            "avg_iterations_to_complete": 0.0,
            "avg_confidence": 0.0,
            "action_distribution": {},
            "evaluation_trends": []
        }

    def record_completion(
        self,
        iterations: int,
        final_confidence: float,
        actions_used: List[str]
    ):
        """Record successful completion"""
        self.metrics["successful_completions"] += 1
        self.metrics["total_iterations"] += iterations

        # Update averages
        total_completions = self.metrics["successful_completions"]
        self.metrics["avg_iterations_to_complete"] = (
            self.metrics["total_iterations"] / total_completions
        )

        # Track action usage
        for action in actions_used:
            self.metrics["action_distribution"][action] = (
                self.metrics["action_distribution"].get(action, 0) + 1
            )

    def get_dashboard(self) -> Dict:
        """Get metrics for monitoring dashboard"""
        return {
            "success_rate": (
                self.metrics["successful_completions"] /
                (self.metrics["successful_completions"] +
                 self.metrics["timeout_failures"] +
                 self.metrics["max_iteration_failures"])
                if self.metrics["successful_completions"] > 0 else 0.0
            ),
            "avg_iterations": self.metrics["avg_iterations_to_complete"],
            "most_used_actions": sorted(
                self.metrics["action_distribution"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
        }
```

## 8. Failure Modes & Mitigation

### Common failure modes

**1. Infinite loops (runaway iteration)**

**Problem:**
```python
# Agent gets stuck repeating same action
Iteration 1: search_logs("error")
Iteration 2: search_logs("error")  # Same action
Iteration 3: search_logs("error")  # Still same
# → Never makes progress
```

**Mitigation:**
```python
class InfiniteLoopDetector:
    def __init__(self, window_size: int = 3):
        self.action_history = deque(maxlen=window_size)

    def detect(self, action: str) -> bool:
        """Detect if repeating same action"""
        self.action_history.append(action)

        if len(self.action_history) == self.action_history.maxlen:
            # All recent actions are identical
            return len(set(self.action_history)) == 1

        return False

    def intervene(self) -> str:
        """Suggest different approach"""
        return "Detected repeated action. Try alternative approach."
```

**2. Action errors (tool failures)**

**Problem:**
```python
# Tool fails but agent doesn't handle it properly
result = execute_tool("query_database", invalid_params)
# Tool crashes, agent has no recovery strategy
```

**Mitigation:**
```python
class ActionErrorHandler:
    async def execute_with_recovery(
        self,
        action: ActionPlan
    ) -> ActionResult:
        """Execute with error handling and retry"""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                # Pre-condition check
                if not self.validate_preconditions(action):
                    return ActionResult(
                        success=False,
                        error="Preconditions not met"
                    )

                # Execute
                result = await self.execute(action)

                # Post-condition check
                if not self.validate_postconditions(result):
                    return ActionResult(
                        success=False,
                        error="Postconditions not met"
                    )

                return result

            except Exception as e:
                if attempt == max_retries - 1:
                    # Final attempt failed
                    return ActionResult(
                        success=False,
                        error=f"Failed after {max_retries} attempts: {e}"
                    )

                # Retry with exponential backoff
                await asyncio.sleep(2 ** attempt)
```

**3. Hallucinated evaluations (false confidence)**

**Problem:**
```python
# Agent thinks it succeeded but actually failed
evaluation = Evaluation(
    progress_made=True,  # Wrong!
    confidence=0.95,     # Overconfident!
    task_complete=True   # False positive
)
```

**Mitigation:**
```python
class EvaluationVerifier:
    async def verify_evaluation(
        self,
        claimed_evaluation: Evaluation,
        actual_results: ActionResult,
        memory: AgentMemory
    ) -> Evaluation:
        """Verify evaluation against ground truth"""

        # 1. Check if claimed success matches actual result
        if claimed_evaluation.progress_made but not actual_results.success:
            # Hallucination detected
            return Evaluation(
                progress_made=False,
                confidence=0.0,
                feedback="Action failed, progress claim incorrect"
            )

        # 2. Check against memory for consistency
        if self.contradicts_memory(claimed_evaluation, memory):
            return Evaluation(
                progress_made=False,
                confidence=0.0,
                feedback="Evaluation contradicts known facts"
            )

        # 3. If verifiable, check against external source
        if self.can_verify_externally(claimed_evaluation):
            verified = await self.external_verification(claimed_evaluation)
            if not verified:
                claimed_evaluation.confidence *= 0.5  # Reduce confidence

        return claimed_evaluation
```

**4. Resource exhaustion (cost/time blowup)**

**Problem:**
```python
# Agent keeps calling expensive APIs
for i in range(100):  # Uncontrolled loop
    expensive_api_call()  # $1 per call
# → $100 bill
```

**Mitigation:**
```python
class ResourceBudget:
    def __init__(self, max_cost: float = 10.0):
        self.max_cost = max_cost
        self.spent = 0.0
        self.action_costs = {
            "llm_call": 0.01,
            "vector_search": 0.001,
            "api_call": 1.0
        }

    def can_afford(self, action: str) -> bool:
        """Check if action is within budget"""
        cost = self.action_costs.get(action, 0.0)
        return (self.spent + cost) <= self.max_cost

    def charge(self, action: str):
        """Deduct cost"""
        cost = self.action_costs.get(action, 0.0)
        self.spent += cost

    def prioritize_actions(
        self,
        possible_actions: List[ActionPlan]
    ) -> List[ActionPlan]:
        """Return actions sorted by cost-effectiveness"""
        return sorted(
            possible_actions,
            key=lambda a: self.action_costs.get(a.action, float('inf'))
        )
```

## 9. Production Architecture Example

### Complete production-ready React Loop

```python
from typing import Optional
import asyncio

class ProductionReactLoop:
    """
    Complete production React Loop implementation
    """
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        memory: AgentMemory,
        safety: SafetyChecker,
        logger: ReactLoopLogger,
        metrics: ReactLoopMetrics
    ):
        # Core components
        self.perception = PerceptionLayer(memory, tools)
        self.reasoning = ReasoningLayer(llm)
        self.action = ActionLayer(tools, safety)
        self.observation = ObservationLayer()
        self.evaluation = EvaluationLayer(llm)
        self.memory_update = MemoryUpdateLayer(memory)

        # Control & monitoring
        self.controller = LoopController(
            max_iterations=10,
            success_threshold=0.90,
            timeout_seconds=300
        )
        self.safety = safety
        self.logger = logger
        self.metrics = metrics

        # State
        self.memory = memory
        self.iteration = 0

    async def run(self, goal: str) -> Result:
        """
        Execute complete React Loop
        """
        # Initialize
        self.memory.set_goal(goal)
        self.controller.start()

        try:
            while True:
                # 1. PERCEPTION: Gather context
                context = await self.perception.perceive(
                    user_input=goal,
                    iteration=self.iteration
                )

                # 2. REASONING: Plan next action
                plan = await self.reasoning.reason(context)

                # 3. SAFETY: Check if action is safe
                is_safe, block_reason = self.safety.is_safe(plan)
                if not is_safe:
                    self.logger.log_safety_block(plan, block_reason)
                    break

                # 4. ACTION: Execute plan
                action_result = await self.action.execute(plan)

                # 5. OBSERVATION: Collect results
                observation = await self.observation.observe(plan, action_result)

                # 6. EVALUATION: Assess progress
                evaluation = await self.evaluation.evaluate(
                    goal=goal,
                    observation=observation,
                    memory=self.memory
                )

                # 7. MEMORY UPDATE: Store learnings
                await self.memory_update.update(plan, observation, evaluation)

                # 8. LOGGING: Record iteration
                self.logger.log_iteration(
                    iteration=self.iteration,
                    perception=context,
                    reasoning=plan,
                    action_result=action_result,
                    evaluation=evaluation
                )

                # 9. CONTROL: Check if should continue
                should_continue, reason = self.controller.should_continue(
                    iteration=self.iteration,
                    evaluation=evaluation
                )

                if not should_continue:
                    # Loop terminating
                    return Result(
                        success=(evaluation.confidence >= self.controller.success_threshold),
                        output=self.memory.get_findings(),
                        reason=reason,
                        trace=self.logger.export_trace(),
                        iterations=self.iteration + 1,
                        confidence=evaluation.confidence
                    )

                self.iteration += 1

        except Exception as e:
            # Error handling
            self.logger.log_error(e)
            return Result(
                success=False,
                error=str(e),
                trace=self.logger.export_trace(),
                iterations=self.iteration
            )

        finally:
            # Record metrics
            self.metrics.record_completion(
                iterations=self.iteration,
                final_confidence=evaluation.confidence,
                actions_used=self.logger.get_actions()
            )

# Usage example
async def main():
    # Setup
    llm = GPT4()
    tools = ToolRegistry()
    tools.register("search_logs", SearchLogsTool())
    tools.register("query_database", DatabaseTool())
    tools.register("read_file", FileReadTool())

    memory = AgentMemory()
    safety = SafetyChecker(policies=[
        NoDestructiveActions(),
        RateLimitPolicy(max_per_minute=10)
    ])
    logger = ReactLoopLogger()
    metrics = ReactLoopMetrics()

    # Create loop
    loop = ProductionReactLoop(llm, tools, memory, safety, logger, metrics)

    # Execute
    result = await loop.run("Debug authentication service failures")

    # Output
    print(f"Success: {result.success}")
    print(f"Iterations: {result.iterations}")
    print(f"Confidence: {result.confidence:.2%}")
    print(f"\nTrace:\n{result.trace}")
```

### Architecture diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Production React Loop                    │
└─────────────────────────────────────────────────────────────┘

User Input (Goal)
   ↓
┌──────────────────┐
│ Loop Controller  │ ← Max iterations, timeout, success threshold
└────────┬─────────┘
         ↓
┌─────────────────────────────────────────────────────┐
│                   ITERATION CYCLE                    │
│                                                      │
│  ┌─────────────┐                                   │
│  │ 1. Perceive │ ← Gather context from memory/tools│
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 2. Reason   │ ← LLM plans next action           │
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 3. Safety   │ ← Check action is safe            │
│  │   Check     │                                   │
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 4. Act      │ ← Execute tool/generate response  │
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 5. Observe  │ ← Collect results & logs          │
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 6. Evaluate │ ← LLM assesses progress           │
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 7. Update   │ ← Store in memory                 │
│  │   Memory    │                                   │
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 8. Log      │ ← Record for audit trail          │
│  └──────┬──────┘                                   │
│         ↓                                           │
│  ┌─────────────┐                                   │
│  │ 9. Control  │ ← Check termination conditions    │
│  │   Decision  │                                   │
│  └──────┬──────┘                                   │
│         │                                           │
│    ┌────┴────┐                                     │
│    │ Done?   │                                     │
│    └─┬────┬──┘                                     │
│      │Yes │No                                      │
│      │    └─────────┐                              │
│      │              ↓                              │
│      │         Next Iteration                      │
│      │              ↑                              │
│      │              └────────────────────┐         │
│      ↓                                    │         │
└──────────────────────────────────────────│─────────┘
       │                                    │
       ↓                                    ↺
   Final Result
   - Success/Failure
   - Output
   - Trace
   - Metrics

Parallel Components:
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Sub-Agent 1  │  │ Sub-Agent 2  │  │ Sub-Agent 3  │
└──────────────┘  └──────────────┘  └──────────────┘
       ↓                  ↓                  ↓
       └──────────────────┴──────────────────┘
                         ↓
                   Master Aggregator
```

## 10. Implementation Best Practices

### Production checklist

**1. Use structured outputs (JSON) for actions**

```python
# Bad: Unstructured text
action = "Search logs for errors"

# Good: Structured JSON
action = {
    "action": "search_logs",
    "parameters": {
        "pattern": "error",
        "time_range": "1h",
        "max_results": 100
    },
    "expected_outcome": "Identify error patterns"
}
```

**2. Enforce hard limits**

```python
class SafeReactLoop:
    def __init__(self):
        # MANDATORY limits
        self.max_iterations = 10        # Prevent infinite loops
        self.max_cost_usd = 1.0         # Prevent cost blowup
        self.timeout_seconds = 300      # 5 minute max
        self.max_tool_calls = 50        # Prevent API abuse

        # Enforce in controller
        self.controller = LoopController(
            max_iterations=self.max_iterations,
            timeout_seconds=self.timeout_seconds
        )
```

**3. Store complete loop history**

```python
class AuditableReactLoop:
    def log_complete_history(self):
        """Store everything for debugging"""
        return {
            "goal": self.goal,
            "iterations": [
                {
                    "iteration": i,
                    "perception": {...},   # What agent saw
                    "reasoning": {...},    # Why it chose this action
                    "action": {...},       # What it did
                    "observation": {...},  # What happened
                    "evaluation": {...}    # How it assessed results
                }
                for i in range(self.iteration)
            ],
            "final_result": self.result,
            "metrics": {
                "total_time": self.elapsed_time,
                "total_cost": self.total_cost,
                "iterations": self.iteration,
                "success": self.result.success
            }
        }
```

**4. Use adaptive iteration based on confidence**

```python
class AdaptiveController:
    def should_continue(self, evaluation: Evaluation) -> bool:
        """Adapt based on confidence trajectory"""

        # High confidence → stop early
        if evaluation.confidence > 0.95:
            return False

        # Confidence improving → continue
        recent_confidences = self.confidence_history[-3:]
        if self.is_improving(recent_confidences):
            return True

        # Confidence flat → try different approach or stop
        if self.is_stagnant(recent_confidences):
            return False

        return True
```

**5. Separate reasoning from execution**

```python
# Good: Clear separation
class SeparatedLoop:
    async def run(self):
        # Reasoning (LLM) - stateless, pure function
        plan = await self.llm.generate(prompt)

        # Validation - deterministic check
        if not self.validator.is_valid(plan):
            plan = await self.llm.revise(plan, "Invalid format")

        # Execution - controlled environment
        result = await self.sandboxed_executor.execute(plan)
```

**6. Integrate long-term memory**

```python
class MemoryIntegratedLoop:
    async def prepare_context(self, goal: str):
        """Pull from long-term memory"""

        # Recall similar past tasks
        similar_tasks = await self.long_term_memory.search(
            query=goal,
            top_k=3
        )

        # Recall learned procedures
        procedure = self.procedural_memory.get_procedure(
            task_type=classify_task(goal)
        )

        return {
            "goal": goal,
            "past_learnings": similar_tasks,
            "known_procedure": procedure
        }
```

**7. Use hybrid retrieval for better grounding**

```python
class HybridRetrievalLoop:
    async def retrieve_context(self, query: str):
        """Combine vector + graph + keyword search"""

        # Semantic search
        vector_results = await self.vector_db.search(query)

        # Graph traversal for relationships
        if entities := extract_entities(query):
            graph_results = await self.graph_db.traverse(entities)
        else:
            graph_results = []

        # Keyword fallback for exact matches
        keyword_results = await self.keyword_search(query)

        # Merge and deduplicate
        return merge_results([
            vector_results,
            graph_results,
            keyword_results
        ])
```

**8. Maintain audit trails**

```python
class CompliantLoop:
    def __init__(self):
        self.audit_log = []

    def log_decision(
        self,
        iteration: int,
        decision: str,
        reasoning: str,
        outcome: str
    ):
        """Log for compliance/debugging"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "iteration": iteration,
            "decision": decision,
            "reasoning": reasoning,
            "outcome": outcome,
            "confidence": self.current_confidence
        }
        self.audit_log.append(entry)

        # Persist to secure storage
        self.audit_store.append(entry)
```

## 11. When to Use the React Loop

### Use React Loops when:

**1. Complex, multi-step tasks**

```python
# Perfect for React Loop
tasks = [
    "Debug production outage and implement fix",
    "Research competitor features and generate PRD",
    "Analyze codebase for security vulnerabilities",
    "Generate comprehensive test suite for module"
]

# Each requires: discovery → analysis → planning → execution → validation
```

**2. Tasks with uncertain data or retrieval quality**

```python
# Example: Research task with unclear sources
query = "What caused the 2008 financial crisis?"

# React Loop can:
# Iteration 1: Broad search → find many sources
# Iteration 2: Evaluate sources → identify gaps
# Iteration 3: Targeted search → fill gaps
# Iteration 4: Synthesize → generate answer
# Iteration 5: Validate → check against known facts
```

**3. Tasks requiring iterative refinement**

```python
# Example: Code generation
goal = "Implement user authentication API"

# React Loop process:
# Iteration 1: Generate basic structure
# Iteration 2: Add error handling (based on evaluation)
# Iteration 3: Add input validation (based on security review)
# Iteration 4: Add tests (based on coverage check)
# Iteration 5: Optimize (based on performance analysis)
```

**4. Tasks needing multi-agent orchestration**

```python
# Example: Full-stack feature implementation
goal = "Implement payment processing feature"

# Master agent coordinates:
# - Backend agent: API endpoints
# - Frontend agent: UI components
# - Database agent: Schema changes
# - Testing agent: E2E tests
# Each agent runs its own React Loop
# Master synthesizes results
```

### Do NOT use React Loops for:

**1. Single-step deterministic responses**

```python
# Bad fit for React Loop
queries = [
    "What is 2 + 2?",
    "What's the capital of France?",
    "Translate 'hello' to Spanish"
]

# Single LLM call is sufficient
# React Loop adds unnecessary overhead
```

**2. Low-latency applications**

```python
# Bad: Real-time chat
# React Loop: 10-20 seconds per response
# Requirement: <1 second response

# Good: Autocomplete
# Single model: <200ms
# Meets requirement
```

**3. Small, simple queries**

```python
# Overkill for React Loop
simple_queries = [
    "List files in directory",
    "Get current time",
    "Check if user exists"
]

# Simple tool call or single LLM call is enough
```

### Decision framework

```python
def should_use_react_loop(task: Task) -> bool:
    """Decision tree"""

    # Multi-step required?
    if task.estimated_steps <= 1:
        return False

    # Can afford latency?
    if task.latency_requirement < 5:  # seconds
        return False

    # Task complexity
    if task.complexity == "trivial":
        return False

    # Need iterative refinement?
    if task.requires_iteration:
        return True

    # Need multi-agent coordination?
    if task.requires_multiple_agents:
        return True

    # Default: probably not needed
    return False
```

## 12. Performance & Scaling

### Optimization strategies

**1. Parallelize sub-agent actions**

```python
# Bad: Sequential execution
results = []
for agent in agents:
    result = await agent.run(subtask)
    results.append(result)
# Total time: sum of all agent times

# Good: Parallel execution
results = await asyncio.gather(*[
    agent.run(subtask)
    for agent in agents
])
# Total time: max of all agent times
```

**2. Cache repeated retrievals**

```python
class CachedRetrieval:
    def __init__(self):
        self.cache = {}

    async def retrieve(self, query: str):
        """Cache retrieval results"""
        cache_key = hash(query)

        if cache_key in self.cache:
            return self.cache[cache_key]

        results = await self.vector_db.search(query)
        self.cache[cache_key] = results
        return results
```

**3. Limit context size**

```python
class ContextManager:
    def __init__(self, max_context_tokens: int = 8000):
        self.max_tokens = max_context_tokens

    def prepare_context(self, history: List[Dict]) -> str:
        """Truncate history to fit context window"""

        # Keep most recent iterations
        recent = history[-5:]

        # Summarize older iterations
        older = history[:-5]
        summary = self.summarize(older) if older else ""

        context = summary + format_history(recent)

        # Truncate if still too long
        if count_tokens(context) > self.max_tokens:
            context = truncate_to_tokens(context, self.max_tokens)

        return context
```

**4. Use async execution**

```python
class AsyncReactLoop:
    async def execute_tools(self, actions: List[ActionPlan]):
        """Execute I/O-bound actions concurrently"""

        # All tool calls happen in parallel
        results = await asyncio.gather(*[
            self.execute_tool(action)
            for action in actions
        ])

        return results
```

**5. Monitor convergence**

```python
class ConvergenceMonitor:
    def is_converging(self, evaluations: List[Evaluation]) -> bool:
        """Check if making progress"""

        if len(evaluations) < 3:
            return True  # Too early to tell

        # Extract confidence trajectory
        confidences = [e.confidence for e in evaluations[-5:]]

        # Check if improving
        slope = self.calculate_slope(confidences)

        if slope > 0.05:
            return True  # Improving

        if slope < -0.05:
            return False  # Getting worse

        # Flat - check if already high
        return confidences[-1] > 0.85

    def calculate_slope(self, values: List[float]) -> float:
        """Linear regression slope"""
        n = len(values)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        return numerator / denominator if denominator != 0 else 0
```

## 13. Resources & References

### Research Papers

**Foundational work:**
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) - Original ReAct paper (Yao et al., 2022)
- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366) - Self-reflection for agents
- [AutoGPT and the Future of Autonomous Agents](https://arxiv.org/abs/2305.00936) - Autonomous agent patterns

### Frameworks & Tools

**Production implementations:**
- [LangGraph](https://langchain-ai.github.io/langgraph/) - State machine framework for agentic loops
- [AutoGen](https://microsoft.github.io/autogen/) - Microsoft's multi-agent conversation framework
- [CrewAI](https://github.com/joaomdmoura/crewAI) - Role-based multi-agent orchestration

### Practical Guides

**Implementation tutorials:**
- [Building Production AI Agents](https://www.anthropic.com/research/agent-patterns) - Anthropic's agent patterns
- [RAG + Agentic Loops](https://www.assemblyai.com/blog/retrieval-augmented-generation-agentic) - Combining retrieval with iteration
- [Multi-Agent Systems Guide](https://lilianweng.github.io/posts/2023-06-23-agent/) - Lil'Log comprehensive overview

### Best Practices

**Production deployment:**
- [Agent Safety Guidelines](https://www.anthropic.com/index/claude-character) - Safety considerations for production agents
- [LLM Observability](https://www.langsmith.com/) - Monitoring and debugging agent systems
- [Prompt Engineering for Agents](https://www.promptingguide.ai/) - Effective prompting strategies

---

## Final Takeaway

### The React Loop transforms LLMs into autonomous agents

**Key principles:**

1. **Iteration over single-shot**: Multiple attempts beat hoping to get it right the first time
2. **Feedback incorporation**: Each iteration learns from previous results
3. **Dynamic planning**: Adjust strategy based on what's discovered
4. **Self-monitoring**: Agents track their own progress and know when to stop
5. **Bounded execution**: Hard limits prevent runaway behavior
6. **Auditability**: Every decision is logged and traceable

**The mental model:**

```
Perceive → Reason → Act → Observe → Evaluate → Update → Repeat
```

This closed-loop control system enables:
- **Autonomous problem-solving** (complex multi-step tasks)
- **Self-correction** (recover from errors)
- **Adaptive behavior** (adjust to changing conditions)
- **Production reliability** (bounded, safe, observable)

**When to use:**
- Complex tasks requiring multiple steps
- Uncertain environments with incomplete information
- Quality-critical outputs needing refinement
- Multi-agent coordination

**When not to use:**
- Simple single-step queries
- Low-latency requirements (<5s)
- Deterministic responses
- Trivial tasks

**The bottom line:**

> The React Loop is the foundation of production-ready autonomous AI agents. It takes LLMs from reactive responders to proactive problem-solvers.

Master the React Loop, and you unlock the ability to build agents that can tackle real-world complexity with reliability, safety, and auditability.

---