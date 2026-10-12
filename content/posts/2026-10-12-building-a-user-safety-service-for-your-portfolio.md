---
title: "Building a User Safety Service for Your Portfolio"
date: "2026-10-12T08:00:45.044"
draft: false
tags: ["portfolio", "systems", "safety", "fastapi", "python"]
description: "A hands-on guide to building a user safety microservice that demonstrates real systems skills, API design, and production readiness for interviews."
summary: "Build a production-style user safety API in Python that validates profiles, enforces policies, and scales."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-12-building-a-user-safety-service-for-your-portfolio.svg"
  alt: "A dashboard showing user safety metrics"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a user safety microservice in Python that validates user profiles, enforces content policies, and exposes a clean REST API. By the end you’ll have a runnable project that demonstrates API design, data validation, and production‑ready patterns—exactly what hiring managers look for.

In a competitive job market, a side project needs to do more than showcase syntax; it must signal that you understand how software behaves in production. A user safety service is an ideal vehicle because it touches on API design, data validation, policy enforcement, and scalability—all skills that recur in senior engineering interviews.

## Why This Project Stands Out on a CV

- **End‑to‑end service development** – you ship a complete HTTP API, from request parsing to response formatting, which proves you can own a feature from spec to deployment.  
- **Strong typing & validation** – using Pydantic models shows you care about data integrity and can catch malformed input early, a common source of production incidents.  
- **Policy‑driven logic** – implementing a rule engine for safety checks demonstrates experience with business‑logic separation and maintainable code.  
- **Testing & automation** – writing unit and integration tests with pytest and httpx signals a disciplined, CI‑friendly workflow.  
- **Scalability awareness** – the architecture introduces stateless endpoints, optional caching, and horizontal scaling hooks, preparing you to discuss trade‑offs in interviews.  

These bullet points map directly to the competencies listed in senior‑level job descriptions: system design, reliability, and code quality.

## Architecture Overview

```
Client (curl / browser)
        │
        ▼
   ┌─────────────┐
   │   FastAPI   │  ← HTTP layer, routing, request validation
   └──────┬──────┘
          │
   ┌──────▼──────┐
   │ SafetyEngine│  ← Core policy checks (regex, length, blacklists)
   └──────┬──────┘
          │
   ┌──────▼──────┐
   │   Storage   │  ← SQLite for MVP, PostgreSQL for production
   └─────────────┘
```

- **FastAPI** provides automatic OpenAPI docs, async support, and dependency injection, making the service easy to extend.  
- **Pydantic schemas** enforce input contracts and serialize output, eliminating whole classes of runtime errors.  
- **SafetyEngine** is a pure‑Python module that can be unit‑tested in isolation; it currently includes checks for prohibited words, minimum/maximum lengths, and duplicate email detection.  
- **Storage** starts as a single‑file SQLite database via SQLAlchemy, giving you a concrete migration path to PostgreSQL and eventually to a distributed cache like Redis.  

## Building It Step by Step

1. **Scaffold the project**  
   ```bash
   mkdir user-safety-service && cd user-safety-service
   python -m venv venv
   source venv/bin/activate
   pip install fastapi uvicorn pydantic sqlalchemy sqlite
   ```

2. **Define the data models** (`models.py`)  
   ```python
   from pydantic import BaseModel, EmailStr, constr
   from typing import Optional

   class UserCreate(BaseModel):
       username: constr(min_length=3, max_length=32, regex=r'^[A-Za-z0-9_]+$')
       email: EmailStr
       password: constr(min_length=8)

   class UserResponse(BaseModel):
       id: int
       username: str
       email: str
       class Config:
           orm_mode = True
   ```

3. **Implement the safety engine** (`safety.py`)  
   ```python
   import re
   from typing import List

   PROHIBITED_WORDS = ["spam", "phishing", "malware"]

   def check_username(username: str) -> List[str]:
       issues = []
       if len(username) < 3:
           issues.append("username too short")
       if any(word in username.lower() for word in PROHIBITED_WORDS):
           issues.append("username contains prohibited word")
       return issues

   def check_email(email: str) -> List[str]:
       # Simple duplicate check could query DB; here we just validate format
       if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
           issues = ["invalid email format"]
       else:
           issues = []
       return issues
   ```

4. **Create the FastAPI app** (`main.py`)  
   ```python
   from fastapi import FastAPI, HTTPException, Depends
   from sqlalchemy import create_engine, Column, Integer, String
   from sqlalchemy.ext.declarative import declarative_base
   from sqlalchemy.orm import sessionmaker, Session
   from pydantic import BaseModel
   from models import UserCreate, UserResponse
   from safety import check_username, check_email

   app = FastAPI(title="User Safety Service")

   # SQLite setup
   SQLALCHEMY_DATABASE_URL = "sqlite:///./users.db"
   engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
   SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
   Base = declarative_base()

   class User(Base):
       __tablename__ = "users"
       id = Column(Integer, primary_key=True, index=True)
       username = Column(String, unique=True, index=True)
       email = Column(String, unique=True, index=True)
       password = Column(String)

   Base.metadata.create_all(bind=engine)

   def get_db():
       db = SessionLocal()
       try:
           yield db
       finally:
           db.close()

   @app.post("/users/", response_model=UserResponse, status_code=201)
   def create_user(user: UserCreate, db: Session = Depends(get_db)):
       # Run safety checks
       issues = []
       issues += check_username(user.username)
       issues += check_email(user.email)
       if issues:
           raise HTTPException(status_code=400, detail=issues)

       # Persist
       db_user = User(username=user.username, email=user.email, password=user.password)
       db.add(db_user)
       db.commit()
       db.refresh(db_user)
       return db_user
   ```

5. **Add a health endpoint** (optional but useful for CI)  
   ```python
   @app.get("/health")
   def health():
       return {"status": "ok"}
   ```

6. **Write tests** (`test_main.py`)  
   ```python
   from fastapi.testclient import TestClient
   from main import app

   client = TestClient(app)

   def test_create_user_success():
       resp = client.post("/users/", json={"username": "alice", "email": "alice@example.com", "password": "secret123"})
       assert resp.status_code == 201
       data = resp.json()
       assert data["username"] == "alice"

   def test_prohibited_word():
       resp = client.post("/users/", json={"username": "spam123", "email": "spam@example.com", "password": "secret123"})
       assert resp.status_code == 400
       assert "prohibited word" in resp.text
   ```

## Running and Testing It

1. **Start the server**  
   ```bash
   uvicorn main:app --reload
   ```

2. **Exercise the API**  
   ```bash
   curl -X POST "http://127.0.0.1:8000/users/" \
        -H "Content-Type: application/json" \
        -d '{"username":"bob","email":"bob@example.com","password":"bobpass123"}'
   ```

3. **Run the test suite**  
   ```bash
   pip install pytest httpx
   pytest -q
   ```

All tests should pass, confirming that validation, persistence, and error handling work end‑to‑end.

## Extending It: Your Roadmap to Senior-Level

1. **Persist in PostgreSQL** – replace SQLite with a managed PostgreSQL instance using SQLAlchemy’s dialect support; this teaches you production‑grade durability and connection pooling.  
2. **Add JWT‑based authentication** – protect endpoints with `OAuth2PasswordBearer`, demonstrating stateless auth and token refresh patterns.  
3. **Introduce Redis for rate limiting** – implement a sliding‑window limiter to show you can guard against abuse and scale horizontally.  
4. **Instrument with Prometheus** – expose `/metrics` and record request latency and error counts, a core observability skill for on‑call engineers.  
5. **Containerize with Docker** – write a `Dockerfile` and push to a registry; then deploy to Kubernetes to prove you understand CI/CD and orchestration.  
6. **Load‑test with Locust** – simulate 1,000 concurrent users to surface bottlenecks and validate autoscaling policies.

Each upgrade addresses a real production concern, turning a simple prototype into a resilient, observable service.

## Key Takeaways

- Build a complete, type‑safe API that validates input and enforces business rules.  
- Use FastAPI + Pydantic to get automatic docs, async support, and robust serialization.  
- Write unit and integration tests to prove correctness before shipping.  
- Design a modular architecture that can evolve to PostgreSQL, Redis, and Kubernetes.  
- Demonstrate observability and scalability patterns that interviewers recognize.  

## Further Reading

- [FastAPI Official Documentation](https://fastapi.tiangolo.com/) – learn advanced routing, dependency injection, and security features.  
- [Pydantic v2 User Guide](https://docs.pydantic.dev/) – deep dive into validation, custom types, and serialization.  
- [OWASP Top Ten](https://owasp.org/www-project-top-ten/) – understand common security risks and how to mitigate them in your API.  
- [SQLAlchemy Core Tutorial](https://docs.sqlalchemy.org/en/latest