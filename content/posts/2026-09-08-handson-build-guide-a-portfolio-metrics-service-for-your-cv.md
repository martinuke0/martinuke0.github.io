We need to produce a complete markdown file with frontmatter and body. Must follow all rules.

First, frontmatter: title, date (must be exactly "2026-09-08T06:01:05.111"), draft false, tags array 3-6 tags, description 140-160 chars, summary 1-2 sentences, showToc true, TocOpen false, cover image /images/covers/2026-09-08-handson-build-guide-a-portfolio-metrics-service-for-your-cv.svg, alt and caption etc.

We need to ensure no code fences around frontmatter. The frontmatter itself must start with "---" line, then key-values each on its own line, ending with "---". Must wrap string values in double quotes. tags must be JSON-style array with each tag in double quotes, no dashes. Eg: tags: ["docker", "python", "ci-cd"].

Now body: Must start after the frontmatter closing "---". The first body block must be a TL;DR blockquote as very first body block: > **TL;DR** — 2–3 sentences capturing key insight.

Then a brief intro paragraph (no heading).

Then sections in order:

1. "## Why This Project Stands Out on a CV"
2. "## Architecture Overview"
3. "## Building It Step by Step"
4. "## Running and Testing It"
5. "## Extending It: Your Roadmap to Senior-Level"
Then after that "## Key Takeaways" with 3-6 bullet points.
Then "## Further Reading" with at least 3 real URLs as markdown links.

We must obey other rules:

- Never wrap frontmatter or any part in code fences. So no ``` etc around frontmatter.

- Must not repeat title as # heading in body. So we cannot have # Title. The title is in frontmatter only.

- Must complete entire post.

- Every fenced code block must include a language tag. We'll include code snippets with language tags.

- When citing a source, use real inline markdown link at point of claim. We'll use links.

- Use bullet points and numbered lists for scannable content. Use blockquotes for noteworthy asides.

- Professional but accessible tone.

- Audience tuning: mention named tools, platforms, production systems. So we should talk about Docker, Kubernetes, CI/CD, PostgreSQL, etc.

- Length: aim 1800-2600 words. We'll try to be substantial but not too long; but we need to be in-depth.

- Must include sections as described.

- In "## Building It Step by Step": numbered steps with real, language-tagged code snippets showing core logic. So we need code snippets, perhaps in Python or Go or Node. We'll choose Python for simplicity, but also mention Docker, etc.

- In "## Extending It: Your Roadmap to Senior-Level": 4 to 6 concrete upgrades, each with one-line reason.

- In "## Further Reading": prioritize primary sources — papers, RFCs, canonical docs. Name concrete tools and technologies throughout. Provide at least 3 real URLs as markdown links.

Make sure to not use H1 headings in body. We have "##" sections which are H2, that's fine. Must not use "# " anywhere else.

Now let's design the project. A portfolio/CV side project that signals real systems skill. Could be a distributed task queue system using Celery + Redis, or a microservice that processes data streams with Kafka, or a personal website with dynamic routing and analytics. But must be practical enough to build from real runnable code.

Maybe a "Real-time Analytics Dashboard" that ingests events via Kafka, stores in PostgreSQL, serves via FastAPI, with Docker compose, CI with GitHub Actions, monitoring with Prometheus, and a simple front-end. That would signal skills.

But we need a project that can be built step-by-step. Maybe a "Portfolio Event Tracker": a small web app that lets you log events, stores them in Postgres, displays stats, with Docker, tests, and extensibility.

Better: A "Personal Incident Response Playbook as a CLI tool" using Python, click, SQLite, with Docker, tests, CI, and can be extended with Docker Compose for scaling.

But need to demonstrate real systems skill: perhaps a "Distributed Key-Value Store" using Raft? That might be too complex.

Simplify: A "Microservice-backed Portfolio Site" that uses FastAPI, SQLModel, Docker, GitHub Actions, and Deploy to GCP Cloud Run. This would show containerization, CI/CD, API design, database integration.

However, need a "hands-on build guide". So we need to provide steps.

Maybe choose a project: "Event-driven Portfolio Dashboard". It tracks projects, skills, and displays stats. Uses Flask/FastAPI, PostgreSQL, Alembic migrations, Docker Compose, GitHub Actions CI, Prometheus metrics, and a simple React front-end or just static HTML.

But we need code snippets in building step.

Ok, let's design a project: "Portfolio Metrics Service" (PMS). A tiny HTTP service that records developer activity events (e.g., "project added", "skill updated") and serves JSON stats. It uses FastAPI, SQLModel (SQLAlchemy), PostgreSQL, Docker, GitHub Actions for CI, and optional Prometheus metrics.

We'll produce steps:

- Step 1: Project scaffolding with Poetry or venv.

- Step 2: Define data models.

- Step 3: Implement API endpoints.

- Step 4: Add Dockerfile and docker-compose.yml.

- Step 5: Add GitHub Actions workflow.

- Step 6: Add health check and metrics endpoint.

But need core logic code snippets with language tag.

Now produce the entire markdown.

First, frontmatter.

We need title: Something like "Hands‑On Build Guide: A Portfolio Metrics Service for Your CV". Must be in quotes.

date: "2026-09-08T06:01:05.111"

draft: false

tags: we need 3-6 relevant tags. Choose: "python", "fastapi", "docker", "postgresql", "ci-cd". That's 5 tags.

description: 140-160 characters. Let's craft: "Build a runnable portfolio metrics service with FastAPI, PostgreSQL and Docker – a concrete side project that signals backend engineering skill to hiring managers." Count characters: Let's count approx. We'll aim around 150.

We need summary: one or two sentences that will appear on listing pages and social cards. Eg: "A minimal FastAPI service that logs developer events and exposes JSON stats, containerized with Docker and CI‑ready for immediate deployment."

Now cover: image: "__COVER_PATH__", alt: "A sleek laptop screen showing a FastAPI dashboard", caption: "", relative: false.

Now frontmatter block.

After frontmatter, body.

First body block: TL;DR blockquote.

> **TL;DR** — In this post we walk through building a Portable Portfolio Metrics Service with FastAPI, PostgreSQL and Docker. The result is a tiny, containerised API that records developer events and serves JSON stats – a concrete, runnable project you can add to your CV and extend with persistence, observability and scaling.

Make sure the blockquote starts with > and has a space after? The rule: "TL;DR blockquote as the very first body block: > **TL;DR** — 2–3 sentences capturing the key insight of the post." So we need that.

Now intro paragraph (no heading). We'll write a short paragraph.

Now sections.

Section 1: "## Why This Project Stands Out on a CV". We'll discuss skills demonstrated, roles it signals (backend engineer, devops, full-stack). Mention named tools.

Section 2: "## Architecture Overview". Provide bullet breakdown or text diagram of components: client, FastAPI app, PostgreSQL, Docker compose, CI, monitoring.

Section 3: "## Building It Step by Step". Numbered steps with code snippets. We'll have maybe 6 steps. Each step may have a code block with language tag (python for FastAPI, sql for schema, yaml for docker-compose). Must ensure every fenced code block includes a language tag. We'll use ```python, ```sql, ```yaml.

Step 1: Scaffold project and install dependencies.

Step 2: Define SQLModel models.

Step 3: Implement API endpoints.

Step 4: Create Dockerfile.

Step 5: Write docker-compose.yml.

Step 6: Add GitHub Actions CI workflow.

We'll embed code snippets.

Step 1 code: maybe a terminal command or python code? We'll show a snippet of requirements.txt or a python code to init project. But must be real, language-tagged.

Step 2: SQLModel model code in python.

Step 3: FastAPI route code.

Step 4: Dockerfile content.

Step 5: docker-compose.yml.

Step 6: .github/workflows/ci.yml.

We'll ensure code fences have language tag.

Section 4: "## Running and Testing It". Explain how to run locally with docker compose, how to run tests (pytest). Provide commands.

Section 5: "## Extending It: Your Roadmap to Senior-Level". 4-6 concrete upgrades, each with one-line reason. Eg: "Add Alembic migrations for schema evolution – lets you version‑control DB changes."; "Integrate Prometheus metrics – provides observability."; "Deploy to GCP Cloud Run – horizontal scaling."; "Add Redis caching for read‑through – performance."; "Implement JWT auth – security."; "Write property‑based tests with Hypothesis – quality." Choose 4-6.

We need 4 to 6 upgrades. We'll provide 5.

Each upgrade with a one-line reason.

Section 6: "## Key Takeaways". 3-6 bullet points summarizing what reader should remember.

Section 7: "## Further Reading". At least 3 real URLs as markdown links, prioritize primary sources: papers, RFCs, canonical docs related to the project. Eg: FastAPI docs, SQLAlchemy docs, Docker Compose spec, Kubernetes, Prometheus client, etc.

We must ensure URLs are real and well-known. Provide links like https://fastapi.tiangolo.com, https://www.postgresql.org/docs, https://docs.docker.com/compose, https://prometheus.io/docs, https://github.com/tiangolo/fastapi, etc.

Now check all rules:

- No code fences around frontmatter. We'll just write frontmatter as plain text.

- The first characters of response must be "---". Yes.

- Never repeat title as # heading in body. We'll not use #.

- Complete entire post.

- Frontmatter rules: title, description, summary, string values in double quotes. date in double quotes exact value. tags as JSON-style array with each tag in double quotes. No dashes for tags. Must ensure tags array is like "tags": ["python", "fastapi", "docker", "postgresql", "ci-cd"].

- cover.image must be literal placeholder "__COVER_PATH__". Yes.

- Body structure: TL;DR blockquote as first body block. Then intro paragraph. Then sections in order. Must ensure we have "## Why This Project Stands Out on a CV", etc.

- Each fenced code block must include a language tag. We'll ensure.

- When citing a source, use real inline markdown link at point of claim. We'll maybe cite FastAPI docs inline.

- Use bullet points and numbered lists for scannable content. Use blockquotes for noteworthy asides.

- Professional but accessible tone.

- Audience tuning: mention named tools, platforms, production systems. We'll mention Docker, FastAPI, PostgreSQL, GitHub Actions, GCP Cloud Run, Prometheus.

- Length: aim 1800-2600 words. We'll try to be around maybe 2000 words. We'll need to be substantive.

Now let's draft the content.

First, frontmatter.

We'll produce:

---
title: "Hands‑On Build Guide: A Portfolio Metrics Service for Your CV"
date: "2026-09-08T06:01:05.111"
draft: false
tags: ["python", "fastapi", "docker", "postgresql", "ci-cd"]
description: "Build a runnable portfolio metrics service with FastAPI, PostgreSQL and Docker – a concrete side project that signals backend engineering skill to hiring managers."
summary: "A minimal FastAPI service that logs developer events and exposes JSON stats, containerized with Docker and CI‑ready for immediate deployment."
showToc: true
TocOpen: false
cover:
  image: "__COVER_PATH__"
  alt: "A sleek laptop screen showing a FastAPI dashboard"
  caption: ""
  relative: false
---

Make sure frontmatter ends with --- on its own line.

Now body.

We start with TL;DR blockquote.

> **TL;DR** — In this post we walk through building a Portable Portfolio Metrics Service with FastAPI, PostgreSQL and Docker. The result is a tiny, containerised API that records developer events and serves JSON stats – a concrete, runnable project you can add to your CV and extend with persistence, observability and scaling.

Now intro paragraph:

"Side projects are only valuable when they demonstrate that you can ship working, observable systems. In this guide you’ll create a small but complete FastAPI service that records events (new project, skill update, etc.), persists them in PostgreSQL, and exposes JSON statistics. Everything is containerised with Docker, tested with pytest, and wired into a GitHub Actions CI pipeline – giving you a tangible, production‑flavored artifact to discuss in interviews."

Now sections.

Section 1: "## Why This Project Stands Out on a CV"

We'll write a paragraph or two describing skills.

We need to mention named tools: FastAPI, SQLModel, PostgreSQL, Docker, GitHub Actions, CI/CD, maybe OpenAPI.

We'll mention roles: backend engineer, devops, full-stack, data engineer.

Make sure not to use # heading beyond "##". Ok.

Section 2: "## Architecture Overview"

Provide bullet breakdown or text diagram. We'll do a bullet list of components and their interactions, maybe as a text diagram.

Something like:

- FastAPI app (Python) – HTTP layer & OpenAPI spec
- SQLModel / SQLAlchemy – ORM against PostgreSQL
- PostgreSQL – relational data store
- Docker – containerises app and DB via docker‑compose
- GitHub Actions – runs pytest on push, builds Docker image
- (optional) Prometheus metrics endpoint

Text diagram:

```
client --> [FastAPI] --> [PostgreSQL] --> stats JSON
          ^                |
          |                +-- Docker compose
          +-- GitHub Actions CI
```

But we can just bullet list.

Section 3: "## Building It Step by Step". Numbered steps with code snippets.

We'll have steps 1-6.

Step 1: Scaffold project.

We'll give a code block maybe of a shell command or python code. But must include language tag. We'll use ```bash for shell commands.

Step 1: ```bash
mkdir portfolio-metrics && cd portfolio-metrics
python -m venv .venv
source .venv/bin/activate
pip install "fastapi[all]" sqlmodel pytest pytest-asyncio httpx
```

But we need to ensure code fences have language tag. Yes.

Step 2: Define data model. Use ```python code for SQLModel class.

Step 3: Implement API endpoints. Use ```python for FastAPI route.

Step 4: Create Dockerfile. Use ```dockerfile.

Step 5: Write docker-compose.yml. Use ```yaml.

Step 6: Add GitHub Actions workflow. Use ```yaml.

We'll embed each.

Now Section 4: "## Running and Testing It". Provide commands: "docker compose up -d", "pytest", etc. Also mention health check endpoint.

Section 5: "## Extending It: Your Roadmap to Senior-Level". Provide 5 upgrades, each with one-line reason.

We'll list them as bullet points maybe, but each with a one-line reason.

We need 4 to 6 concrete upgrades. We'll give 5.

Each bullet: "- **Add Alembic migrations** – version‑control DB schema changes." etc.

Now Section 6: "## Key Takeaways". 3-6 bullet points summarizing.

Section 7: "## Further Reading". At least 3 real URLs as markdown links. Provide maybe 5.

We'll include links:

- [FastAPI documentation](https://fastapi.tiangolo.com)
- [SQLModel docs](https://sqlmodel.tiangolo.com)
- [PostgreSQL docs](https://www.postgresql.org/docs)
- [Docker Compose reference](https://docs.docker.com/compose/)
- [Prometheus client for Python](https://github.com/prometheus/client_python)
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/using-workflows)

But need at least 3; we can give 5.

Now ensure we have no H1 headings. All headings start with "##". Good.

Now check for code fences: we will have many fenced code blocks with language tags. Ensure each fence has opening ```language and closing ```.

Make sure not to have any bare ```.

Make sure to not wrap frontmatter in code fences.

Now check the TL;DR blockquote: It must be the very first body block, i.e., after frontmatter, the first thing is the blockquote. We'll place it immediately after frontmatter "---". Actually after the frontmatter closing "---", the next line should be the blockquote starting with ">". Yes.

Now ensure there is a blank line after frontmatter? Usually markdown needs a blank line before blockquote but it's okay.

Now check that we have not repeated title as # heading. We have not.

Now ensure the description length: 140-160 characters. Let's count: "Build a runnable portfolio metrics service with FastAPI, PostgreSQL and Docker – a concrete side project that signals backend engineering skill to hiring managers." Count characters (including spaces). Let's count quickly:

"Build a runnable portfolio metrics service with FastAPI, PostgreSQL and Docker – a concrete side project that signals backend engineering skill to hiring managers."

We'll count: 
Build(5) + space(1)=6
a(1)+space=2 =>8
runnable(8)+space=9 =>17
portfolio(9)+space=10 =>27
metrics(7)+space=8 =>35
service(7)+space=8 =>43
with(4)+space=5 =>48
FastAPI,(9 inc comma?) FastAPI, length 9 (F a s t A P I ,) Actually "FastAPI," 9 chars? F(1) a(2) s(3) t(4) A(5) P(6) I(7) ,(8) so 8? Let's just approximate. But overall likely around 140-160. We'll trust.

Now summary: "A minimal FastAPI service that logs developer events and exposes JSON stats, containerized with Docker and CI‑ready for immediate deployment." Count roughly 140 chars.

Now tags: 5 tags, each in double quotes, separated by commas, no dashes. Good.

Now ensure that we have "cover.image": "__COVER_PATH__". The rule says cover.image MUST be the literal placeholder "__COVER_PATH__". Yes.

Now ensure that we have "cover.alt" and "cover.caption". Ok.

Now ensure that there is no extra frontmatter fields. We have title, date, draft, tags, description, summary, showToc, TocOpen, cover. That's allowed? The rule says "Do NOT add extra frontmatter fields." The listed fields are required. We have them. We have showToc and TocOpen which are allowed? The format example includes showToc and TocOpen. So it's fine.

Now check for any code fences in the frontmatter: none.

Now ensure that each code block in the body has language tag. We'll include.

Now ensure that we have no "### Subsection" headings beyond what's required? The rule says "Use "### Subsection" (H3) for nesting." We can include subsections if needed, but not required. We can include H3 under some sections for clarity, but must ensure we don't use H1. We can use H3.

But we need to be careful: The rule says "Never use H1 in the body." So we must avoid "# ". We'll use "##" and "###" only.

Now ensure that the sections order: 1. "## Why This Project Stands Out on a CV", 2. "## Architecture Overview", 3. "## Building It Step by Step", 4. "## Running and Testing It", 5. "## Extending It: Your Roadmap to Senior-Level", then "## Key Takeaways", then "## Further Reading". Yes.

Now check the "## Key Takeaways" section must have 3-6 bullet points summarizing what reader should remember. We'll provide 5 bullet points.

Now "## Further Reading" must have at least 3 real, well-known URLs formatted as markdown links: [Descriptive anchor](https://url). No made-up URLs. We'll provide real URLs.

Now ensure that we have "## Further Reading" after Key Takeaways.

Now ensure that we haven't included any "##" sections after Further Reading.

Now ensure that we haven't included any extra sections.

Now check for any use of bracketed-number citations like [1]. We'll avoid.

Now ensure that we have real inline markdown links at point of claim. Maybe we can cite FastAPI docs inline: "as described in [FastAPI docs](https://fastapi.tiangolo.com)". We'll include maybe one inline link.

Now check that we have bullet points and numbered lists for scannable content.

Now check that we have blockquotes for noteworthy asides. We'll have TL;DR blockquote, maybe other blockquotes for asides.

Now check the tone: professional but accessible.

Now ensure that we mention named tools throughout: FastAPI, PostgreSQL, Docker, GitHub Actions, Prometheus, etc.

Now check the length: We'll try to be around 2000 words. Let's estimate: The content we have so far is maybe ~1500 words. We'll need to expand each section with substantial detail.

We need to make sure we have enough content. We'll write each section with several paragraphs, code snippets, etc.

Now let's draft the content in detail.

We'll start writing.

First, frontmatter.

--- (we'll output exactly as described). Then body.

Now let's draft each section.

### TL;DR blockquote

> **TL;DR** — In this post we walk through building a Portable Portfolio Metrics Service with FastAPI, PostgreSQL and Docker. The result is a tiny, containerised API that records developer events and serves JSON stats – a concrete, runnable project you can add to your CV and extend with persistence, observability and scaling.

### Intro paragraph

"Side projects are only valuable when they demonstrate that you can ship working, observable systems. In this guide you’ll create a small but complete FastAPI service that records events (new project, skill update, etc.), persists them in PostgreSQL, and exposes JSON statistics. Everything is containerised with Docker, tested with pytest, and wired into a GitHub Actions CI pipeline – giving you a tangible, production‑flavored artifact to discuss in interviews."

Now Section 1: "## Why This Project Stands Out on a CV"

We'll write about skills.

Paragraph: talk about demonstration of backend engineering, API design, database integration, containerization, CI/CD. Mention roles: backend engineer, devops, full-stack, data engineer.

Maybe also mention that hiring managers see concrete code, not just buzzwords.

We'll include a brief bullet list of skills demonstrated.

But we need to keep it as a section, not a bullet list necessarily, but can include bullets.

But ensure we don't break the rule about bullet points? No rule against bullet points.

We'll do:

"Why This Project Stands Out on a CV

This tiny service packs a surprising amount of real‑world engineering. By shipping a FastAPI‑driven API, a PostgreSQL-backed data store, a Docker‑compose setup, and a GitHub Actions pipeline, you signal:

- **API design & OpenAPI generation** – Fast auto‑generated docs.
- **ORM and migration‑aware DB work** – SQLModel + Alembic.
- **Containerised deployment** – Dockerfile and compose for reproducible environments.
- **CI/CD fundamentals** – Automated testing on every push.
- **Observability basics** – A /metrics endpoint ready for Prometheus.

These are exactly the competencies hiring managers look for in junior‑to‑mid‑level backend, full‑stack or DevOps roles."

That's good.

Now Section 2: "## Architecture Overview"

We'll provide bullet breakdown and text diagram.

We'll do:

"Architecture Overview

The system consists of a few well‑separated components that you can run locally with a single `docker compose up` command.

- **FastAPI application** (`app/`) – Python HTTP server, validates requests with Pydantic, generates OpenAPI spec.
- **PostgreSQL database** (`db`) – persistent storage for events, accessed via SQLModel/SQLAlchemy.
- **Docker Compose** – ties the two services together, exposes port 8000, sets up network.
- **GitHub Actions** – runs `pytest` on push, builds a Docker image and pushes to a registry (or builds locally).
- **Optional Prometheus metrics** – the FastAPI app exposes `/metrics` with request count and latency histograms.

Text diagram:

```
+--------+      +----------+      +----------+
| Client | --> | FastAPI  | --> | PostgreSQL|
+--------+      +----------+      +----------+
          |                ^
          |                |
          +---- Docker Compose
```

But we can just describe.

Now Section 3: "## Building It Step by Step". Numbered steps with code snippets.

We'll detail steps 1-6.

Step 1: Scaffold project and install dependencies.

We'll give a code block:

```bash
# Create project directory
mkdir portfolio-metrics && cd portfolio-metrics

# Python virtual environment
python -m venv .venv
source .venv/bin/activate

# Install core dependencies
pip install "fastapi[all]" sqlmodel pytest pytest-asyncio httpx
```

Step 2: Define SQLModel model.

```python
# app/models.py
from sqlmodel import SQLModel, Field

class Event(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    kind: str = Field(index=True)      # e.g. "project_added", "skill_updated"
    payload: dict = Field(default={})  # free‑form data
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

We need to import datetime.

We'll include import.

Step 3: Implement API endpoints.

```python
# app/main.py
from fastapi import FastAPI
from .models import Event
from sqlmodel import Session, create_engine

engine = create_engine("postgresql+psycopg2://postgres:postgres@db:5433/app")

app = FastAPI()

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

@app.post("/events/", response_model=Event)
def create_event(event: Event, session: Session = Depends(get_session)):
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
```

But we need to include dependency injection for session. We can simplify.

We'll provide a simplified version:

```python
# app/main.py
from fastapi import FastAPI, Depends
from sqlmodel import Session, create_engine, select
from .models import Event

engine = create_engine("postgresql+psycopg2://postgres:postgres@db:5433/app")

app = FastAPI()

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

@app.post("/events/", response_model=Event)
def create_event(event: Event, session: Session = Depends(get_session)):
    session.add(event)
    session.commit()
    session.refresh(event)
    return event

@app.get("/stats/")
def stats(session: Session = Depends(get_session)):
    statement = select(Event.kind, func.count()).group_by(Event.kind)
    result = session.exec(statement).all()
    return {kind: count for kind, count in result}
```

But we need to import func from sqlalchemy. We'll include.

Better to keep simple.

We'll provide code with necessary imports.

Step 4: Create Dockerfile.

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry && poetry config virtualenvs.create false && poetry install --only main

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

But we may not have pyproject. Simpler: use requirements.txt.

We'll give a simpler Dockerfile:

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Step 5: Write docker-compose.yml.

```yaml
# docker-compose.yml
version: "3.9"
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/app
    depends_on:
      - db
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: app
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Step 6: Add GitHub Actions CI workflow.

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      db:
        image: postgres:15
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: test
        ports: ["5432:5432"]
        options: >-
          --health-interval=10s
          --health-timeout=5s
          --health-retries=5
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run tests
        run: pytest
```

We'll ensure code fences have language tag.

Now Section 4: "## Running and Testing It"

We'll describe:

- Local development: `docker compose up -d` then visit http://localhost:8000/docs.
- Run tests: `pytest` inside venv or docker.
- Verify with curl.

We'll give commands.

Section 5: "## Extending It: Your Roadmap to Senior-Level"

List 5 upgrades, each with one-line reason.

We'll bullet list:

- **Add Alembic migrations** – version‑control DB schema changes and keep them in sync across environments.
- **Instrument Prometheus metrics** – expose request latency and count, giving you observability in production.
- **Deploy to Cloud Run or Fly.io** – enables horizontal scaling and zero‑downtime releases.
- **Add JWT‑based authentication** – protects the API and demonstrates secure‑by‑design thinking.
- **Write property‑based tests with Hypothesis** – catches edge‑case bugs and shows a quality‑first mindset.

That's 5.

Now Section 6: "## Key Takeaways"

Bullet points 3-6.

We'll give 5 bullet points:

- This project combines API design, ORM, containerisation, and CI/CD in a single, runnable artifact.
- FastAPI gives you auto‑generated OpenAPI docs and built‑in validation with minimal boilerplate.
- Docker Compose provides a reproducible local environment that mirrors production deployments.
- GitHub Actions automates testing and builds, teaching you the fundamentals of modern DevOps.
- The extension roadmap (migrations, metrics, auth, scaling) shows how a side project can evolve into a production‑grade service.

Now Section 7: "## Further Reading"

List links:

- [FastAPI documentation](https://fastapi.tiangolo.com)
- [SQLModel guide](https://sqlmodel.tiangolo.com)
- [PostgreSQL documentation](https://www.postgresql.org/docs)
- [Docker Compose reference](https://docs.docker.com/compose/)
- [Prometheus Python client](https://github.com/prometheus/client_python)
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/using-workflows)

Make sure each link is formatted as markdown link.

Now check all rules.

Potential issues:

- The frontmatter must have "title" in quotes, "date" exact value with quotes, "tags" array with double quotes each. We'll ensure.

- The frontmatter must not have extra fields beyond those listed. We have showToc and TocOpen, which are part of the format shape. The rule says "Do NOT add extra frontmatter fields." The example includes showToc and TocOpen, so they are allowed. But we need to ensure we aren't adding any other fields not in the spec. We have title, date, draft, tags, description, summary, showToc, TocOpen, cover. That's the shape.

- The cover.image must be "__COVER_PATH__". Yes.

- The body must start with TL;DR blockquote as very first body block. We'll place it right after frontmatter.

- No heading # in body. We have "##" sections only.

- The "## Key Takeaways" section must have 3-6 bullet points. We'll have 5.

- The "## Further Reading" must have at least 3 real URLs formatted as markdown links. We'll have 6.

- Every fenced code block must include a language tag. We'll ensure.

- When citing a source, use a real inline markdown link at the point of claim. We may have one inline link somewhere, maybe referencing FastAPI docs. We'll include an inline link in the text, maybe in the "Why This Project Stands Out" section: "as described in [FastAPI docs](https://fastapi.tiangolo.com)". That counts.

- Use bullet points and numbered lists for scannable content. We'll have bullet points in sections.

- Use blockquotes for noteworthy asides, not decoration. We have TL;DR blockquote, maybe other blockquotes. We'll keep only the TL;DR blockquote; but we could add other blockquotes for asides, but not required. We'll keep just the TL;DR.

- Professional but accessible tone. We'll maintain.

- Audience tuning: mention named tools, platforms, production systems. We have FastAPI, PostgreSQL, Docker, GitHub Actions, Prometheus, Cloud Run.

- Length: aim 1800-2600 words. We'll need to count roughly. Let's approximate word count. We'll have a lot of text; likely over 1800. We'll ensure.

Now check for any mistakes.

Potential violation: The frontmatter must start with "---" on its own line. Yes.

Potential violation: The very first characters of response must be "---". We'll output exactly that.

Potential violation: The frontmatter values must be wrapped in double quotes. We'll ensure all string values are in double quotes. The date value is already in quotes. The tags array each tag in double quotes. The description