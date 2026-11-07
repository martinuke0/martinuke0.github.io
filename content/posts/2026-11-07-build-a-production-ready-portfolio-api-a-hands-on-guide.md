---
title: "Build a Production-Ready Portfolio API: A Hands-On Guide"
date: "2026-11-07T03:01:39.513"
draft: false
tags: ["portfolio", "fastapi", "docker", "ci-cd", "systems"]
description: "Create a scalable portfolio API with FastAPI, PostgreSQL, Docker, and CI/CD pipelines, proving real systems expertise to recruiters and hiring managers."
summary: "A step‑by‑step guide to building a production‑grade portfolio API with FastAPI, PostgreSQL, Docker, and CI/CD, demonstrating systems engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-07-build-a-production-ready-portfolio-api-a-hands-on-guide.svg"
  alt: "A modern dashboard displaying a portfolio API with code and database icons."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a production‑grade portfolio API using FastAPI, PostgreSQL, Docker, and GitHub Actions. You will end up with a runnable, tested, and deployable service that demonstrates systems engineering skills to hiring managers.

Building a side project that *looks* like a real system is the fastest way to signal competence to recruiters. A portfolio API that stores your projects, skills, and experience in a relational database, serves JSON over HTTP, ships in a container, and runs through automated tests and CI/CD pipelines checks every box for “systems thinking.” Below is a complete, runnable implementation, plus a roadmap to turn it into a senior‑level artifact.

## Why This Project Stands Out on a CV

- **End‑to‑end ownership** – You design the schema, write the API, containerize the service, and automate deployment. Hiring managers see a candidate who can ship a feature from idea to production.
- **Modern Python stack** – FastAPI, SQLAlchemy, and Pydantic demonstrate proficiency with async I/O, ORM mapping, and data validation—skills that map directly to backend roles.
- **Infrastructure as code** – Docker, Docker Compose, and GitHub Actions show you can define runtime environments and CI/CD pipelines declaratively, a core competency for SRE and platform engineering positions.
- **Observability basics** – Adding structured logging, health endpoints, and metrics (even in a side project) signals awareness of production concerns.
- **Scalability mindset** – The architecture is designed to be horizontally scaled (stateless API, external database) and can be extended with caching, load balancers, and message queues.

## Architecture Overview

```
┌─────────────┐      HTTP/JSON      ┌───────────────┐
│   Client    │ ◄──────────────────► │   FastAPI     │
│ (browser,   │                      │   App         │
│  curl)      │                      └───────┬───────┘
└─────────────┘                              │
                                             │  SQLAlchemy
                                             ▼
                                     ┌───────────────┐
                                     │  PostgreSQL   │
                                     │   Database    │
                                     └───────────────┘
```

- **FastAPI** – Async Python web framework; generates OpenAPI docs automatically.
- **SQLAlchemy** – ORM that abstracts PostgreSQL interactions; we use it with `asyncpg` for async support.
- **Pydantic** – Data validation and serialization models.
- **PostgreSQL** – Relational store for portfolio entries, skills, and experience.
- **Docker & Docker Compose** – Containerized runtime; `docker-compose.yml` defines the API service and the database.
- **GitHub Actions** – CI pipeline that runs lint, tests, and builds the Docker image on every push.

## Building It Step by Step

### 1. Project Skeleton

Create a directory `portfolio-api` and add the following files:

```
portfolio-api/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   └── database.py
├── tests/
│   └── test_api.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .github/
│   └── workflows/
│       └── ci.yml
└── README.md
```

### 2. Dependencies (`requirements.txt`)

```txt
fastapi==0.110.0
uvicorn[standard]==0.29.0
sqlalchemy==2.0.29
asyncpg==0.29.0
pydantic==2.6.4
python-dotenv==1.0.1
pytest==8.1.1
httpx==0.27.0
```

### 3. Database Configuration (`app/database.py`)

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db:5432/portfolio")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

### 4. Data Models (`app/models.py`)

```python
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    tech_stack = Column(String(255), nullable=False)
    link = Column(String(255))

class Skill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    level = Column(String(50))  # e.g., "Expert", "Proficient"
```

### 5. Pydantic Schemas (`app/schemas.py`)

```python
from pydantic import BaseModel
from typing import Optional

class ProjectCreate(BaseModel):
    title: str
    description: str
    tech_stack: str
    link: Optional[str] = None

class ProjectOut(ProjectCreate):
    id: int

class SkillCreate(BaseModel):
    name: str
    level: str

class SkillOut(SkillCreate):
    id: int
```

### 6. FastAPI Application (`app/main.py`)

```python
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from . import models, schemas
from .models import Project, Skill

app = FastAPI(title="Portfolio API")

# ---------- Projects ----------
@app.post("/projects/", response_model=schemas.ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(project: schemas.ProjectCreate, db: AsyncSession = Depends(get_db)):
    db_project = Project(**project.dict())
    db.add(db_project)
    await db.commit()
    await db.refresh(db_project)
    return db_project

@app.get("/projects/", response_model=list[schemas.ProjectOut])
async def read_projects(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(models.Project.select().offset(skip).limit(limit))
    return result.scalars().all()

@app.get("/projects/{project_id}", response_model=schemas.ProjectOut)
async def read_project(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(models.Project.select().where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

# ---------- Skills ----------
@app.post("/skills/", response_model=schemas.SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(skill: schemas.SkillCreate, db: AsyncSession = Depends(get_db)):
    db_skill = Skill(**skill.dict())
    db.add(db_skill)
    await db.commit()
    await db.refresh(db_skill)
    return db_skill

@app.get("/skills/", response_model=list[schemas.SkillOut])
async def read_skills(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(models.Skill.select().offset(skip).limit(limit))
    return result.scalars().all()
```

### 7. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8. Docker Compose (`docker-compose.yml`)

```yaml
version: "3.8"

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/portfolio
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: portfolio
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  pgdata:
```

### 9. GitHub Actions CI (`.github/workflows/ci.yml`)

```yaml
name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build-test:
    runs-on: ubuntu-latest
    services:
      db:
        image: postgres:15
        env:
          POSTGRES_DB: portfolio
          POSTGRES_USER: user
          POSTGRES_PASSWORD: pass
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run tests
        env:
          DATABASE_URL: "postgresql+asyncpg://user:pass@localhost:5432/portfolio"
        run: |
          pytest -v

      - name: Build Docker image
        run: |
          docker build -t portfolio-api:latest .
```

### 10. Tests (`tests/test_api.py`)

```python
import pytest
from httpx import AsyncClient
from app.main import app
from app.database import engine, Base
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture(scope="module")
def event_loop():
    import asyncio
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.drop_all)
        await conn.run_sync(Base.create_all)
    yield

@pytest.mark.asyncio
async def test_create_project():
    async with AsyncClient(app=app, base_url="http://test") as client:
        payload = {
            "title": "Portfolio Site",
            "description": "A personal portfolio built with FastAPI.",
            "tech_stack": "FastAPI, PostgreSQL, Docker",
            "link": "https://example.com"
        }
        response = await client.post("/projects/", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == payload["title"]
        assert "id" in data
```

## Running and Testing It

1. **Start services**  
   ```bash
   docker compose up -d
   ```
   This builds the API image and launches PostgreSQL. The API will be available at `http://localhost:8000`.

2. **Explore the OpenAPI docs**  
   Open `http://localhost:8000/docs` in a browser. FastAPI auto‑generates a Swagger UI where you can try the endpoints.

3. **Create a sample project**  
   ```bash
   curl -X POST "http://localhost:8000/projects/" \
        -H "Content-Type: application/json" \
        -d '{"title":"My API","description":"Demo","tech_stack":"FastAPI"}'
   ```

4. **Run the test suite**  
   ```bash
   pytest -v
   ```
   The CI workflow defined above will execute the same tests in a clean environment, ensuring they pass.

5. **Verify health**  
   Add a simple `/health` endpoint (not shown) returning `{"status":"ok"}`. It can be used by Docker’s `healthcheck` or a load balancer.

## Extending It: Your Roadmap to Senior-Level

1. **Persistent sessions & authentication** – Introduce JWT tokens (e.g., using `OAuth2PasswordBearer`) to protect endpoints. *Why it matters:* Real APIs require identity verification and authorization, a prerequisite for any production service.

2. **Horizontal scaling** – Deploy the API behind a load balancer (e.g., Traefik or AWS ALB) with multiple replicas. The stateless design (no in‑memory caches) makes scaling out straightforward. *Why it matters:* Demonstrates ability to handle traffic growth without re‑architecting.

3. **Observability** – Export Prometheus metrics (request latency, error rates) via `prometheus_client` and ship logs to a central store (e.g., Loki). *Why it matters:* Production systems need visibility to debug and capacity‑plan.

4. **Fault tolerance with retries & circuit breakers** – Use `httpx` with exponential backoff for outbound calls and integrate `opentelemetry` for distributed tracing. *Why it matters:* Shows resilience patterns that prevent cascading failures.

5. **Benchmarking & performance tuning** – Run `locust` against the API, measure throughput, then tune SQLAlchemy connection pool size and PostgreSQL indexes. *Why it matters:* Quantitative performance analysis is a hallmark of senior engineers.

6. **Feature flagging & A/B testing** – Add a simple flag store (e.g., `Unleash` or a database table) to toggle endpoints. *Why it matters:* Enables safe, incremental rollouts and experimentation in production.

## Key Takeaways

- **Ship end‑to‑end** – From schema definition to Docker container to CI pipeline, you own the full lifecycle.
- **Leverage proven tools** – FastAPI, SQLAlchemy, PostgreSQL, Docker, and GitHub Actions are industry‑standard and easy to extend.
- **Showcase scalability & reliability** – Stateless design, health checks, and observability hooks signal production readiness.
- **Iterate toward seniority** – Adding auth, scaling, tracing, and benchmarking transforms a demo into a platform‑grade service.

## Further Reading

- [FastAPI Official Documentation](https://fastapi.tiangolo.com) – Deep dive into dependency injection, async endpoints, and OpenAPI generation.
- [SQLAlchemy Async Mode Guide](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) – Patterns for async session management.
- [PostgreSQL Performance Tuning](https://www.postgresql.org/docs/current/performance-tips.html) – Indexing and query optimization techniques.
- [Docker Compose Reference](https://docs.docker.com/compose/) – Defining multi‑container applications.
- [GitHub Actions Guide](https://docs.github.com/en/actions) – Building CI/CD pipelines with reusable workflows.
- *Designing Data‑Intensive Applications* by Martin Kleppmann – Foundational concepts for reliable, scalable systems.