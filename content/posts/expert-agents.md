---
title: "Elite Context Engineering: The R&D Agent Strategy"
date: 2025-11-28T01:58:00+02:00
draft: false
---

# Elite Context Engineering Tutorial: The R&D Agent Strategy

**Master the art of context window management to build high-performance AI agents**

> *"A focused agent is a performant agent. Context engineering is the name of the game for high-value engineering in the age of agents."*

---

## Table of Contents

1. [Foundation](#foundation)
   - [What is Context Engineering?](#what-is-context-engineering)
   - [The R&D Framework](#the-rd-framework)
2. [Level 1: Beginner - Reduction Techniques](#level-1-beginner---reduction-techniques)
   - [1.1 Eliminate Wasteful MCP Server Loading](#11-eliminate-wasteful-mcp-server-loading)
   - [1.2 Context Priming Over Large Memory Files](#12-context-priming-over-large-memory-files)
3. [Level 2: Intermediate - Delegation with Sub-Agents](#level-2-intermediate---delegation-with-sub-agents)
   - [2.1 Understanding Sub-Agents](#21-understanding-sub-agents)
   - [2.2 Implementing Sub-Agent Workflows](#22-implementing-sub-agent-workflows)
4. [Level 3: Advanced - Active Context Management](#level-3-advanced---active-context-management)
   - [3.1 Context Bundles](#31-context-bundles)
   - [3.2 Session Recovery Workflows](#32-session-recovery-workflows)
5. [Level 4: Agentic - Multi-Agent Orchestration](#level-4-agentic---multi-agent-orchestration)
   - [4.1 Primary Multi-Agent Delegation](#41-primary-multi-agent-delegation)
   - [4.2 Background Agent Workflows](#42-background-agent-workflows)
   - [4.3 Agent Experts Pattern](#43-agent-experts-pattern)
6. [Resources & Next Steps](#resources--next-steps)

---

## Foundation

### What is Context Engineering?

**Context Engineering** is the discipline of managing your AI agent's context window to maximize performance, minimize waste, and scale your agent systems effectively.

#### Why It Matters

- **Performance Degrades with Context Growth**: Language models have inherent scaling laws where performance decreases as context windows grow
- **Token Efficiency**: Every token counts—wasteful context loading impacts speed and cost
- **Agent Focus**: A cluttered context window creates confused, slow, error-prone agents
- **Scalability**: Poor context management prevents you from scaling to multi-agent systems

#### Core Principle

> **A focused engineer is a performant engineer.**  
> **A focused agent is a performant agent.**

### The R&D Framework

There are only **two ways** to manage your context window:

#### **R = REDUCE**
Minimize unnecessary context entering your primary agent. Keep only task-specific, relevant information loaded.

**Techniques:**
- Remove unused MCP servers
- Shrink static memory files
- Use dynamic context priming
- Selective information loading

#### **D = DELEGATE**
Offload context-heavy work to sub-agents or separate primary agents, keeping intensive tasks outside your main agent's context window.

**Techniques:**
- Sub-agent delegation
- Background agent workflows
- Multi-agent orchestration
- Specialized agent experts

**Every technique in this guide fits into R, D, or both.**

---

## Level 1: Beginner - Reduction Techniques

**Goal:** Clean up your primary agent's context window by eliminating waste

### 1.1 Eliminate Wasteful MCP Server Loading

#### The Problem

MCP (Model Context Protocol) servers can consume **24,100+ tokens** (12% of context window) when loaded unnecessarily through default configurations.

#### Step-by-Step Implementation

**Step 1: Audit Current Context Usage**
````bash
# Check your current token consumption
claude context
````

**Expected Output:**
````
Context Window: 200,000 tokens
Used: 24,100 tokens (12.05%)
Available: 175,900 tokens (87.95%)

MCP Tools: 24,100 tokens
````

**Step 2: Remove Default MCP Configuration**
````bash
# Delete default MCP configuration files
rm .claude/mcp.json
# or
rm defaultmcp.json
````

**Result:** Immediate context window cleanup, saving ~20,000+ tokens

**Step 3: Load MCP Servers Explicitly When Needed**
````bash
# Fire up specific MCP server configuration
claude-mcp config path/to/firecrawl-4k.json

# For strict configuration (override globals)
claude -d-strict mcp config path/to/specific-config.json
````

**Step 4: Verify Context Savings**
````bash
# Check context after cleanup
claude context
````

**Expected Output:**
````
Context Window: 200,000 tokens
Used: 6,000 tokens (3%)
Available: 194,000 tokens (97%)

MCP Tools: 6,000 tokens (firecrawl only)
````

#### Best Practices

- ✅ **Be purposeful**: Only load MCP servers you actively need
- ✅ **Suffix configs**: Name configs by token size (e.g., `firecrawl-4k.json`)
- ✅ **Explicit over implicit**: Manually reference each required server
- ❌ **Never use default autoload configs** for production workflows

#### Prompt Template
````markdown
Load only the [SERVER_NAME] MCP server for this task:

claude-mcp config configs/[SERVER_NAME]-config.json

Task: [DESCRIBE YOUR TASK]
````

---

### 1.2 Context Priming Over Large Memory Files

#### The Problem

**Large `claude.md` memory files** (23,000+ tokens, 10% of context) that:
- Constantly grow as projects evolve
- Become "massive globs of mess"
- Are always loaded regardless of task relevance
- Impact agent performance

#### The claude.md Paradox

> `claude.md` is **incredible** because it's a reusable memory file always loaded into your agent's context.
> 
> `claude.md` is **terrible** for the exact same reason.

The problem: **Always-on context is not dynamic or controllable.** Engineering work changes constantly, but `claude.md` only grows.

#### Step-by-Step Implementation

**Step 1: Audit Your Current claude.md**
````bash
# Check file size
wc -l .claude/claude.md

# Check token consumption
claude context | grep "claude.md"
````

**Red Flags:**
- File exceeds 50 lines
- Token consumption over 1,000 tokens
- Contains task-specific instructions
- Includes multiple project areas

**Step 2: Shrink claude.md to Essentials Only**

Keep **ONLY** what you're 100% sure you want loaded 100% of the time.

**Example Minimal claude.md (43 lines, 350 tokens):**
````markdown
# Universal Project Standards

## Code Style
- Use descriptive variable names
- Follow language-specific conventions
- Include error handling

## Communication
- Provide clear status updates
- Ask clarifying questions when uncertain
- Summarize actions taken

## File Operations
- Always verify file paths before operations
- Create backups for destructive changes
- Report all file modifications
````

**Step 3: Create Context Priming Commands**

Context priming uses **dedicated reusable prompts** (custom slash commands) to set up task-specific context dynamically.

**Directory Structure:**
````
.claude/
├── claude.md (minimal, universal)
└── commands/
    ├── prime.md
    ├── prime-bug.md
    ├── prime-feature.md
    └── prime-refactor.md
````

**Example: `commands/prime.md`**
````markdown
# Prime: General Codebase Understanding

## Purpose
Gain comprehensive understanding of codebase structure, patterns, and current state for general development tasks.

## Run Steps
1. Read project README
2. Scan directory structure
3. Identify key architectural patterns
4. Review recent changes

## Read
- README.md
- package.json / requirements.txt / Cargo.toml
- src/ directory structure
- docs/ folder overview

## Report
Provide concise summary of:
- Project purpose and tech stack
- Key directories and their roles
- Notable patterns or conventions
- Current development focus
````

**Example: `commands/prime-bug.md`**
````markdown
# Prime: Bug Investigation

## Purpose
Set up context for investigating and fixing reported bugs.

## Variables
- BUG_ID: {{bug_id}}
- SYMPTOMS: {{symptoms}}
- AFFECTED_FILES: {{files}}

## Run Steps
1. Review bug report details
2. Locate relevant code sections
3. Identify potential root causes
4. Plan investigation approach

## Read
- Issue tracker entry for {{bug_id}}
- Files: {{files}}
- Related test files
- Recent commits to affected areas

## Report
- Bug reproduction steps
- Suspected root cause
- Investigation plan
- Estimated complexity
````

**Step 4: Use Context Priming in Practice**
````bash
# Start new agent session
claude opus --yolo

# Prime for general development
/prime

# Or prime for specific task
/prime-bug

# Or prime for feature work
/prime-feature
````

**Step 5: Verify Context Efficiency**
````bash
# Check context after priming
claude context
````

**Expected Output:**
````
Context Window: 200,000 tokens
Used: 8,500 tokens (4.25%)
Available: 191,500 tokens (95.75%)

claude.md: 350 tokens
Prime command: 1,200 tokens
Loaded files: 6,950 tokens
````

#### Context Priming Prompt Structure

All prime commands should follow this structure:
````markdown
# Prime: [TASK_TYPE]

## Purpose
[One sentence describing the goal]

## Variables (optional)
- VAR_NAME: {{description}}

## Run Steps
1. [Action step 1]
2. [Action step 2]
3. [Action step 3]

## Read
- [File or directory to read]
- [Another file]

## Report
[What the agent should summarize after priming]
````

#### Best Practices

- ✅ **Keep claude.md under 50 lines** (universal essentials only)
- ✅ **Create task-specific prime commands** for different work areas
- ✅ **Use variables** in prime commands for reusability
- ✅ **Build prime libraries** as your project grows
- ❌ **Never let claude.md become a dumping ground**
- ❌ **Don't include task-specific info in claude.md**

#### Comparison: claude.md vs Context Priming

| Aspect | Large claude.md | Context Priming |
|--------|-----------------|-----------------|
| **Token Usage** | 23,000+ tokens always | 1,200 tokens when needed |
| **Flexibility** | Static, always loaded | Dynamic, task-specific |
| **Maintenance** | Grows endlessly | Organized, modular |
| **Performance** | Degrades over time | Optimized per task |
| **Control** | None (always on) | Full (selective loading) |

---

## Level 2: Intermediate - Delegation with Sub-Agents

**Goal:** Offload context-heavy work to specialized sub-agents

### 2.1 Understanding Sub-Agents

#### What Are Sub-Agents?

Sub-agents are specialized agent instances spawned by your primary agent to handle specific tasks. They create a **partially forked context window**, keeping heavy computational work isolated.

#### The System Prompt Advantage

**Key Difference:**
- **User Prompts** → Added to primary agent's context window
- **System Prompts** → Define sub-agent behavior WITHOUT adding to primary context

This is a **massive advantage** for the **D (Delegate)** in the R&D framework.

#### Token Math Example

**Without Sub-Agents:**
````
Primary Agent Context:
- Base context: 5,000 tokens
- Web scraping task: 40,000 tokens (10 pages × 4,000 tokens)
- Total: 45,000 tokens in primary agent
````

**With Sub-Agents:**
````
Primary Agent Context:
- Base context: 5,000 tokens
- Sub-agent definitions: 1,200 tokens
- Total: 6,200 tokens in primary agent

Sub-Agent Contexts (isolated):
- 10 sub-agents × 4,000 tokens each
- Total: 40,000 tokens NOT in primary agent
````

**Savings:** 38,800 tokens freed in primary agent context

### 2.2 Implementing Sub-Agent Workflows

#### Step-by-Step Implementation

**Step 1: Define Sub-Agent System Prompts**

**Directory Structure:**
````
.claude/
└── agents/
    ├── doc-scraper.md
    ├── code-reviewer.md
    └── data-processor.md
````

**Example: `agents/doc-scraper.md`**
````markdown
# Doc Scraper Sub-Agent

## Role
Specialized web documentation scraper that fetches and processes documentation pages.

## Capabilities
- Web fetching with firecrawl or web_fetch
- HTML content extraction
- Markdown conversion
- Clean output formatting

## Constraints
- Maximum 5,000 tokens per scrape
- Focus on main content only
- Remove navigation and boilerplate
- Preserve code blocks and examples

## Output Format
Save to: `docs/scraped/[domain]-[page-slug].md`

Include:
- Source URL
- Fetch timestamp
- Cleaned content
- Key sections identified

## Error Handling
- Retry failed fetches once
- Report inaccessible pages
- Skip authentication-required content
````

**Step 2: Create Delegation Command**

**File: `.claude/commands/load-ai-docs.md`**
````markdown
# Load AI Documentation

## Purpose
Fetch and process AI documentation from multiple sources using specialized doc-scraper sub-agents.

## Variables
- DOCS_LIST: ai-docs-urls.txt

## Workflow

### 1. Check Freshness
Read existing docs in `docs/scraped/`
Identify files older than 24 hours

### 2. Remove Stale Docs
Delete outdated documentation files

### 3. Spawn Doc Scrapers
For each URL in {{DOCS_LIST}}:
- Launch doc-scraper sub-agent
- Pass URL and output path
- Run in parallel

### 4. Verify Completion
Wait for all sub-agents to complete
Check all expected output files exist

## Report Format
- Total URLs processed
- Successful scrapes
- Failed URLs (with reasons)
- Total tokens consumed by sub-agents
- Updated documentation list
````

**Step 3: Execute Sub-Agent Workflow**
````bash
# Start primary agent
claude opus --yolo

# Load MCP server for web fetching (if needed)
claude-mcp config configs/firecrawl-config.json

# Execute delegation command
/load-ai-docs
````

**Step 4: Monitor Sub-Agent Execution**

**Expected Console Output:**
````
[Primary Agent] Reading ai-docs-urls.txt...
[Primary Agent] Found 10 URLs to process
[Primary Agent] Checking existing docs...
[Primary Agent] Removing 8 stale files...
[Primary Agent] Spawning doc-scraper sub-agents...

[Sub-Agent 1] Scraping: https://docs.anthropic.com/claude/docs
[Sub-Agent 2] Scraping: https://platform.openai.com/docs
[Sub-Agent 3] Scraping: https://docs.langchain.com/docs
...

[Sub-Agent 1] ✓ Complete (3,847 tokens) → docs/scraped/anthropic-claude.md
[Sub-Agent 2] ✓ Complete (4,123 tokens) → docs/scraped/openai-platform.md
[Sub-Agent 3] ✓ Complete (3,654 tokens) → docs/scraped/langchain-docs.md
...

[Primary Agent] All sub-agents completed successfully
[Primary Agent] Total: 10/10 successful, 38,450 tokens (isolated in sub-agents)
````

**Step 5: Verify Context Savings**
````bash
# Check primary agent context
claude context
````

**Expected Output:**
````
Context Window: 200,000 tokens
Used: 9,200 tokens (4.6%)
Available: 190,800 tokens (95.4%)

Sub-agents spawned: 10
Sub-agent token usage: 38,450 tokens (NOT in primary context)
````

#### Sub-Agent Delegation Patterns

**Pattern 1: Parallel Processing**
````markdown
## Workflow
For each item in {{LIST}}:
- Spawn sub-agent
- Process independently
- Collect results

Wait for all completions
Aggregate results
````

**Pattern 2: Sequential Chain**
````markdown
## Workflow
1. Spawn preprocessor sub-agent
2. Wait for completion
3. Spawn analyzer sub-agent with preprocessor output
4. Wait for completion
5. Spawn reporter sub-agent with analyzer output
````

**Pattern 3: Conditional Delegation**
````markdown
## Workflow
If {{CONDITION}}:
  - Spawn specialized-sub-agent-A
Else:
  - Spawn specialized-sub-agent-B

Process results based on which agent ran
````

#### Best Practices

- ✅ **Isolate heavy tasks** to sub-agents (web scraping, file processing)
- ✅ **Keep sub-agent prompts focused** on one responsibility
- ✅ **Use parallel execution** when tasks are independent
- ✅ **Monitor token consumption** per sub-agent
- ✅ **Aggregate results** in primary agent
- ❌ **Don't overuse sub-agents** for simple tasks
- ❌ **Don't lose track** of context flow between agents
- ❌ **Don't nest sub-agents** more than 2 levels deep

#### When to Use Sub-Agents

**Good Use Cases:**
- Web scraping multiple URLs
- Processing multiple files
- Parallel data transformations
- Independent task execution
- Token-heavy operations

**Bad Use Cases:**
- Simple file reads
- Single calculations
- Sequential dependent tasks
- Tasks requiring primary agent context

#### Managing Context Flow

**Critical Concept:** The flow of information in multi-agent systems
````
[User] 
  ↓ (prompts)
[Primary Agent]
  ↓ (spawns & prompts)
[Sub-Agent 1] [Sub-Agent 2] [Sub-Agent 3]
  ↓ (responds)    ↓ (responds)    ↓ (responds)
[Primary Agent]
  ↓ (aggregates & responds)
[User]
````

**Key Points:**
- Sub-agents respond to PRIMARY AGENT, not to you
- Primary agent must aggregate sub-agent results
- You only see primary agent's final report
- Sub-agent context is isolated and discarded after completion

---

## Level 3: Advanced - Active Context Management

**Goal:** Maintain context continuity across agent sessions

### 3.1 Context Bundles

#### What Are Context Bundles?

Context bundles are **append-only logs** of agent work that capture:
- User prompts executed
- Files read
- Operations performed
- Plans created
- Key decisions made

They provide a **trail of work** that enables subsequent agents to understand what previous agents accomplished without loading their full context.

#### Why Context Bundles Matter

**Problem:** Agent context windows eventually explode
- Long sessions accumulate tokens
- Complex tasks require extensive reading
- Multiple iterations build up context
- Eventually performance degrades

**Solution:** Context bundles let you:
- Start fresh agent sessions
- Recover 60-70% of previous agent's understanding
- Avoid re-reading entire codebases
- Maintain continuity across sessions

#### How Context Bundles Work

**Automatic Generation via Claude Code Hooks:**
- Hook into tool calls (reads, writes, searches)
- Log operations to session-specific bundle
- Unique by date, hour, and session ID
- Trim to essential operations only

### 3.2 Session Recovery Workflows

#### Step-by-Step Implementation

**Step 1: Enable Context Bundle Generation**

Context bundles are typically auto-generated when using Claude Code with proper hooks. Verify they're being created:
````bash
# Check for context bundles directory
ls -la .claude/agents/context-bundles/

# Expected output:
# 2025-11-28-01-session-abc123.bundle
# 2025-11-28-02-session-def456.bundle
````

**Step 2: Generate a Context Bundle (Manual Process)**

If your setup doesn't auto-generate bundles, create them manually:

**File: `.claude/agents/context-bundles/2025-11-28-01-session-abc123.bundle`**
````markdown
# Context Bundle: Feature Development Session
Session ID: abc123
Started: 2025-11-28 01:00:00
Agent: Claude Opus

## User Prompt
/prime
Prepare for implementing new authentication system

## Operations Log

### Read Operations
- README.md (overview)
- src/auth/current-auth.ts (existing implementation)
- src/database/user-schema.ts (user model)
- docs/auth-requirements.md (specifications)
- package.json (dependencies)
- src/middleware/auth-middleware.ts (current middleware)
- tests/auth.test.ts (existing tests)

### Search Operations
- "authentication" across src/ → 23 results
- "JWT" across src/ → 15 results
- "session" across src/auth/ → 8 results

### Plans Created
Created quick plan:
1. Analyze current authentication implementation
2. Identify security gaps
3. Design new JWT-based system
4. Plan migration strategy
5. Update middleware
6. Write comprehensive tests

### Key Findings
- Current system uses basic session cookies
- No token refresh mechanism
- Passwords hashed with bcrypt (good)
- Need to add JWT support
- Middleware tightly coupled to old system
````

**Step 3: Load Context Bundle in New Session**
````bash
# Start new agent session
claude opus --yolo

# Load previous context bundle
/loadbundle .claude/agents/context-bundles/2025-11-28-01-session-abc123.bundle
````

**Agent Response:**
````
[Agent] Loading context bundle: session-abc123

[Agent] Summary of previous session:
- Prompt: Prepare for implementing new authentication system
- Files read: 7 key files
- Key findings loaded:
  • Current system uses session cookies
  • No token refresh mechanism
  • Need JWT implementation
  • Middleware requires refactoring

[Agent] De-duplicating read operations...
[Agent] Context restored. Ready to continue authentication system implementation.

What would you like to work on next?
````

**Step 4: Verify Context Efficiency**
````bash
# Check new agent's context
claude context
````

**Expected Output:**
````
Context Window: 200,000 tokens
Used: 4,200 tokens (2.1%)
Available: 195,800 tokens (97.9%)

claude.md: 350 tokens
Context bundle summary: 850 tokens
Current session: 3,000 tokens
````

Compare to reloading everything manually:
````
Without bundle: 45,000+ tokens
With bundle: 4,200 tokens
Savings: 40,800 tokens (90% reduction)
````

#### Context Bundle Best Practices

**What to Include:**
- ✅ User prompts and commands executed
- ✅ File read operations (paths only, not full content)
- ✅ Search operations and result counts
- ✅ Plans and decisions made
- ✅ Key findings and insights
- ✅ Next steps identified

**What to Exclude:**
- ❌ Full file contents
- ❌ Detailed write operations
- ❌ Token-heavy responses
- ❌ Redundant information
- ❌ Debugging details

**Structure Template:**
````markdown
# Context Bundle: [TASK_NAME]
Session ID: [SESSION_ID]
Started: [TIMESTAMP]
Agent: [AGENT_NAME]

## User Prompt
[Initial prompt that started the session]

## Operations Log

### Read Operations
- [file-path] ([brief context])
- [file-path] ([brief context])

### Search Operations
- "[query]" across [scope] → [count] results

### Write Operations (High-Level Only)
- Created: [file-path]
- Modified: [file-path]

### Plans Created
[Brief summary of plans made]

### Key Findings
- [Finding 1]
- [Finding 2]
- [Finding 3]

### Next Steps
- [Step 1]
- [Step 2]
````

#### Advanced Context Bundle Patterns

**Pattern 1: Chained Context Bundles**

For multi-day projects, chain bundles together:
````markdown
# Context Bundle: Day 3 - Authentication Testing
Session ID: xyz789
Previous Bundles:
- 2025-11-28-01-session-abc123 (initial design)
- 2025-11-28-02-session-def456 (implementation)

## Inherited Context
From previous sessions:
- JWT system implemented
- Middleware refactored
- Database migrations complete

## Today's Work
[Current session operations]
````

**Pattern 2: Milestone Bundles**

Create comprehensive bundles at project milestones:
````markdown
# Context Bundle: Authentication System - Milestone 1 Complete
Milestone: MVP JWT Authentication
Sessions Included: 5
Total Time: 12 hours

## What Was Accomplished
- JWT token generation and validation
- Refresh token system
- Updated middleware
- 95% test coverage

## Key Files
- src/auth/jwt.service.ts (core implementation)
- src/middleware/jwt-auth.middleware.ts
- tests/auth-integration.test.ts

## Known Issues
- Token expiration edge case in timezone handling
- Need rate limiting on refresh endpoint

## Next Phase Context
Ready to begin:
- OAuth2 integration
- Multi-factor authentication
- Admin permission system
````

---

## Level 4: Agentic - Multi-Agent Orchestration

**Goal:** Scale to multiple primary agents working in parallel and background

### 4.1 Primary Multi-Agent Delegation

#### What is Primary Multi-Agent Delegation?

Unlike sub-agents (which are forked from your primary agent), **primary multi-agent delegation** involves spawning completely independent top-level agents that:
- Run in parallel
- Have their own full context windows
- Can use different models
- Report back via files or APIs
- Enable true "out of the loop" workflows

#### Multi-Agent Delegation Methods

| Method | Complexity | Control | Use Case |
|--------|------------|---------|----------|
| **CLI** | Low | High | Quick background tasks |
| **SDK** | Medium | Very High | Programmatic workflows |
| **MCP Server** | Medium | High | Tool-based orchestration |
| **Custom UI** | High | Very High | Production systems |
| **Wrapper Scripts** | Low | Medium | Batch processing |

### 4.2 Background Agent Workflows

#### The Lightweight Delegation Pattern

The simplest way to achieve primary multi-agent delegation is through a **reusable custom command** that spawns background Claude Code instances.

#### Step-by-Step Implementation

**Step 1: Create Background Command**

**File: `.claude/commands/background.md`**
````markdown
# Background Agent Launcher

## Purpose
Launch a full Claude Code instance in the background to execute one focused task without blocking the primary agent.

## Arguments
- {{prompt}}: The task prompt for the background agent
- {{model}}: claude-opus or claude-sonnet (default: opus)
- {{report_file}}: Path to write completion report

## Workflow

### 1. Create Report File
Create empty report file at {{report_file}}

### 2. Launch Background Agent
Execute:
```bash
claude {{model}} --yolo << EOF > {{report_file}} 2>&1 &
{{prompt}}
EOF
```

### 3. Create Context Bundle
Generate context bundle for background session in:
`.claude/agents/background/{{timestamp}}-{{task}}.bundle`

### 4. Return Immediately
Report to user:
- Background task launched
- Task ID / Session ID
- Report file location
- How to monitor progress

## Report Format
Background Task Launched:
- Task: {{brief_description}}
- Model: {{model}}
- Session: {{session_id}}
- Report: {{report_file}}
- Status: Running

Monitor progress: tail -f {{report_file}}
````

**Step 2: Create Task-Specific Background Prompts**

**File: `.claude/agents/background/quick-plan.md`**
````markdown
# Background Task: Quick Plan Generation

## Purpose
Generate a detailed implementation plan for a new feature or component.

## Prompt Template
You are a focused planning agent. Your sole purpose is to create a detailed implementation plan.

## Context
Project: {{project_name}}
Task: {{task_description}}

## Required Output Format

### Plan Structure
1. Overview
2. Technical Approach
3. File Structure
4. Implementation Steps
5. Testing Strategy
6. Risks and Mitigations

## Output Location
Write plan to: `plans/{{task_name}}-plan.md`

## Report Requirements
When complete:
1. Rename report file to include timestamp
2. Report success/failure
3. List plan file location
4. Provide next steps

## Constraints
- Single execution, no follow-up prompts
- Complete within 5 minutes
- Use existing codebase patterns
- No interactive questions
````

**Step 3: Execute Background Agent**
````bash
# Start primary agent
claude opus --yolo

# Launch background planning agent
/background "Generate implementation plan for OAuth2 integration" opus plans/oauth2-plan-progress.md
````

**Primary Agent Response:**
````
Background Task Launched ✓

Task: Generate OAuth2 implementation plan
Model: claude-opus
Session: bg-abc123-oauth2-plan
Report: plans/oauth2-plan-progress.md
Status: Running

Monitor progress:
  tail -f plans/oauth2-plan-progress.md

Context bundle:
  .claude/agents/background/2025-11-28-02-oauth2-plan.bundle
````

**Step 4: Monitor Background Agent Progress**
````bash
# In another terminal
tail -f plans/oauth2-plan-progress.md
````

**Real-time Output:**
````
[02:15:01] Background planning agent initialized
[02:15:02] Reading project structure...
[02:15:08] Analyzing existing authentication system...
[02:15:15] Researching OAuth2 best practices...
[02:15:45] Generating plan structure...
[02:16:20] Writing implementation steps...
[02:16:55] Plan complete → plans/oauth2-implementation-plan.md

Task Status: ✓ COMPLETE
Duration: 1m 54s
Output: plans/oauth2-implementation-plan.md
````

**Step 5: Integrate Results**

Once background task completes:
````bash
# Primary agent continues
/read plans/oauth2-implementation-plan.md

# Or kick off implementation with new background agent
/background "Implement OAuth2 following plans/oauth2-implementation-plan.md" opus implementation-progress.md
````

#### Advanced Background Patterns

**Pattern 1: Agent Chains**

Launch sequential background agents where each uses the previous output:
````markdown
## Multi-Stage Background Pipeline

### Stage 1: Research
/background "Research OAuth2 providers and compare features" sonnet research/oauth2-research.md

### Stage 2: Planning (after Stage 1 completes)
/background "Create implementation plan using research/oauth2-research.md" opus plans/oauth2-plan.md

### Stage 3: Implementation (after Stage 2 completes)
/background "Implement OAuth2 following plans/oauth2-plan.md" opus implementation/oauth2-progress.md
````

**Pattern 2: Parallel Background Agents**

Launch multiple independent agents simultaneously:
````markdown
## Parallel Background Tasks

# Start all at once
/background "Write unit tests for auth module" sonnet tests/auth-test-progress.md
/background "Update API documentation" sonnet docs/api-docs-progress.md
/background "Refactor error handling" opus refactor/error-handling-progress.md
/background "Performance optimization analysis" opus analysis/perf-analysis.md

# All run in parallel, report independently
````

**Pattern 3: Scheduled Background Monitoring**

Set up recurring background agents:
````bash
# Cron job or scheduled task
0 */6 * * * claude opus --yolo --one-shot "Scan codebase for security vulnerabilities and update reports/security-scan.md" >> logs/security-scan.log 2>&1
````

### 4.3 Agent Experts Pattern

#### What Are Agent Experts?

**Agent Experts** are highly specialized, single-purpose agents designed to do one thing extraordinarily well. They represent the ultimate evolution of context engineering through extreme specialization.

#### The Specialization Advantage

**Why Specialization Matters:**
- Focused context = Maximum performance
- Single responsibility = Fewer errors
- Repeatable = Consistent quality
- Composable = Build complex systems

**Performance Principle:**
> As context windows grow, performance decreases. Therefore, many small specialized agents outperform one large general agent.

#### Building Agent Experts
**Step 1:
Identify Expert Domains**
Look for repeating tasks in your workflow:

Code review (by language or framework)
Test generation
Documentation writing
Bug analysis
Performance optimization
Security auditing
API design
Database optimization

Step 2: Create Expert Directory Structure
.claude/
└── agents/
    └── experts/
        ├── python-reviewer/
        │   ├── system-prompt.md
        │   ├── checklist.md
        │   └── examples/
        ├── test-generator/
        │   ├── system-prompt.md
        │   ├── templates/
        │   └── coverage-rules.md
        ├── api-designer/
        │   ├── system-prompt.md
        │   ├── rest-conventions.md
        │   └── schema-patterns.md
        └── security-auditor/
            ├── system-prompt.md
            ├── vulnerability-checklist.md
            └── remediation-guides/
Step 3: Define Expert System Prompts
Example: agents/experts/python-reviewer/system-prompt.md
markdown# Expert: Python Code Reviewer

## Identity
You are an expert Python code reviewer specializing in:
- PEP 8 compliance
- Type safety (mypy/pyright)
- Performance optimization
- Security vulnerabilities
- Pythonic idioms
- Test coverage

## Expertise Areas
- Python 3.10+ features
- FastAPI / Flask patterns
- SQLAlchemy best practices
- Async/await patterns
- Error handling
- Dependency management

## Review Process

### 1. Structural Analysis
- Module organization
- Import structure
- Dependency cycles
- Package architecture

### 2. Code Quality
- PEP 8 compliance
- Type annotations
- Docstring completeness
- Naming conventions

### 3. Logic Review
- Algorithm efficiency
- Error handling
- Edge cases
- Race conditions

### 4. Security Scan
- SQL injection risks
- XSS vulnerabilities
- Authentication issues
- Secrets in code

### 5. Performance Check
- N+1 queries
- Unnecessary loops
- Memory leaks
- Blocking operations

## Output Format

### Summary
[High-level assessment: Excellent/Good/Needs Work/Critical Issues]

### Critical Issues (Blockers)
- [Issue 1 with file:line]
- [Issue 2 with file:line]

### Improvements (Should Fix)
- [Improvement 1 with suggestion]
- [Improvement 2 with suggestion]

### Suggestions (Nice to Have)
- [Suggestion 1]
- [Suggestion 2]

### Positives
- [Good practice 1]
- [Good practice 2]

## Constraints
- Review files provided only
- Reference checklist.md for standards
- Provide code examples for fixes
- Prioritize critical security issues
Step 4: Create Expert Launch Commands
File: .claude/commands/review-python.md
markdown# Launch Python Review Expert

## Purpose
Spawn specialized Python code review expert agent for comprehensive code analysis.

## Arguments
- {{files}}: Files or directories to review
- {{focus}}: Optional focus area (security/performance/style)

## Workflow

### 1. Prepare Context
Create review session context:
- Files to review: {{files}}
- Focus area: {{focus or "comprehensive"}}
- Timestamp: {{now}}

### 2. Launch Expert Agent
```bash
claude opus \
  --system-prompt .claude/agents/experts/python-reviewer/system-prompt.md \
  --yolo \
  "Review the following Python code: {{files}}" \
  > reviews/python-review-{{timestamp}}.md 2>&1 &
```

### 3. Create Tracking
Report file: `reviews/python-review-{{timestamp}}.md`
Session bundle: `.claude/agents/background/review-{{timestamp}}.bundle`

## Report
Expert agent launched:
- Type: Python Code Reviewer
- Files: {{file_count}} files
- Focus: {{focus}}
- Report: reviews/python-review-{{timestamp}}.md
Step 5: Execute Expert Agent
bash# Launch Python review expert
/review-python src/api/*.py security

# Launch multiple experts in parallel
/review-python src/ performance
/test-generator src/api/auth.py
/security-auditor src/
Expert Agent Orchestration
Multi-Expert Pipeline Example:
markdown# Full Code Quality Pipeline

## Stage 1: Security Audit (Blocking)
/security-auditor src/ → reports/security-audit.md
If critical issues found → STOP
Else → Continue to Stage 2

## Stage 2: Parallel Expert Reviews
Launch simultaneously:
- /review-python src/ → reviews/python-review.md
- /test-generator src/ → tests/generated-tests.md  
- /api-designer src/api/ → docs/api-review.md
- /performance-analyzer src/ → reports/performance.md

## Stage 3: Documentation Expert
After all reviews complete:
/doc-generator using:
- reviews/python-review.md
- docs/api-review.md
- reports/performance.md
→ docs/comprehensive-docs.md

## Stage 4: Integration Report
Aggregate all expert findings:
/integration-reporter → reports/final-quality-report.md
Expert Agent Best Practices
Design Principles:

✅ One responsibility per expert (single purpose)
✅ Deep domain knowledge in system prompt
✅ Consistent output formats (parseable)
✅ Clear success criteria (when is review "complete"?)
✅ Composable with other experts (standard interfaces)
✅ Fast execution (focused scope)

Anti-Patterns:

❌ Generic "reviewer" experts (too broad)
❌ Experts that need follow-up prompts (should be one-shot)
❌ Overlapping expert domains (creates confusion)
❌ Experts without checklists (inconsistent quality)


Resources & Next Steps
Key Takeaways

Master the R&D Framework

Reduce: Keep primary agent context lean
Delegate: Offload work to sub-agents and background agents


Progress Through Levels

Level 1 (Beginner): Clean up MCP servers, use context priming
Level 2 (Intermediate): Implement sub-agent delegation
Level 3 (Advanced): Use context bundles for session recovery
Level 4 (Agentic): Build multi-agent orchestration systems


Performance Principle

Agent performance degrades as context grows
Better agents → More focused agents → Specialized expert agents


Scale Strategy

Start with single agent optimization
Add sub-agents for parallel work
Build background agent workflows
Create expert agent libraries



Further Reading & Links
Official Documentation

Anthropic Claude API Documentation
Claude Prompt Engineering Guide
Model Context Protocol (MCP) Specification

Related Tutorials

Agentic Prompt Engineering (Extended Lesson)

Purpose, Variables, Workflow, Report Format
Prompt chaining patterns
Multi-step reasoning workflows


Claude Code Advanced Workflows (TAC Course)

In-loop vs. out-loop patterns
Zero-touch execution (ZTE)
Multi-agent orchestration UIs



Community Resources

Claude Code GitHub
MCP Servers Directory
Agent Engineering Patterns

Implementation Checklist
Week 1: Foundation

 Audit current context usage (claude context)
 Remove default MCP configurations
 Shrink claude.md to essentials (<50 lines)
 Create first context priming command
 Measure baseline token savings

Week 2: Intermediate

 Define first sub-agent system prompt
 Create sub-agent delegation command
 Test parallel sub-agent execution
 Monitor sub-agent token isolation
 Document sub-agent patterns

Week 3: Advanced

 Enable context bundle generation
 Test session recovery workflow
 Create milestone bundle
 Chain context bundles across days

Week 4: Agentic

 Create background agent launcher
 Build first expert agent
 Test parallel background agents
 Create expert orchestration pipeline
 Measure end-to-end performance

Next Steps

Start with One Technique

Pick the technique with highest immediate impact for your workflow
Implement fully before moving to next technique
Measure improvement (tokens saved, time saved, error reduction)


Build Your Context Engineering Library

Create .claude/ directory structure
Document your patterns
Share with your team


Measure and Iterate

Track context usage over time
Identify bottlenecks
Optimize high-frequency workflows first


Scale Gradually

Master single agent → sub-agents → background agents → expert agents
Don't skip levels
Build confidence at each stage



Questions to Guide Your Journey

Are you wasting tokens on unused MCP servers?
Is your claude.md growing out of control?
Could sub-agents handle your parallel processing tasks?
Do you need context bundles for long-running projects?
Would expert agents improve your code quality pipeline?

Final Thoughts

"Context engineering is the name of the game for high-value engineering in the age of agents."

Investing in context engineering is a safe bet because:

Performance decreases as context windows grow (fundamental limitation)
Tokens are expensive (cost optimization)
Focus improves quality (fewer errors)
Specialization enables scale (orchestrate more agents)

A focused agent is a performant agent.
The limits of what an engineer can do with well-orchestrated agents are unknown. Ignore the pessimists. Investigate the optimists. Build, ship, and scale with elite context engineering.

Tutorial Version: 1.0
Last Updated: 2025-11-28
Source: Elite Context Engineering with Claude Code
License: MIT

Get Started Now:
bash# 1. Check your current context
claude context

# 2. Create your context engineering directory
mkdir -p .claude/{commands,agents/experts,agents/background,agents/context-bundles}

# 3. Shrink your claude.md
# (Keep only absolute essentials)

# 4. Create your first prime command
touch .claude/commands/prime.md

# 5. Launch your first optimized session
claude opus --yolo
/prime
You now have everything you need to master context engineering. Ship with focused agents. 