

---
title: "Building a Production-Ready Personal CV API with Next.js and Prisma"
date: "2026-09-19T00:00:59.276"
draft: false
tags: ["portfolio", "cv", "nextjs", "prisma", "docker"]
description: "Learn to build a personal CV API with Next.js and Prisma, demonstrating real systems skills and production patterns for hiring managers."
summary: "A practical guide to building a personal CV API with Next.js and Prisma, showcasing systems engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-19-building-a-production-ready-personal-cv-api-with-nextjs-and-prisma.svg"
  alt: "A developer working on a laptop"
  caption: ""
  relative: false
---

> **TL;DR** — This guide shows you how to build a personal CV API using Next.js and Prisma, giving you a runnable project that highlights systems engineering skills. You'll end up with a Dockerized service that serves structured resume data and can be extended with production features.

Building a portfolio project that *actually* signals real systems skill is hard. Many candidates throw together a static site with a few libraries, but hiring managers can smell boilerplate from a mile away. The project described below is a **CV API** — a small, containerized web service that stores your resume in a relational database, exposes it through a clean REST interface, and is ready to be deployed on any cloud. It demonstrates full‑stack development, API design, database modeling, containerization, and a taste of production concerns like versioning and testability.

## Why This Project Stands Out on a CV

- **End‑to‑end ownership** – You write the schema, the API layer, the client (even a minimal one), and the deployment artifacts. That shows you can ship a feature from idea to production.
- **Explicit API design** – By exposing `/api/v1/resume` with JSON, you demonstrate an understanding of resource modeling, HTTP semantics, and versioning—skills that map directly to backend or full‑stack roles.
- **Relational data modeling** – Using Prisma with SQLite (and later PostgreSQL) teaches you to think in terms of entities, relationships, and migrations, which is core to any systems‑oriented position.
- **Containerization & reproducibility** – A Dockerfile and `docker‑compose.yml` prove you can package an application so it runs identically anywhere, a prerequisite for modern DevOps environments.
- **Testing & observability hooks** – Even a simple `curl` test or a basic Prometheus endpoint shows you care about verification and monitoring, traits that senior engineers look for.
- **Extensibility path** – The architecture is deliberately modular, so you can later add authentication, caching, or horizontal scaling without rewriting the whole codebase.

In short, this project checks the boxes for *backend*, *full‑stack*, and *DevOps* narratives, giving you a concrete artifact to discuss in interviews.

## Architecture Overview

The system is composed of four logical layers:

1. **Client (optional)** – A minimal Next.js page that consumes the API (or any HTTP client). For a CV, this could be a simple HTML view, but the API is the star.
2. **API Gateway** – Next.js API routes (`pages/api/...`) act as the entry point, handling HTTP requests and returning JSON.
3. **Persistence** – Prisma ORM talks to a SQLite database during development; swapping to PostgreSQL is a one‑line change in the connection string.
4. **Container** – Docker wraps the whole stack, ensuring consistent runtime across laptops, CI pipelines, and cloud containers.

A textual diagram:

```
+-------------------+      HTTP/JSON      +-------------------+
|   Client (curl)   | <-----------------> |   Next.js API     |
+-------------------+                     +-------------------+
                                            |
                                            v
                                     +-------------------+
                                     |   Prisma ORM      |
                                     +-------------------+
                                            |
                                            v
                                     +-------------------+
                                     |   SQLite / PG     |
                                     +-------------------+
```

All components are version‑controlled in a single Git repository, and a `docker‑compose.yml` orchestrates the service (and optionally a Redis cache or a PostgreSQL container).

## Building It Step by Step

Below is a numbered, end‑to‑end implementation. Each step includes the exact commands or code you need to copy‑paste.

### 1. Scaffold the project

```bash
mkdir cv-api && cd cv-api
npm init -y
npm install next@latest react@latest react-dom@latest
npm install --save-dev typescript @types/react @types/node
npm install prisma @prisma/client
```

Create `tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "es2020",
    "module": "commonjs",
    "lib": ["es2020"],
    "outDir": "./dist",
    "rootDir": "./",
    "strict": true,
    "esModuleInterop": true
  },
  "include": ["pages/**/*", "prisma/**/*"]
}
```

### 2. Initialize Prisma

```bash
npx prisma init
```

Edit `prisma/schema.prisma`:

```prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "sqlite"
  url      = "file:./dev.db"
}

model Resume {
  id        Int      @id @default(autoincrement())
  name      String
  title     String
  summary   String
  experience Experience[]
  education Education[]
  skills    Skill[]
}

model Experience {
  id          Int      @id @default(autoincrement())
  company     String
  role        String
  startDate   DateTime
  endDate     DateTime?
  description String
  resume      Resume    @relation(fields: [resumeId], references: [id])
  resumeId    Int
}

model Education {
  id          Int      @id @default(autoincrement())
  institution String
  degree      String
  field       String
  startDate   DateTime
  endDate     DateTime?
  resume      Resume    @relation(fields: [resumeId], references: [id])
  resumeId    Int
}

model Skill {
  id      Int      @id @default(autoincrement())
  name    String
  level   String
  resume  Resume    @relation(fields: [resumeId], references: [id])
  resumeId Int
}
```

Generate the client:

```bash
npx prisma generate
```

### 3. Seed the database (optional but helpful)

Create `prisma/seed.ts`:

```ts
import { PrismaClient } from '@prisma/client';
const prisma = new PrismaClient();

async function main() {
  const resume = await prisma.resume.create({
    data: {
      name: 'Jane Doe',
      title: 'Senior Software Engineer',
      summary: '10+ years building scalable backend services.',
      experience: {
        create: [
          {
            company: 'TechCorp',
            role: 'Backend Lead',
            startDate: new Date('2018-01-01'),
            description: 'Led a team of 8 engineers on a microservices platform.',
          },
        ],
      },
      education: {
        create: [
          {
            institution: 'University of Example',
            degree: 'B.Sc.',
            field: 'Computer Science',
            startDate: new Date('2008-09-01'),
            endDate: new Date('2012-06-01'),
          },
        ],
      },
      skills: {
        create: [
          { name: 'Go', level: 'expert' },
          { name: 'Kubernetes', level: 'advanced' },
          { name: 'PostgreSQL', level: 'expert' },
        ],
      },
    },
  });
  console.log('Seeded resume id:', resume.id);
}

main()
  .catch(e => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
```

Run it:

```bash
npx prisma migrate dev --seed
```

### 4. Create the API route

Make the folder `pages/api/v1` and add `resume.ts`:

```ts
import { PrismaClient } from '@prisma/client';
import { NextApiRequest, NextApiResponse } from 'next';

const prisma = new PrismaClient();

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const resume = await prisma.resume.findFirst({
      include: {
        experience: true,
        education: true,
        skills: true,
      },
    });

    if (!resume) {
      return res.status(404).json({ error: 'Resume not found' });
    }

    // Shape the response to a flat, versioned payload
    const payload = {
      version: '1.0',
      data: {
        name: resume.name,
        title: resume.title,
        summary: resume.summary,
        experience: resume.experience.map(e => ({
          company: e.company,
          role: e.role,
          startDate: e.startDate.toISOString(),
          endDate: e.endDate ? e.endDate.toISOString() : null,
          description: e.description,
        })),
        education: resume.education.map(ed => ({
          institution: ed.institution,
          degree: ed.degree,
          field: ed.field,
          startDate: ed.startDate.toISOString(),
          endDate: ed.endDate ? ed.endDate.toISOString() : null,
        })),
        skills: resume.skills.map(s => ({ name: s.name, level: s.level })),
      },
    };

    res.status(200).json(payload);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Internal server error' });
  }
}
```

### 5. Add Docker support

Create a `Dockerfile`:

```dockerfile
FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

EXPOSE 3000

CMD ["npm", "run", "start"]
```

And a `docker-compose.yml`:

```yaml
version: "3.8"
services:
  cv-api:
    build: .
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL="file:./dev.db"
    volumes:
      - .:/app
      - /app/node_modules
```

### 6. Add a simple health‑check endpoint

In `pages/api/health.ts`:

```ts
import { NextApiRequest, NextApiResponse } from 'next';

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  res.status(200).json({ status: 'ok' });
}
```

## Running and Testing It

1. **Start the service** (from the project root):

```bash
docker compose up --build
```

2. **Verify the API**:

```bash
curl http://localhost:3000/api/v1/resume | jq .
```

You should receive a JSON object with the seeded resume data.

3. **Check the health endpoint**:

```bash
curl http://localhost:3000/api/health
```

4. **Run a quick integration test** (using `pytest` or `jest` if you prefer). A minimal Node test with `mocha`:

```js
// test/resume.test.js
const fetch = require('node-fetch');
const assert = require('assert');

describe('CV API', () => {
  it('returns a versioned resume payload', async () => {
    const res = await fetch('http://localhost:3000/api/v1/resume');
    const body = await res.json();
    assert.strictEqual(body.version, '1.0');
    assert.ok(body.data.name);
  });
});
```

Run with `npm test`.

## Extending It: Your Roadmap to Senior-Level

The base project is functional, but you can evolve it into a production‑grade service with these upgrades:

1. **Switch to PostgreSQL** – Replace the SQLite datasource in `schema.prisma` and set `DATABASE_URL` to a managed Postgres instance. This teaches you to handle production‑grade durability, connection pooling, and migrations at scale.
2. **Add authentication (JWT)** – Protect the API with a simple token‑based guard. Libraries like `jsonwebtoken` or NextAuth.js let you demonstrate stateless auth, a common requirement in microservice architectures.
3. **Introduce a caching layer** – Deploy Redis (via Docker) and cache the resume payload for 5 minutes. This shows you understand read‑heavy workloads and the trade‑offs of cache‑aside patterns.
4. **Instrument with Prometheus** – Export metrics (request latency, error rate) using `prom-client`. Pair with Grafana dashboards to prove you care about observability and SLA tracking.
5. **Container orchestration** – Write a Kubernetes manifest (`deployment.yaml`, `service.yaml`) and deploy to a cluster. This signals readiness for cloud‑native environments and horizontal scaling.
6. **Load‑testing & benchmarking** – Use `k6` or `wrk` to simulate traffic, then analyze throughput and latency. Presenting a benchmark report demonstrates performance awareness and the ability to iterate on bottlenecks.

Each of these steps adds a concrete, interview‑ready talking point about how you handle real‑world reliability, scalability, and maintainability.

## Key Takeaways

- **Build a runnable artifact** – A Dockerized Next.js + Prisma service that serves a versioned CV.
- **Showcase end‑to‑end ownership** – From schema design to API routing to container packaging.
- **Demonstrate production concerns** – Versioning, error handling, health checks, and a clear path to scaling.
- **Provide extensibility** – The modular architecture invites additions like auth, caching, and observability.
- **Create a conversation piece** – You can discuss trade‑offs (SQLite vs. Postgres, monolith vs. microservice) with concrete code.

## Further Reading

- [Next.js API Routes Documentation](https://nextjs.org/docs/api-routes/introduction) – the canonical guide to building serverless functions with Next.js.
- [Prisma Guide](https://www.prisma.io/docs) – deep dive into schema design, migrations, and client usage.
- [Docker Reference](https://docs.docker.com) – official docs for containerization and orchestration basics.
- [HTTP Semantics (RFC 7231)](https://tools.ietf.org/html/rfc7231) – the foundation for understanding RESTful design and status codes.
- [Prometheus Client Documentation](https://github.com/simonverjs/prom-client) – how to expose metrics for observability.
- [Kubernetes Basics](https://kubernetes.io/docs/tutorials/kubernetes-basics/) – a practical introduction to deploying containers in a cluster.