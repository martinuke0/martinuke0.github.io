---
title: "A2A from Zero to Production: A Very Detailed End‑to‑End Guide"
date: "2025-12-26T22:28:55.624"
draft: false
tags: ["architecture", "devops", "api", "security", "nodejs"]
---

## Table of Contents

- [Introduction](#introduction)
- [1. Understanding A2A and Defining the Problem](#1-understanding-a2a-and-defining-the-problem)
  - [1.1 What is A2A?](#11-what-is-a2a)
  - [1.2 Typical A2A Requirements](#12-typical-a2a-requirements)
  - [1.3 Example Scenario We’ll Use](#13-example-scenario-well-use)
- [2. High-Level Architecture](#2-high-level-architecture)
  - [2.1 Core Components](#21-core-components)
  - [2.2 Synchronous vs Asynchronous](#22-synchronous-vs-asynchronous)
  - [2.3 Choosing Protocols and Formats](#23-choosing-protocols-and-formats)
- [3. Local Development Setup](#3-local-development-setup)
  - [3.1 Tech Stack Choices](#31-tech-stack-choices)
  - [3.2 Project Skeleton (Node.js Example)](#32-project-skeleton-nodejs-example)
- [4. Designing the A2A API Contract](#4-designing-the-a2a-api-contract)
  - [4.1 Resource Modeling](#41-resource-modeling)
  - [4.2 Versioning Strategy](#42-versioning-strategy)
  - [4.3 Idempotency and Request Correlation](#43-idempotency-and-request-correlation)
  - [4.4 Error Handling Conventions](#44-error-handling-conventions)
- [5. Implementing AuthN & AuthZ for A2A](#5-implementing-authn--authz-for-a2a)
  - [5.1 OAuth 2.0 Client Credentials](#51-oauth-20-client-credentials)
  - [5.2 mTLS (Mutual TLS)](#52-mtls-mutual-tls)
  - [5.3 Role- and Scope-Based Authorization](#53-role--and-scope-based-authorization)
- [6. Robustness: Validation, Resilience, and Retries](#6-robustness-validation-resilience-and-retries)
  - [6.1 Input Validation](#61-input-validation)
  - [6.2 Timeouts, Retries, and Circuit Breakers](#62-timeouts-retries-and-circuit-breakers)
- [7. Observability: Logging, Metrics, and Tracing](#7-observability-logging-metrics-and-tracing)
  - [7.1 Structured Logging](#71-structured-logging)
  - [7.2 Metrics](#72-metrics)
  - [7.3 Distributed Tracing](#73-distributed-tracing)
- [8. Testing Strategy from Day One](#8-testing-strategy-from-day-one)
  - [8.1 Unit Tests](#81-unit-tests)
  - [8.2 Integration and Contract Tests](#82-integration-and-contract-tests)
  - [8.3 Performance and Load Testing](#83-performance-and-load-testing)
- [9. From Dev to Production: CI/CD](#9-from-dev-to-production-cicd)
  - [9.1 Containerization with Docker](#91-containerization-with-docker)
  - [9.2 CI Example with GitHub Actions](#92-ci-example-with-github-actions)
  - [9.3 Deployment Strategies](#93-deployment-strategies)
- [10. Production-Grade Infrastructure](#10-production-grade-infrastructure)
  - [10.1 Kubernetes Example](#101-kubernetes-example)
  - [10.2 Configuration and Secrets Management](#102-configuration-and-secrets-management)
- [11. Security and Compliance Hardening](#11-security-and-compliance-hardening)
- [12. Operating A2A in Production](#12-operating-a2a-in-production)
- [Conclusion](#conclusion)
- [Further Resources](#further-resources)

---

## Introduction

Application-to-application (A2A) communication is the backbone of modern software systems. Whether you’re integrating internal microservices, connecting with third‑party providers, or exposing core capabilities to trusted partners, A2A APIs are often:

- high‑throughput
- security‑sensitive
- business‑critical

This guide walks through a **zero‑to‑production journey** for an A2A service:

- designing an API contract
- implementing a secure backend
- adding observability
- building a CI/CD pipeline
- deploying and operating it in production

Examples are given in **Node.js + Express**, but the principles apply to any stack.

---

## 1. Understanding A2A and Defining the Problem

### 1.1 What is A2A?

In this article, **A2A (application-to-application)** means:

> Two or more software systems communicating directly with each other **without a human user in the loop**.

Common types:

- **Internal microservices** inside the same organization
- **B2B integrations** (e.g., your payment processor talking to a bank)
- **Machine-to-machine** APIs (often OAuth 2.0 “client credentials” flows)

### 1.2 Typical A2A Requirements

A2A services usually have stricter non‑functional requirements than user‑facing APIs:

- **Security**
  - Strong authentication (OAuth 2.0, mTLS, signed tokens)
  - Fine‑grained authorization (scopes, roles)
  - Network controls (VPC, IP allow lists)
- **Reliability**
  - Idempotent endpoints
  - Retries with backoff
  - Circuit breakers and timeouts
- **Observability**
  - Structured logs
  - Metrics (latency, errors, throughput)
  - Traces across multiple services
- **Change control**
  - Backwards‑compatible changes
  - Versioning strategy
  - Contract testing

### 1.3 Example Scenario We’ll Use

We’ll design an **“Order Processing A2A Service”** that:

- Accepts order creation requests from an **Order Orchestrator** service
- Persists orders in a database
- Publishes order events to a message bus (e.g., Kafka or RabbitMQ)
- Is protected using **OAuth 2.0 Client Credentials** + optional **mTLS**

---

## 2. High-Level Architecture

### 2.1 Core Components

A minimal production A2A architecture might look like this:

- **Order API Service**
  - Exposes REST endpoints for creating and querying orders
  - Implements authentication/authorization
  - Writes to DB and publishes to message bus

- **Database**
  - Stores order state (PostgreSQL, MySQL, etc.)

- **Message Bus**
  - Emits events like `order.created` to downstream consumers

- **Identity Provider (IdP)**
  - Issues OAuth 2.0 tokens to trusted machine clients
  - Validates client credentials and enforces scopes

- **API Gateway / Ingress**
  - Terminates TLS
  - Enforces rate limiting
  - Routes traffic to the Order API

### 2.2 Synchronous vs Asynchronous

- **Synchronous (REST/gRPC)**
  - Good for “request‑reply” interactions
  - Easy to reason about from client perspective
- **Asynchronous (queue/stream)**
  - Better for high throughput, eventual consistency
  - Decouples producers and consumers

In our example:

- The **Order Orchestrator** calls `POST /v1/orders` (synchronous)
- The **Order API** publishes an `order.created` event (asynchronous)

### 2.3 Choosing Protocols and Formats

Common choices:

- **REST + JSON**
  - Simple, widely understood
  - Good for most business APIs
- **gRPC + Protobuf**
  - High performance, strong typing
  - Great for internal services at scale

We’ll use **REST + JSON** for clarity.

---

## 3. Local Development Setup

### 3.1 Tech Stack Choices

For a new greenfield A2A service, a modern stack might include:

- **Runtime:** Node.js (LTS)
- **Framework:** Express or Fastify
- **Database:** PostgreSQL
- **Message bus:** Kafka (or RabbitMQ)
- **Auth:** OAuth 2.0 via a managed IdP (Auth0, Okta, Keycloak, etc.)
- **Containerization:** Docker
- **Orchestration:** Kubernetes (K8s) for production, Docker Compose locally
- **CI:** GitHub Actions / GitLab CI / CircleCI

### 3.2 Project Skeleton (Node.js Example)

```bash
mkdir order-a2a-service
cd order-a2a-service
npm init -y
npm install express jsonwebtoken ajv pino pino-pretty axios
npm install --save-dev typescript @types/node @types/express ts-node-dev jest @types/jest
npx tsc --init
```

**Basic folder structure:**

```text
order-a2a-service/
  src/
    index.ts
    config.ts
    routes/
      orders.ts
    middleware/
      auth.ts
      errorHandler.ts
      logging.ts
    services/
      orderService.ts
    lib/
      db.ts
      kafka.ts
  test/
    unit/
    integration/
  docker/
  .github/workflows/
  package.json
  tsconfig.json
  Dockerfile
```

**Minimal Express bootstrap (`src/index.ts`):**

```ts
import express from "express";
import { json } from "body-parser";
import { ordersRouter } from "./routes/orders";
import { loggingMiddleware } from "./middleware/logging";
import { errorHandler } from "./middleware/errorHandler";

const app = express();

app.use(json());
app.use(loggingMiddleware); // request logging

app.use("/v1/orders", ordersRouter);

// central error handler
app.use(errorHandler);

const port = process.env.PORT || 3000;

app.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`Order A2A service listening on port ${port}`);
});
```

---

## 4. Designing the A2A API Contract

Strong contracts are especially important for A2A, where there’s no human to “work around” ambiguous behavior.

### 4.1 Resource Modeling

Example endpoints:

- `POST /v1/orders` – create new order
- `GET /v1/orders/{id}` – fetch an order
- `GET /v1/orders?status=PENDING&limit=50` – list orders

**Request example (POST /v1/orders):**

```json
{
  "idempotencyKey": "9d0c2c1b-27e7-4e65-8a1b-43f684c2d7a9",
  "customerId": "cust_123",
  "items": [
    { "sku": "ABC-001", "quantity": 2 },
    { "sku": "XYZ-777", "quantity": 1 }
  ],
  "totalAmount": {
    "currency": "USD",
    "value": "129.99"
  },
  "metadata": {
    "sourceSystem": "order-orchestrator"
  }
}
```

**Response example:**

```json
{
  "orderId": "ord_456",
  "status": "PENDING",
  "createdAt": "2025-12-26T21:45:10.123Z",
  "links": {
    "self": "/v1/orders/ord_456"
  }
}
```

### 4.2 Versioning Strategy

Common strategies:

- **URI versioning:** `/v1/orders`, `/v2/orders`
- **Header-based:** `Accept: application/vnd.mycompany.order+json;version=1`

> For A2A, URI versioning is often easiest to manage operationally and in contract tests.

Guidelines:

- Never make **breaking changes** in an existing version.
- Introduce new fields in a **backwards-compatible** way (clients should ignore unknown fields).
- Deprecate versions with clear timelines.

### 4.3 Idempotency and Request Correlation

A2A clients often retry on failure, so endpoints must be idempotent.

- For `POST /v1/orders`:
  - Require an `Idempotency-Key` header or `idempotencyKey` field.
  - Store this with the resulting order ID.
  - On retry with the same key, **return the same order** instead of creating a new one.

**Request correlation:**

- Generate a `X-Request-Id` if the client doesn’t send one.
- Log it in all services to trace a single call across systems.

### 4.4 Error Handling Conventions

Return **predictable error shapes** so client automation can respond.

Example error schema:

```json
{
  "error": {
    "code": "ORDER_VALIDATION_FAILED",
    "message": "Invalid order payload",
    "details": [
      { "field": "items[0].sku", "message": "SKU is required" }
    ],
    "correlationId": "req-1234abcd"
  }
}
```

Use appropriate HTTP status codes:

- `400` – validation error
- `401` – authentication failure
- `403` – authorization failure
- `404` – resource not found
- `409` – conflict (e.g., duplicate idempotency key)
- `429` – rate limited
- `500` / `503` – server / dependency issues

---

## 5. Implementing AuthN & AuthZ for A2A

### 5.1 OAuth 2.0 Client Credentials

For machine clients:

1. Each client (e.g., Order Orchestrator) is registered with the IdP.
2. Client authenticates with client ID and secret or mTLS cert.
3. IdP issues an access token (usually a JWT).
4. The A2A service validates the token on each request.

**Express middleware example (`src/middleware/auth.ts`):**

```ts
import { Request, Response, NextFunction } from "express";
import jwt, { JwtPayload } from "jsonwebtoken";

interface AuthenticatedRequest extends Request {
  auth?: {
    clientId: string;
    scopes: string[];
  };
}

// In production these values come from env/config
const ISSUER = process.env.OIDC_ISSUER!;
const AUDIENCE = process.env.OIDC_AUDIENCE!;
const JWKS_URL = `${ISSUER}/.well-known/jwks.json`;

// For brevity we use a simple secret here; in production use JWKS and proper key rotation.
const SHARED_SECRET = process.env.OIDC_SHARED_SECRET!;

export function authMiddleware(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
) {
  const authHeader = req.headers.authorization;
  if (!authHeader?.startsWith("Bearer ")) {
    return res.status(401).json({
      error: {
        code: "UNAUTHORIZED",
        message: "Missing or invalid Authorization header"
      }
    });
  }

  const token = authHeader.substring("Bearer ".length);

  try {
    const decoded = jwt.verify(token, SHARED_SECRET) as JwtPayload;
    if (decoded.iss !== ISSUER || decoded.aud !== AUDIENCE) {
      throw new Error("Invalid token issuer or audience");
    }

    const clientId = decoded.sub as string;
    const scopes = (decoded.scope as string)?.split(" ") ?? [];

    req.auth = { clientId, scopes };
    next();
  } catch (err) {
    return res.status(401).json({
      error: {
        code: "INVALID_TOKEN",
        message: "Access token is invalid or expired"
      }
    });
  }
}
```

Attach this middleware to protected routes:

```ts
import { Router } from "express";
import { authMiddleware } from "../middleware/auth";
import { createOrderHandler, getOrderHandler } from "../services/orderService";

export const ordersRouter = Router();

ordersRouter.post("/", authMiddleware, createOrderHandler);
ordersRouter.get("/:id", authMiddleware, getOrderHandler);
```

### 5.2 mTLS (Mutual TLS)

mTLS adds an additional layer of trust:

- The client presents a TLS certificate.
- The server verifies it against a trusted CA.
- You map certificate attributes (e.g., CN, SAN) to client identity.

You typically configure mTLS at:

- **API Gateway / Ingress Controller**
- or **Service Mesh** (e.g., Istio, Linkerd)

> Combine mTLS with OAuth 2.0 where possible: certificates for network trust, tokens for application‑level authorization.

### 5.3 Role- and Scope-Based Authorization

Once a request is authenticated:

- Use `scope` claims to enforce fine‑grained access (e.g., `orders:write`, `orders:read`).
- Optionally, use custom claims for tenant or environment restrictions.

```ts
function requireScopes(requiredScopes: string[]) {
  return (req: any, res: any, next: any) => {
    const tokenScopes = req.auth?.scopes || [];
    const missing = requiredScopes.filter(s => !tokenScopes.includes(s));

    if (missing.length > 0) {
      return res.status(403).json({
        error: {
          code: "INSUFFICIENT_SCOPE",
          message: `Missing required scopes: ${missing.join(", ")}`
        }
      });
    }

    next();
  };
}

ordersRouter.post(
  "/",
  authMiddleware,
  requireScopes(["orders:write"]),
  createOrderHandler
);
```

---

## 6. Robustness: Validation, Resilience, and Retries

### 6.1 Input Validation

Use a JSON schema and validate every incoming request.

**Schema (simplified) using Ajv:**

```ts
// src/schemas/orderCreateSchema.ts
export const orderCreateSchema = {
  type: "object",
  required: ["idempotencyKey", "customerId", "items", "totalAmount"],
  properties: {
    idempotencyKey: { type: "string", minLength: 10 },
    customerId: { type: "string", minLength: 1 },
    items: {
      type: "array",
      minItems: 1,
      items: {
        type: "object",
        required: ["sku", "quantity"],
        properties: {
          sku: { type: "string" },
          quantity: { type: "integer", minimum: 1 }
        }
      }
    },
    totalAmount: {
      type: "object",
      required: ["currency", "value"],
      properties: {
        currency: { type: "string", pattern: "^[A-Z]{3}$" },
        value: { type: "string", pattern: "^[0-9]+(\\.[0-9]{2})?$" }
      }
    },
    metadata: { type: "object", additionalProperties: true }
  }
};
```

**Validation middleware:**

```ts
import { Request, Response, NextFunction } from "express";
import Ajv from "ajv";
import { orderCreateSchema } from "../schemas/orderCreateSchema";

const ajv = new Ajv({ allErrors: true });

const validateOrderCreate = ajv.compile(orderCreateSchema);

export function validateOrderCreateMiddleware(
  req: Request,
  res: Response,
  next: NextFunction
) {
  const valid = validateOrderCreate(req.body);
  if (!valid) {
    return res.status(400).json({
      error: {
        code: "ORDER_VALIDATION_FAILED",
        message: "Invalid order payload",
        details: validateOrderCreate.errors
      }
    });
  }
  next();
}
```

Attach to route:

```ts
ordersRouter.post(
  "/",
  authMiddleware,
  requireScopes(["orders:write"]),
  validateOrderCreateMiddleware,
  createOrderHandler
);
```

### 6.2 Timeouts, Retries, and Circuit Breakers

A2A systems often depend on other services. Without safeguards:

- Downstream slowness cascades into outages.
- Clients retry aggressively and amplify load.

Recommendations:

- **Client-side timeouts** (e.g., 1–3 seconds for synchronous calls).
- **Limited retries with exponential backoff**, only for safe operations.
- **Circuit breakers** to stop hammering unhealthy dependencies.

Node.js example using `axios` with timeout and retry (simplified):

```ts
import axios from "axios";

const client = axios.create({
  baseURL: process.env.PAYMENT_API_URL,
  timeout: 2000 // 2 seconds
});

async function callPaymentAPI(payload: any) {
  let attempts = 0;
  const maxAttempts = 3;

  while (true) {
    attempts++;
    try {
      return await client.post("/v1/payments", payload);
    } catch (err: any) {
      const retryable =
        err.code === "ECONNABORTED" || // timeout
        (err.response && err.response.status >= 500); // server error

      if (!retryable || attempts >= maxAttempts) {
        throw err;
      }

      const delay = 100 * 2 ** (attempts - 1); // 100ms, 200ms, 400ms
      await new Promise(r => setTimeout(r, delay));
    }
  }
}
```

For full circuit breaker behavior, use libraries like **opossum** or implement in a service mesh (e.g., Istio’s outlier detection).

---

## 7. Observability: Logging, Metrics, and Tracing

### 7.1 Structured Logging

For A2A, logs are often parsed by machines. Use structured JSON logs.

**Pino-based request logging (`logging.ts`):**

```ts
import pino from "pino";
import pinoHttp from "pino-http";
import { v4 as uuid } from "uuid";

export const logger = pino({
  level: process.env.LOG_LEVEL || "info",
  transport:
    process.env.NODE_ENV === "development"
      ? { target: "pino-pretty", options: { colorize: true } }
      : undefined
});

export const loggingMiddleware = pinoHttp({
  logger,
  genReqId: (req) => req.headers["x-request-id"]?.toString() || uuid(),
  customLogLevel: function (res, err) {
    if (res.statusCode >= 500 || err) return "error";
    if (res.statusCode >= 400) return "warn";
    return "info";
  }
});
```

Log important contextual fields:

- `requestId`
- `clientId`
- `scope`
- `orderId`
- error codes, not stack traces only

### 7.2 Metrics

Use Prometheus‑style metrics:

- **Counters:** `http_requests_total`, `orders_created_total`
- **Histograms:** `http_request_duration_seconds`
- **Gauges:** `in_flight_requests`

Node.js example with `prom-client`:

```ts
import client from "prom-client";
import express from "express";

const register = new client.Registry();
client.collectDefaultMetrics({ register });

const httpRequestDuration = new client.Histogram({
  name: "http_request_duration_seconds",
  help: "HTTP request duration",
  labelNames: ["method", "route", "status_code"],
  buckets: [0.05, 0.1, 0.3, 0.5, 1, 2, 5]
});
register.registerMetric(httpRequestDuration);

export function metricsMiddleware(
  req: express.Request,
  res: express.Response,
  next: express.NextFunction
) {
  const end = httpRequestDuration.startTimer();
  res.on("finish", () => {
    end({
      method: req.method,
      route: req.route?.path || req.path,
      status_code: res.statusCode
    });
  });
  next();
}

export function metricsRoute(app: express.Express) {
  app.get("/metrics", async (_req, res) => {
    res.set("Content-Type", register.contentType);
    res.end(await register.metrics());
  });
}
```

### 7.3 Distributed Tracing

Tracing is essential when:

- a request flows through multiple A2A services
- you need to debug latency or failures in the chain

Use **OpenTelemetry**:

- Instrument HTTP server and clients
- Export traces to Jaeger, Zipkin, or your APM (Datadog, New Relic, etc.)
- Propagate trace IDs using `traceparent` header

---

## 8. Testing Strategy from Day One

### 8.1 Unit Tests

Test:

- business logic (e.g., order total calculation)
- edge cases (empty items, invalid currency)
- error mapping to HTTP codes

Example Jest test (simplified):

```ts
import { calculateTotal } from "../../src/services/orderService";

describe("calculateTotal", () => {
  it("sums line items correctly", () => {
    const items = [
      { sku: "A", quantity: 2, unitPrice: "10.00" },
      { sku: "B", quantity: 1, unitPrice: "5.50" }
    ];
    const total = calculateTotal(items);
    expect(total).toBe("25.50");
  });
});
```

### 8.2 Integration and Contract Tests

Integration tests:

- spin up the service with a real or ephemeral DB
- hit HTTP endpoints and assert behavior

Contract tests (e.g., Pact):

- ensure that changes to the service do not break existing consumers
- useful when you cannot coordinate releases across many client teams

### 8.3 Performance and Load Testing

Use tools like:

- **k6**, **Locust**, or **JMeter** to simulate realistic traffic
- Measure throughput, latency percentiles (p95, p99), and error rates
- Validate behavior under:
  - normal load
  - peak load
  - failure of dependencies (e.g., DB slowdown)

---

## 9. From Dev to Production: CI/CD

### 9.1 Containerization with Docker

**Example `Dockerfile`:**

```dockerfile
# Stage 1: Build
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Runtime
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
EXPOSE 3000
CMD ["node", "dist/index.js"]
```

### 9.2 CI Example with GitHub Actions

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: ["main"]
  pull_request:

jobs:
  build-and-test:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Use Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"

      - name: Install dependencies
        run: npm ci

      - name: Run unit tests
        run: npm test

      - name: Build
        run: npm run build

      - name: Build Docker image
        run: |
          docker build -t ghcr.io/${{ github.repository }}:${{ github.sha }} .
```

You can extend this:

- push the image to a container registry
- run integration tests using `docker-compose`
- add security scans (Snyk, Trivy)

### 9.3 Deployment Strategies

Common patterns:

- **Blue‑Green**
  - Run both old and new versions; cut over traffic when new is healthy.
- **Canary**
  - Gradually shift traffic to the new version; roll back if metrics degrade.
- **Rolling updates**
  - Replace pods gradually with minimal downtime (typical on K8s).

For A2A, canary is often preferred:

- traffic is predictable
- automation can check **SLOs** before ramping up

---

## 10. Production-Grade Infrastructure

### 10.1 Kubernetes Example

A basic `Deployment` + `Service`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-a2a
spec:
  replicas: 3
  selector:
    matchLabels:
      app: order-a2a
  template:
    metadata:
      labels:
        app: order-a2a
    spec:
      containers:
        - name: order-a2a
          image: ghcr.io/myorg/order-a2a-service:1.0.0
          ports:
            - containerPort: 3000
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health/live
              port: 3000
            initialDelaySeconds: 15
            periodSeconds: 20
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "512Mi"
          envFrom:
            - secretRef:
                name: order-a2a-secrets
            - configMapRef:
                name: order-a2a-config
---
apiVersion: v1
kind: Service
metadata:
  name: order-a2a
spec:
  selector:
    app: order-a2a
  ports:
    - protocol: TCP
      port: 80
      targetPort: 3000
```

Behind an **Ingress** (NGINX, AWS ALB, GKE Ingress, etc.) that:

- terminates TLS
- enforces mTLS (if required)
- applies rate limits and WAF rules

### 10.2 Configuration and Secrets Management

- Use **ConfigMaps** for non‑sensitive config (timeouts, feature flags).
- Use **Secrets** or external secret managers for:
  - DB credentials
  - IdP client secrets
  - signing keys (if you issue your own JWTs)

> Never bake secrets into images or commit them to git.

---

## 11. Security and Compliance Hardening

Key practices for A2A production services:

- **Least privilege everywhere**
  - Each client gets only the scopes it truly needs.
  - Each service account has minimal permissions (in K8s, DB, etc.).
- **Token lifetime management**
  - Short‑lived access tokens, long‑lived refresh tokens kept server‑side only.
- **Key rotation**
  - Rotate signing keys and TLS certificates regularly.
  - Automate with ACME (Let’s Encrypt) or cloud‑native solutions.
- **Input sanitization**
  - Even for “trusted” A2A clients, validate all inputs.
- **Rate limiting and abuse prevention**
  - Protect against runaway clients or bugs that flood the system.
- **Audit logging**
  - Track who (which client) called what, when, and what the outcome was.
- **Compliance alignment**
  - If dealing with payments: PCI-DSS
  - If dealing with personal data: GDPR/CCPA
  - Ensure data retention and deletion policies are implemented.

---

## 12. Operating A2A in Production

Operational excellence includes:

- **Runbooks**
  - Clear procedures for common incidents: DB outage, message bus lag, IdP downtime.
- **On‑call and alerting**
  - Alerts on:
    - elevated error rate (5xx)
    - increased latency (p95)
    - spike in 401/403 (auth issues)
    - backlog in message queues
- **SLOs and SLIs**
  - Example:
    - Availability SLO: 99.9% over 30 days
    - Latency SLO: p95 < 500 ms for `POST /v1/orders`
- **Change management**
  - Feature flags to roll out new behavior gradually.
  - Shadow deployments for major logic changes (e.g., new pricing