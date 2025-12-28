---
title: "Claude Agent Skills: Zero-to-Production Guide"
date: "2025-12-28T03:10:00+02:00"
draft: false
tags: ["claude", "agent skills", "anthropic", "ai agents", "automation", "production"]
---

## Introduction

Claude Code introduces a powerful feature called **Skills**—a way to teach Claude repeatable, specialized capabilities that persist across sessions. Think of Skills as plugins for behavior: structured instruction sets that define exactly what Claude should do, when to do it, and which tools it can use.

Unlike one-off prompts that you type into chat, Skills are persistent, discoverable, and automatically selected by Claude based on context. They transform Claude from a general-purpose assistant into a specialized agent that can reliably perform complex, domain-specific tasks.

**What makes Skills powerful:**
- **Consistency** — Same input produces same behavior every time
- **Safety** — Explicit tool boundaries prevent unauthorized actions
- **Discoverability** — Claude automatically finds and uses relevant Skills
- **Production-ready** — Versioned, testable, and team-shareable

This guide will teach you everything from basic Skill creation to production deployment patterns.

**Official Documentation:** [Claude Skills Documentation](https://code.claude.com/docs/en/skills)

---

## 1. What Claude Skills Are (Precisely)

### Definition

**A Claude Skill is a structured, local capability that teaches Claude:**
- **What** to do (the procedure)
- **When** to apply it (the trigger condition)
- **Which tools** it may use (the safety boundary)

Skills enable reliable, repeatable agent behavior in production.

### Key characteristics

**1. Local and file-based**
- Skills live in your project's `.claude/skills/` directory
- They're just markdown files with structured frontmatter
- Version controlled with your codebase

**2. Automatically loaded**
- Claude Code discovers Skills at startup
- No manual registration required
- Always available when relevant

**3. Dynamically selected**
- Claude reads the user's request
- Matches it against Skill descriptions
- Activates the most relevant Skill automatically

**4. NOT just prompts**
- Prompts are one-time, conversational inputs
- Skills are persistent, structured capabilities
- Skills have tool boundaries and repeatability guarantees

### What Skills enable

With Skills, Claude can:

**1. Follow repeatable procedures**
- Same input → same process → same output
- Critical for production workflows
- Eliminates "works sometimes" problems

**2. Respect tool boundaries**
- Each Skill explicitly lists allowed tools
- Claude cannot use unauthorized tools
- Built-in safety and sandboxing

**3. Apply domain-specific behavior**
- Database auditing Skills for DBAs
- Code review Skills for engineers
- Security analysis Skills for DevSecOps

**4. Operate consistently across sessions**
- Skills persist between conversations
- No need to re-explain procedures
- Team members get the same behavior

### The big picture

**This is the foundation of Claude as an agent, not just a chatbot.**

Traditional chatbots:
- Respond to queries
- Context limited to current conversation
- Behavior varies based on phrasing

Claude with Skills:
- Performs tasks autonomously
- Persistent capabilities across sessions
- Consistent, predictable behavior

## 2. Mental Model: How Claude Uses Skills

Understanding how Claude selects and uses Skills is crucial for designing effective ones.

### The selection process

Claude performs skill selection **internally and automatically**. Here's the runtime flow:

**Step 1: User request arrives**
```
User: "Analyze the database schema for performance issues"
```

**Step 2: Claude scans available Skills**
- Reads all Skill descriptions in `.claude/skills/`
- Evaluates relevance to the user's intent
- Considers specificity and clarity of matches

**Step 3: Claude selects the most relevant Skill**
- Chooses based on description match quality
- Prefers more specific over more general
- May ask for clarification if ambiguous

**Step 4: Claude follows Skill instructions exactly**
- Treats the Skill's instructions as primary guidance
- Executes steps in order
- Maintains procedure consistency

**Step 5: Claude uses only allowed tools**
- Respects the `allowed-tools` list
- Refuses to use tools not in the list
- May ask user for permission if blocked

### Important principles

**1. Skills are opt-in, not forced**
- Claude won't use a Skill if it's not relevant
- No Skill = normal Claude behavior
- Users can always override Skill selection

**2. All-or-nothing activation**
- Claude doesn't "partially" use a Skill
- Either the full Skill is active, or none of it is
- No mixing Skill and non-Skill behavior

**3. Specificity wins**
- More specific descriptions match better
- Generic Skills get deprioritized
- Clear boundaries improve selection accuracy

## 3. Skill Lifecycle (End-to-End)

Here's the complete flow from user intent to output:

```
┌─────────────────┐
│  User Intent    │  "Review this pull request"
└────────┬────────┘
         ↓
┌─────────────────┐
│ Skill Matching  │  Scans: pr-reviewer, code-analyzer, etc.
└────────┬────────┘
         ↓
┌─────────────────┐
│ Skill Selected  │  Selects: pr-reviewer (best match)
└────────┬────────┘
         ↓
┌─────────────────┐
│ Instructions    │  Follows SKILL.md step-by-step
└────────┬────────┘
         ↓
┌─────────────────┐
│ Tool Usage      │  Uses only allowed tools (Read, Grep)
└────────┬────────┘
         ↓
┌─────────────────┐
│ Output          │  Structured review report
└─────────────────┘
```

### Key insight

**Claude will not partially apply a Skill — it either uses it fully or doesn't use it at all.**

This ensures:
- Predictable behavior
- No confusion between Skill and non-Skill responses
- Clear debugging (did the Skill activate or not?)

## 4. Skill File Structure (Canonical)

A Skill is a directory containing at minimum one required file.

### Directory structure

```
.claude/skills/my-skill/
├── SKILL.md        # REQUIRED - Core Skill definition
├── reference.md    # Optional - Domain knowledge
├── examples.md     # Optional - Input/output examples
├── scripts/        # Optional - Helper scripts
└── data/           # Optional - Reference data
```

### File purposes

**SKILL.md (REQUIRED)**
- Defines when the Skill applies
- Specifies what Claude must do
- Lists which tools Claude may use
- Contains step-by-step instructions

**reference.md (Optional)**
- Domain-specific knowledge
- Internal standards and conventions
- Definitions and glossaries
- Style guides and best practices
- Only loaded when Skill is active

**examples.md (Optional)**
- Canonical input examples
- Expected output formats
- Edge case handling
- Dramatically improves reliability

**scripts/ (Optional)**
- Validation scripts
- Formatting tools
- Internal helpers
- Only executed if explicitly allowed and referenced

**data/ (Optional)**
- Reference datasets
- Configuration files
- Lookup tables
- Context files

## 5. SKILL.md — Required Structure

The SKILL.md file has two mandatory sections: **frontmatter** and **instructions**.

### 5.1 Frontmatter (Mandatory)

The frontmatter is YAML metadata at the top of the file:

```markdown
---
name: database-auditor
description: Analyze SQL schemas and identify performance risks, security issues, and optimization opportunities.
allowed-tools:
  - Read
  - Grep
---
```

**Field requirements:**

**`name`** (required)
- Must be unique across all Skills
- Use kebab-case (lowercase with hyphens)
- Descriptive and specific
- Example: `pr-reviewer`, `security-scanner`, `test-generator`

**`description`** (required)
- Clear explanation of when to use this Skill
- Should match user intent patterns
- Specific enough to avoid ambiguity
- This is what Claude uses for Skill selection

**`allowed-tools`** (required)
- YAML list of tool names
- Strictly limits Claude's capabilities
- If a tool is not listed, Claude CANNOT use it
- Common tools: Read, Write, Edit, Grep, Glob, Bash, etc.

**Critical rule:**
> If a tool is not in the `allowed-tools` list, Claude cannot use it. No exceptions.

### 5.2 Instructions Section

After the frontmatter, provide explicit operational instructions:

```markdown
## Instructions

When this Skill is selected:

1. Identify the database type (PostgreSQL, MySQL, etc.) from file extensions and syntax
2. Locate and read schema files (*.sql, migrations/, schema.rb)
3. Review the following for each table:
   - Table structure and column types
   - Indexes (identify missing indexes on foreign keys)
   - Constraints (primary keys, foreign keys, unique constraints)
4. Flag the following issues:
   - **Performance:** Missing indexes, unbounded queries, N+1 patterns
   - **Security:** Unencrypted sensitive columns, missing access controls
   - **Data integrity:** Missing foreign keys, nullable columns that shouldn't be
5. Generate a structured report with:
   - Executive summary (2-3 sentences)
   - Issues by severity (Critical, Warning, Info)
   - Specific recommendations with code examples
6. Do NOT modify any files without explicit user permission
```

**Key principles:**

**1. Be procedural, not conversational**
- Use numbered steps
- Specify exact actions
- Define clear deliverables

**2. Be explicit, not clever**
- Say exactly what Claude should do
- Don't rely on "best judgment"
- Remove ambiguity

**3. Include guardrails**
- Specify what NOT to do
- Define boundaries clearly
- Protect against unintended actions

## 6. Writing High-Quality Skill Instructions

Great Skills come from great instructions. Here's how to write them.

### 6.1 Be explicit, not clever

**Bad:**
```
"Help the user analyze their database."
```

Problems:
- What does "help" mean?
- What does "analyze" entail?
- What should the output be?

**Good:**
```
"Enumerate all tables, identify missing indexes on foreign keys,
flag unbounded queries without LIMIT clauses, and summarize
security and performance risks in a structured report."
```

Benefits:
- Clear actions
- Specific deliverables
- Measurable completion

**Key insight:** Claude executes your exact wording. Be precise.

### 6.2 Step-based instructions work best

Claude reliably follows:
- **Ordered lists** — numbered steps create clear sequence
- **Clear stages** — each step has obvious start and end
- **Explicit termination** — define when the task is complete

**Example of good step-based instructions:**

```markdown
## Instructions

1. **Discover:** Scan the repository for test files (test/, spec/, *_test.*)
2. **Analyze:** For each test file, identify:
   - Test framework (Jest, PyTest, etc.)
   - Coverage gaps (uncovered functions)
   - Flaky tests (marked with skip/xfail)
3. **Report:** Generate a summary with:
   - Total test count
   - Coverage percentage
   - List of high-priority gaps
4. **Recommend:** Suggest 3 specific tests to write first
5. **Stop:** Do NOT write any tests unless explicitly asked
```

### 6.3 Avoid vague language

**Words to avoid:**
- "Try to..." (implies optional)
- "If possible..." (creates ambiguity)
- "Use best judgment..." (no clear guidance)
- "Consider..." (is this required or optional?)
- "Maybe..." (definitely remove this)

**Words to use:**
- "Identify..." (clear action)
- "List..." (specific deliverable)
- "Flag..." (concrete output)
- "Must..." (required step)
- "Never..." (clear boundary)

## 7. Tool Control & Safety (Critical)

Tool boundaries are **enforced**, not advisory. This is a core safety feature.

### 7.1 Allowed tools are strictly enforced

Claude will:

**1. Refuse to use unlisted tools**
```
User: "Now deploy the changes"
Claude: "I cannot use the Bash tool - it's not in my allowed tools for
        this Skill. Would you like me to exit the Skill and help with
        deployment?"
```

**2. Ask for clarification if blocked**
- Explains which tool is missing
- Suggests alternatives
- Offers to exit Skill mode

**3. Continue safely within boundaries**
- Works with available tools only
- No workarounds or clever bypasses
- Maintains safety posture

### Example: Read-only Skill

```yaml
---
name: security-auditor
description: Analyze code for security vulnerabilities and best practice violations.
allowed-tools:
  - Read
  - Grep
  - Glob
---
```

**With these tools, Claude CAN:**
- Read source files
- Search for patterns
- Find files by name
- Analyze code structure

**With these tools, Claude CANNOT:**
- Write or modify files
- Execute commands
- Run tests
- Deploy changes
- Call external APIs

**The boundary is absolute.** No exceptions, no special cases.

### 7.2 Skill-level sandboxing

Each Skill acts as a sandboxed capability with its own permission boundary.

**Production pattern: Separation of concerns**

**1. Analysis Skills (read-only)**
```yaml
allowed-tools: [Read, Grep, Glob]
```
- Code review
- Security audits
- Performance analysis
- Documentation review

**2. Modification Skills (write-capable)**
```yaml
allowed-tools: [Read, Edit, Write]
```
- Code fixes
- Refactoring
- Documentation updates
- Configuration changes

**3. Execution Skills (command-capable)**
```yaml
allowed-tools: [Read, Bash]
```
- Running tests
- Building projects
- Starting services
- Deployment operations

**4. Approval Skills (no tools)**
```yaml
allowed-tools: []
```
- Review and approve plans
- Make decisions
- Provide guidance
- No direct file or system access

**Why separate Skills?**

| Benefit | Explanation |
|---------|-------------|
| **Safety** | Limit blast radius of mistakes |
| **Clarity** | Each Skill has clear capabilities |
| **Auditability** | Easy to track what happened |
| **Composability** | Chain Skills for complex workflows |

**Example workflow:**

```
1. security-auditor (read-only)
   → Identifies issues

2. User reviews findings

3. security-fixer (write-capable)
   → Implements fixes

4. test-runner (execution-capable)
   → Verifies fixes work
```

Each stage has exactly the permissions it needs, nothing more.

## 8. Optional Supporting Files

Beyond SKILL.md, you can add supporting files to enhance Skill effectiveness.

### 8.1 reference.md

Use this file for domain-specific knowledge that Claude should reference when using the Skill.

**Good use cases:**
- **Domain knowledge:** API specifications, protocol details
- **Internal standards:** Company coding conventions, style guides
- **Definitions:** Technical terminology, acronyms
- **Best practices:** Security guidelines, performance patterns

**Example reference.md for a code review Skill:**

```markdown
# Code Review Standards

## Security Requirements
- All database queries must use parameterized statements
- API keys must never be committed to the repository
- User input must be sanitized before use

## Performance Guidelines
- Database queries should have LIMIT clauses
- N+1 query patterns should be avoided
- Large lists should be paginated

## Style Conventions
- Use descriptive variable names (no single letters except loop counters)
- Functions should be under 50 lines
- Comments should explain "why", not "what"
```

**Key point:** Claude reads reference.md **only when the Skill is selected**. It's not global context.

### 8.2 examples.md

Provide concrete examples to dramatically improve Skill reliability.

**What to include:**
- **Canonical inputs:** Representative examples of what the Skill processes
- **Expected outputs:** The format and structure Claude should produce
- **Edge cases:** Unusual inputs and how to handle them

**Example examples.md for a test generator Skill:**

```markdown
# Test Generation Examples

## Example 1: Simple function

Input function:
\```python
def calculate_discount(price, percentage):
    return price * (1 - percentage / 100)
\```

Expected test output:
\```python
def test_calculate_discount():
    assert calculate_discount(100, 10) == 90.0
    assert calculate_discount(50, 20) == 40.0
    assert calculate_discount(100, 0) == 100.0
    assert calculate_discount(100, 100) == 0.0
\```

## Example 2: Edge case - division by zero

Input function:
\```python
def divide(a, b):
    return a / b
\```

Expected test output:
\```python
def test_divide():
    assert divide(10, 2) == 5
    assert divide(10, 5) == 2

    with pytest.raises(ZeroDivisionError):
        divide(10, 0)
\```
```

**Why this matters:** Examples ground Claude's behavior in concrete patterns.

### 8.3 scripts/

Add helper scripts that Claude can invoke if explicitly allowed.

**Common use cases:**
- **Validation scripts:** Check code quality, run linters
- **Formatting tools:** Auto-format code, normalize data
- **Internal helpers:** Custom analysis tools, report generators

**Example scripts/ directory:**

```
.claude/skills/code-quality/
├── SKILL.md
├── scripts/
│   ├── run_linter.sh      # Run ESLint/PyLint
│   ├── check_types.sh     # Run type checker
│   └── analyze_complexity.py  # Calculate cyclomatic complexity
```

**Critical safety rules:**

**1. Scripts are NOT executed unless:**
- The `Bash` tool is in `allowed-tools`
- The script is explicitly referenced in instructions
- The user approves execution (if configured)

**2. Scripts should be:**
- Idempotent (safe to run multiple times)
- Read-only when possible
- Well-documented
- Error-handling aware

**Example SKILL.md with script usage:**

```markdown
---
name: code-quality-checker
description: Run static analysis tools and report code quality issues.
allowed-tools:
  - Read
  - Bash
---

## Instructions

1. Identify the project language from file extensions
2. Run the appropriate linter:
   - JavaScript/TypeScript: `bash scripts/run_linter.sh`
   - Python: `bash scripts/check_types.sh`
3. Parse the output and categorize issues by severity
4. Generate a report with the top 10 issues to fix first
```

## 9. Skill Selection Behavior (Important)

Understanding how Claude chooses Skills helps you design better ones.

### When Claude selects a Skill

Claude activates a Skill when all these conditions are met:

**1. User intent matches the description**
- The Skill's `description` field aligns with what the user asked
- Keywords and concepts overlap
- The task fits the Skill's purpose

**2. The Skill is clearly relevant**
- Not ambiguous or borderline
- Obviously the right tool for the job
- No competing Skills that match better

**3. Instructions are unambiguous**
- Steps are clear and actionable
- No conflicting guidance
- Claude can confidently execute

### If multiple Skills match

**Specificity wins.**

**Example:**

Skills available:
1. `code-analyzer` — "Analyze code for any issues"
2. `security-scanner` — "Analyze code for security vulnerabilities"

User request: "Check this code for SQL injection risks"

**Claude selects:** `security-scanner` (more specific to the security concern)

### How to improve Skill selection

**1. Write specific descriptions**
```yaml
# Vague (bad)
description: Help with code

# Specific (good)
description: Review pull requests for code quality, test coverage,
             and adherence to team conventions
```

**2. Use clear trigger phrases**
```yaml
description: Generate unit tests for Python functions using pytest.
             Trigger phrases: "write tests", "add test coverage",
             "generate tests for..."
```

**3. Define clear boundaries**
```yaml
description: Analyze database schemas for performance issues.
             Does NOT: modify schemas, run migrations, or change data.
             Focus: read-only analysis and recommendations.
```

## 10. Production Skill Design Patterns

Here are proven patterns for building production-ready Skills.

### Pattern 1: Reviewer Skill (read-only analysis)

**Characteristics:**
- No write access
- Output is analysis only
- Cannot modify anything
- Safe to run repeatedly

**Use cases:**
- Code review
- Security audits
- Performance analysis
- Compliance checking

**Example:**
```yaml
---
name: pr-reviewer
description: Review pull requests for code quality, test coverage, and best practices.
allowed-tools:
  - Read
  - Grep
  - Glob
---

## Instructions
1. Identify all changed files in the PR
2. Review each file for:
   - Code quality issues
   - Missing tests
   - Security concerns
   - Performance problems
3. Generate a structured review with:
   - Summary (approve/request changes)
   - Specific issues with file:line references
   - Suggested improvements
4. Do NOT modify any files
```

### Pattern 2: Executor Skill (controlled actions)

**Characteristics:**
- Narrow, well-defined scope
- Explicit actions only
- Strong guardrails
- Clear success/failure criteria

**Use cases:**
- Running tests
- Applying fixes
- Formatting code
- Generating boilerplate

**Example:**
```yaml
---
name: test-runner
description: Run project tests and report failures with details.
allowed-tools:
  - Read
  - Bash
---

## Instructions
1. Identify the test framework (package.json, requirements.txt, etc.)
2. Run tests with appropriate command:
   - JavaScript: `npm test`
   - Python: `pytest`
3. If tests fail:
   - Parse output to identify failing tests
   - Show stack traces for each failure
   - Suggest likely causes
4. Do NOT modify test files or source code
```

### Pattern 3: Planner Skill (no tools)

**Characteristics:**
- No tool access
- Outputs structured plans
- Used upstream of execution
- Pure reasoning, no actions

**Use cases:**
- Architecture planning
- Migration strategies
- Implementation plans
- Decision making

**Example:**
```yaml
---
name: refactoring-planner
description: Create detailed refactoring plans for codebases.
allowed-tools: []
---

## Instructions
1. Understand the refactoring goal from user input
2. Identify affected files and modules
3. Create a step-by-step plan with:
   - Phase breakdown (what to do when)
   - Risks and mitigation strategies
   - Testing approach for each phase
   - Rollback procedures
4. Output as structured markdown with checkboxes
5. Do NOT execute any refactoring steps
```

## 11. Anti-Patterns to Avoid

Common mistakes that make Skills unreliable or unsafe:

### 1. One Skill that "does everything"

**Problem:**
```yaml
name: do-anything
description: Help with any task
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
```

**Why it's bad:**
- No clear purpose
- Over-permissioned
- Hard to maintain
- Unpredictable behavior

**Better:** Create specific Skills for specific tasks

### 2. Vague descriptions

**Problem:**
```yaml
description: Code helper
```

**Why it's bad:**
- When would Claude use this?
- What does "helper" mean?
- Ambiguous matching

**Better:**
```yaml
description: Generate unit tests for JavaScript functions using Jest
```

### 3. Over-permissive tool lists

**Problem:**
```yaml
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
```

**Why it's bad:**
- More tools = more risk
- Unclear what the Skill actually does
- Harder to audit

**Better:** Minimum necessary tools
```yaml
allowed-tools: [Read, Grep]
```

### 4. Hidden assumptions

**Problem:**
```markdown
## Instructions
1. Find the main application file
2. Analyze its structure
```

**Why it's bad:**
- What's a "main application file"?
- How should Claude find it?
- What if there are multiple?

**Better:**
```markdown
## Instructions
1. Find the main application file:
   - Look for: index.js, main.py, app.js, or server.js
   - If multiple exist, use the one in the root directory
2. Read the file and identify...
```

### 5. Mixing planning and execution

**Problem:**
```markdown
## Instructions
1. Analyze the codebase
2. Decide what needs refactoring
3. Refactor the code
4. Run tests
```

**Why it's bad:**
- Steps 1-2 are planning
- Steps 3-4 are execution
- Should be separate Skills

**Better:** Two Skills
- `refactoring-analyzer` (read-only, creates plan)
- `refactoring-executor` (executes approved plan)

## 12. Testing & Iteration Workflow

Skills improve through iteration. Here's the recommended development loop:

### The iteration cycle

**1. Write the Skill**
- Create `.claude/skills/my-skill/SKILL.md`
- Define name, description, and allowed-tools
- Write step-by-step instructions

**2. Restart Claude Code**
- Skills are loaded at startup
- Use CMD/CTRL + R or restart the application
- Verify the Skill was discovered

**3. Check Skill availability**
```
User: "What Skills are available?"
Claude: Lists all Skills with their descriptions
```

**4. Trigger the Skill explicitly**
```
User: "Use the database-auditor Skill on schema.sql"
```

**5. Observe behavior**
- Did Claude select the right Skill?
- Did it follow the instructions?
- Were the tools used correctly?
- Was the output structured as expected?

**6. Refine instructions**
- Tighten ambiguous steps
- Add missing guardrails
- Clarify expected outputs
- Fix tool usage issues

**7. Repeat**

### Key insight

**Skills improve incrementally — don't overdesign upfront.**

Start simple:
- Basic instructions
- Minimal tools
- Core functionality

Then iterate based on real usage.

### Debugging tips

**Skill not activating?**
- Check the description matches user intent
- Make the description more specific
- Verify the Skill file is in `.claude/skills/`

**Wrong tool usage?**
- Be more explicit in instructions
- Add examples of correct tool usage
- Check tool is in `allowed-tools` list

**Inconsistent behavior?**
- Remove vague language ("try", "if possible")
- Add more procedural steps
- Include examples.md with expected patterns

## 13. Versioning & Team Use

In production, Skills are code. Treat them accordingly.

### Production best practices

**1. Store Skills in Git**
```bash
git add .claude/skills/
git commit -m "Add database audit Skill"
```

**2. Code review SKILL.md changes**
- Skills affect Claude's behavior
- Review like you review code
- Check for safety issues

**3. Treat Skills like infrastructure**
- Document changes in commit messages
- Tag releases when Skills change significantly
- Maintain backwards compatibility when possible

**4. Maintain changelogs**
```markdown
# Changelog - database-auditor Skill

## v2.0.0 - 2025-12-28
- Added security vulnerability checks
- Now flags unencrypted sensitive columns
- Breaking: Changed output format to JSON

## v1.0.0 - 2025-12-01
- Initial release
- Basic schema analysis
```

**5. Version Skill names if needed**
```
database-auditor-v1/
database-auditor-v2/
```

### Team collaboration

**Shared Skill repository:**
```
company-claude-skills/
├── code-review/
├── test-generator/
├── security-scanner/
└── deployment-helper/
```

**Usage:**
```bash
# Clone team Skills
git clone git@github.com:company/claude-skills.git .claude/skills
```

**Benefits:**
- Consistent behavior across team
- Shared improvements
- Centralized maintenance
- Onboarding efficiency

### The key insight

**Claude Skills are behavioral APIs.**

Just like you version APIs, version Skills. Just like you test APIs, test Skills.

## 14. When to Use Skills vs Normal Prompting

Not every interaction needs a Skill. Here's when to use each.

### Use Skills when:

**1. Behavior must be consistent**
```
Example: Code review process must follow company standards
Solution: Create a pr-reviewer Skill
```

**2. Tasks repeat**
```
Example: Daily security scans of new code
Solution: Create a security-scanner Skill
```

**3. Safety matters**
```
Example: Database migrations must be reviewed, not executed
Solution: Create read-only migration-reviewer Skill
```

**4. Tools are involved**
```
Example: Running tests requires Bash tool
Solution: Create test-runner Skill with explicit Bash permission
```

**5. Team needs shared behavior**
```
Example: All engineers should use same test generation approach
Solution: Create shared test-generator Skill
```

### Do NOT use Skills for:

**1. One-off creative tasks**
```
Example: "Help me brainstorm product names"
Solution: Just use normal Claude conversation
```

**2. Casual chat**
```
Example: "What's the best way to learn Rust?"
Solution: No Skill needed, normal interaction
```

**3. Exploratory brainstorming**
```
Example: "Let's explore different architecture approaches"
Solution: Free-form conversation is better
```

**4. Highly variable tasks**
```
Example: "Help me debug whatever error I'm seeing"
Solution: Too variable for a Skill, use normal Claude
```

### The decision framework

```
Is this task:
├── Repeatable? ──No──→ Normal prompting
│       │
│      Yes
│       │
├── Needs specific tools? ──No──→ Consider Skill for consistency
│       │
│      Yes
│       │
└── CREATE A SKILL
```

## 15. Official Documentation (Source of Truth)

Everything in this guide is based on the official documentation.

**Authoritative reference:**
[Claude Skills Documentation](https://code.claude.com/docs/en/skills)

This is the only official source for:
- Skill file structure
- Tool enforcement behavior
- Selection mechanics
- Best practices

**When in doubt, consult the official docs.**

---

## Final Takeaway

Claude Skills are the foundation of production Claude agents.

### What makes Skills special:

**1. Deterministic**
- Same input → same behavior
- No "sometimes works" problems
- Predictable and reliable

**2. Composable**
- Skills can work together
- Chain them for complex workflows
- Build libraries of capabilities

**3. Safe**
- Tool boundaries are enforced
- Read-only Skills can't cause damage
- Explicit permissions model

**4. Production-ready**
- Version controlled
- Team shareable
- Auditable and testable

### The core primitive

**Skills are the core primitive for building Claude agents that work the same way every time.**

Not "usually works."
Not "works if you phrase it right."
**Works. Every time.**

That's what makes them production-ready.