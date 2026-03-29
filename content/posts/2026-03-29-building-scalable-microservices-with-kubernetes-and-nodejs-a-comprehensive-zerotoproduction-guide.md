---
title: "Building Scalable Microservices with Kubernetes and Node.js: A Comprehensive Zero‑to‑Production Guide"
date: "2026-03-29T01:00:43.612"
draft: false
tags: ["kubernetes","nodejs","microservices","devops","scalability"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Combine Node.js and Kubernetes?](#why-combine-nodejs-and-kubernetes)  
3. [Prerequisites & Toolchain Setup](#prerequisites--toolchain-setup)  
4. [Designing a Microservice Architecture](#designing-a-microservice-architecture)  
   - 4.1 [Domain‑Driven Design Basics](#domain-driven-design-basics)  
   - 4.2 [API Contracts with OpenAPI](#api-contracts-with-openapi)  
5. [Implementing the First Node.js Service](#implementing-the-first-nodejs-service)  
   - 5.1 [Project Scaffold](#project-scaffold)  
   - 5.2 [Business Logic & Routes](#business-logic--routes)  
   - 5.3 [Testing the Service Locally](#testing-the-service-locally)  
6. [Containerizing the Service](#containerizing-the-service)  
   - 6.1 [Dockerfile Best Practices](#dockerfile-best-practices)  
   - 6.2 [Multi‑Stage Builds for Smaller Images](#multi-stage-builds-for-smaller-images)  
7. [Kubernetes Foundations](#kubernetes-foundations)  
   - 7.1 [Namespaces, Labels, and Annotations](#namespaces-labels-and-annotations)  
   - 7.2 [Deployments, Services, and Ingress](#deployments-services-and-ingress)  
8. [Deploying the Service to a Cluster](#deploying-the-service-to-a-cluster)  
   - 8.1 [Helm Chart Structure](#helm-chart-structure)  
   - 8.2 [Applying Manifests Manually](#applying-manifests-manually)  
9. [Scaling Strategies](#scaling-strategies)  
   - 9.1 [Horizontal Pod Autoscaling (HPA)](#horizontal-pod-autoscaling-hpa)  
   - 9.2 [Cluster Autoscaler & Node Pools](#cluster-autoscaler--node-pools)  
10. [Observability: Logging, Metrics, Tracing](#observability-logging-metrics-tracing)  
    - 10.1 [Centralized Logging with Loki](#centralized-logging-with-loki)  
    - 10.2 [Metrics via Prometheus & Grafana](#metrics-via-prometheus--grafana)  
    - 10.3 [Distributed Tracing with Jaeger](#distributed-tracing-with-jaeger)  
11. [Configuration & Secrets Management](#configuration--secrets-management)  
12. [CI/CD Pipeline (GitHub Actions Example)](#cicd-pipeline-github-actions-example)  
13. [Advanced Deployment Patterns](#advanced-deployment-patterns)  
    - 13.1 [Blue‑Green Deployments](#blue-green-deployments)  
    - 13.2 [Canary Releases with Flagger](#canary-releases-with-flagger)  
14. [Security Considerations](#security-considerations)  
15. [Testing in a Kubernetes Environment](#testing-in-a-kubernetes-environment)  
16. [Conclusion](#conclusion)  
17. [Resources](#resources)

---

## Introduction

Microservices have become the de‑facto architecture for modern, cloud‑native applications. They let teams ship features independently, scale components in isolation, and adopt the best technology for each problem domain. However, the promise of microservices comes with operational complexity: service discovery, health‑checking, scaling, logging, and secure configuration must be managed at scale.

Kubernetes (K8s) provides a powerful, declarative platform for orchestrating containers, handling many of those operational concerns automatically. Pairing Kubernetes with **Node.js**—a lightweight, event‑driven runtime that excels at I/O‑bound workloads—creates a compelling stack for building highly scalable, responsive services.

This guide walks you **from zero to production**:

* **Zero** – set up a local development environment, write a simple Node.js microservice, containerize it, and run it locally.
* **Production** – package the service with Helm, deploy it to a real Kubernetes cluster, enable autoscaling, add observability, secure secrets, and automate the entire lifecycle with CI/CD.

By the end you’ll have a production‑ready repository that you can clone, adapt, and extend for your own business domains.

---

## Why Combine Node.js and Kubernetes?

| Aspect | Node.js | Kubernetes |
|--------|----------|-------------|
| **Concurrency Model** | Single‑threaded event loop, non‑blocking I/O → ideal for APIs, streaming, websockets. | Schedules containers across a cluster, abstracts the underlying infrastructure. |
| **Developer Velocity** | Rich npm ecosystem, fast prototyping, TypeScript support. | Declarative YAML/Helm, self‑healing, built‑in service discovery. |
| **Scalability** | Horizontal scaling via clustering (`pm2`, `node cluster`). | Horizontal Pod Autoscaling (HPA), Cluster Autoscaler, load‑balancing. |
| **Observability** | Mature libraries (`winston`, `pino`, `@opentelemetry`). | Integrated with Prometheus, Grafana, Loki, Jaeger. |
| **Deployment Footprint** | Small runtime (≈ 30 MB). | Lightweight pods, can be run on any cloud or on‑prem. |

When you combine the two, you inherit the rapid development cycle of Node.js while delegating the heavy lifting of orchestration, scaling, and resilience to Kubernetes.

---

## Prerequisites & Toolchain Setup

| Tool | Version (minimum) | Purpose |
|------|-------------------|---------|
| **Node.js** | 20.x | Runtime for services |
| **npm / Yarn** | 9.x | Package management |
| **Docker** | 24.x | Build container images |
| **kubectl** | 1.28+ | Interact with clusters |
| **Kind** or **Minikube** | 0.20+ | Local K8s cluster for dev |
| **Helm** | 3.12+ | Package manager for K8s |
| **Git** | 2.40+ | Source control |
| **GitHub Actions** (optional) | - | CI/CD pipeline |

> **Note:** All commands shown assume a Unix‑like shell (bash, zsh). Windows users can use WSL2 or PowerShell with equivalent commands.

---

## Designing a Microservice Architecture

### Domain‑Driven Design Basics

Before writing code, identify **bounded contexts**—logical domains that can evolve independently. For this guide we’ll build a tiny e‑commerce system with three services:

1. **Product Service** – CRUD for product catalog.
2. **Order Service** – Handles order creation, validation, and persistence.
3. **Notification Service** – Sends email/SMS after order placement.

Each service owns its own database (MongoDB for products, PostgreSQL for orders) and communicates over **HTTP/REST** and **gRPC** (optional). This separation enforces the *single responsibility principle* and makes scaling decisions straightforward.

### API Contracts with OpenAPI

Define contracts first, then generate client SDKs or server stubs:

```yaml
# openapi/product.yaml
openapi: 3.0.3
info:
  title: Product API
  version: 1.0.0
paths:
  /products:
    get:
      summary: List all products
      responses:
        '200':
          description: A JSON array of products
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/Product'
    post:
      summary: Create a new product
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ProductCreate'
      responses:
        '201':
          description: Product created
components:
  schemas:
    Product:
      type: object
      properties:
        id:
          type: string
        name:
          type: string
        price:
          type: number
    ProductCreate:
      type: object
      required: [name, price]
      properties:
        name:
          type: string
        price:
          type: number
```

You can generate TypeScript types with `openapi-generator-cli` or `swagger-typescript-api`, ensuring both client and server stay in sync.

---

## Implementing the First Node.js Service

We'll start with **Product Service**.

### Project Scaffold

```bash
mkdir product-service
cd product-service
npm init -y
npm install express mongoose cors dotenv pino
npm install -D typescript @types/node @types/express ts-node-dev eslint prettier
npx tsc --init
```

**Directory layout**

```
product-service/
├─ src/
│  ├─ config/
│  │   └─ index.ts
│  ├─ models/
│  │   └─ product.ts
│  ├─ routes/
│  │   └─ product.ts
│  ├─ app.ts
│  └─ server.ts
├─ .env
├─ Dockerfile
├─ helm/
│  └─ product/
└─ package.json
```

### Business Logic & Routes

```ts
// src/models/product.ts
import { Schema, model, Document } from 'mongoose';

export interface IProduct extends Document {
  name: string;
  price: number;
}

const ProductSchema = new Schema<IProduct>({
  name: { type: String, required: true },
  price: { type: Number, required: true },
});

export const Product = model<IProduct>('Product', ProductSchema);
```

```ts
// src/routes/product.ts
import { Router, Request, Response } from 'express';
import { Product } from '../models/product';

const router = Router();

/**
 * GET /products
 * Returns a list of all products.
 */
router.get('/', async (_req: Request, res: Response) => {
  const products = await Product.find();
  res.json(products);
});

/**
 * POST /products
 * Creates a new product.
 */
router.post('/', async (req: Request, res: Response) => {
  const { name, price } = req.body;
  const product = new Product({ name, price });
  await product.save();
  res.status(201).json(product);
});

export default router;
```

```ts
// src/app.ts
import express from 'express';
import cors from 'cors';
import mongoose from 'mongoose';
import productRouter from './routes/product';
import pino from 'pino-http';

require('dotenv').config();

const app = express();

app.use(pino());
app.use(cors());
app.use(express.json());

app.use('/products', productRouter);

// Health endpoint
app.get('/health', (_req, res) => res.send('OK'));

export default app;
```

```ts
// src/server.ts
import app from './app';

const PORT = process.env.PORT || 3000;
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongo:27017/products';

mongoose
  .connect(MONGO_URI)
  .then(() => {
    console.log('MongoDB connected');
    app.listen(PORT, () => console.log(`🚀 Product service listening on ${PORT}`));
  })
  .catch((err) => {
    console.error('MongoDB connection error:', err);
    process.exit(1);
  });
```

### Testing the Service Locally

Add a simple **unit test** with Jest:

```bash
npm install -D jest ts-jest @types/jest supertest
npx ts-jest config:init
```

```ts
// tests/product.test.ts
import request from 'supertest';
import app from '../src/app';
import mongoose from 'mongoose';
import { Product } from '../src/models/product';

beforeAll(async () => {
  await mongoose.connect('mongodb://localhost:27017/test-products');
});

afterAll(async () => {
  await mongoose.connection.db.dropDatabase();
  await mongoose.disconnect();
});

describe('Product API', () => {
  it('creates a product', async () => {
    const res = await request(app).post('/products').send({ name: 'Apple', price: 1.99 });
    expect(res.status).toBe(201);
    expect(res.body.name).toBe('Apple');
  });

  it('lists products', async () => {
    const res = await request(app).get('/products');
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body)).toBe(true);
  });
});
```

Run with `npm test`. All good? Great—now we have a functional microservice ready for containerization.

---

## Containerizing the Service

### Dockerfile Best Practices

```dockerfile
# ---- Build Stage ----
FROM node:20-alpine AS builder
WORKDIR /app

# Install only production dependencies
COPY package*.json ./
RUN npm ci --production

# Copy source files
COPY tsconfig.json ./
COPY src ./src

# Compile TypeScript
RUN npx tsc

# ---- Runtime Stage ----
FROM node:20-alpine AS runtime
WORKDIR /app

# Copy compiled output and production node_modules from builder
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./

# Non‑root user for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

EXPOSE 3000
ENV NODE_ENV=production

CMD ["node", "dist/server.js"]
```

**Why multi‑stage?** The final image contains only compiled JavaScript and the minimal `node_modules`, resulting in a ~60 MB image—great for fast pull/push cycles.

### Building & Running Locally

```bash
docker build -t product-service:1.0 .
docker run -d -p 3000:3000 --name product-service \
  -e MONGO_URI=mongodb://host.docker.internal:27017/products \
  product-service:1.0
```

Visit `http://localhost:3000/health` → `OK`. The service works inside a container.

---

## Kubernetes Foundations

### Namespaces, Labels, and Annotations

* **Namespaces** isolate environments (e.g., `dev`, `staging`, `prod`).  
* **Labels** enable selection (`app=product-service`).  
* **Annotations** store metadata (e.g., `prometheus.io/scrape: "true"`).

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: prod
  labels:
    environment: production
```

### Deployments, Services, and Ingress

* **Deployment** – declarative pod management, rollout history.  
* **Service** – stable cluster IP, load‑balancing.  
* **Ingress** – HTTP routing at the edge (NGINX, Traefik, or cloud LB).

---

## Deploying the Service to a Cluster

### Helm Chart Structure

```
helm/
└─ product/
   ├─ Chart.yaml
   ├─ values.yaml
   └─ templates/
       ├─ deployment.yaml
       ├─ service.yaml
       └─ ingress.yaml
```

**Chart.yaml**

```yaml
apiVersion: v2
name: product
description: Helm chart for the Product microservice
type: application
version: 0.1.0
appVersion: "1.0"
```

**values.yaml**

```yaml
replicaCount: 2

image:
  repository: your-registry/product-service
  tag: "1.0"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80
  targetPort: 3000

ingress:
  enabled: true
  className: nginx
  host: products.example.com
  tls: true
  secretName: product-tls

resources:
  limits:
    cpu: "500m"
    memory: "256Mi"
  requests:
    cpu: "250m"
    memory: "128Mi"

env:
  MONGO_URI: mongodb://mongo.prod.svc.cluster.local:27017/products
```

**templates/deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "product.fullname" . }}
  labels:
    {{- include "product.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "product.name" . }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ include "product.name" . }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.service.targetPort }}
          env:
            - name: MONGO_URI
              value: "{{ .Values.env.MONGO_URI }}"
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          livenessProbe:
            httpGet:
              path: /health
              port: {{ .Values.service.targetPort }}
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: {{ .Values.service.targetPort }}
            initialDelaySeconds: 5
            periodSeconds: 5
```

**templates/service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "product.fullname" . }}
  labels:
    {{- include "product.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
  selector:
    app.kubernetes.io/name: {{ include "product.name" . }}
```

**templates/ingress.yaml** (optional)

```yaml
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "product.fullname" . }}
  annotations:
    kubernetes.io/ingress.class: {{ .Values.ingress.className }}
    nginx.ingress.kubernetes.io/rewrite-target: /
    {{- if .Values.ingress.tls }}
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    {{- end }}
spec:
  {{- if .Values.ingress.tls }}
  tls:
    - hosts:
        - {{ .Values.ingress.host }}
      secretName: {{ .Values.ingress.secretName }}
  {{- end }}
  rules:
    - host: {{ .Values.ingress.host }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "product.fullname" . }}
                port:
                  number: {{ .Values.service.port }}
{{- end }}
```

Deploy:

```bash
helm upgrade --install product ./helm/product --namespace prod --create-namespace
```

Verify:

```bash
kubectl -n prod get pods -l app.kubernetes.io/name=product
kubectl -n prod get svc
kubectl -n prod get ingress
```

---

## Scaling Strategies

### Horizontal Pod Autoscaling (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: product-hpa
  namespace: prod
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: product
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
```

Apply with `kubectl apply -f hpa.yaml`. The HPA watches CPU usage and adds pods up to 10 when needed.

### Cluster Autoscaler & Node Pools

If you run on a managed service (GKE, EKS, AKS), enable **Cluster Autoscaler** so the underlying node pool expands when the scheduler cannot place pods. For on‑prem you can use the open‑source `cluster-autoscaler` with a cloud‑provider plugin.

---

## Observability: Logging, Metrics, Tracing

### Centralized Logging with Loki

1. **Deploy Loki** via Helm:

   ```bash
   helm repo add grafana https://grafana.github.io/helm-charts
   helm install loki grafana/loki-stack -n monitoring --create-namespace
   ```

2. **Configure pino** to output JSON (already done). Add a sidecar `promtail` that ships logs to Loki.

3. In the Helm chart, add:

   ```yaml
   annotations:
     prometheus.io/scrape: "true"
     prometheus.io/port: "3000"
   ```

   and enable `promtail` in the Loki stack to collect logs from the pod’s `/var/log/containers` directory.

### Metrics via Prometheus & Grafana

*Expose metrics* using `prom-client`:

```ts
// src/metrics.ts
import client from 'prom-client';
export const httpRequestDurationMicroseconds = new client.Histogram({
  name: 'http_request_duration_ms',
  help: 'Duration of HTTP requests in ms',
  labelNames: ['method', 'route', 'code'],
  buckets: [0.1, 5, 15, 50, 100, 300, 500, 1000],
});
```

Add a `/metrics` endpoint:

```ts
import { httpRequestDurationMicroseconds } from './metrics';
app.get('/metrics', async (_req, res) => {
  res.set('Content-Type', client.register.contentType);
  res.end(await client.register.metrics());
});
```

Deploy **Prometheus** with the Helm chart `prometheus-community/kube-prometheus-stack`. Ensure it scrapes the `/metrics` endpoint by adding:

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "3000"
  prometheus.io/path: "/metrics"
```

Create Grafana dashboards to visualize request latency, error rates, and pod resource usage.

### Distributed Tracing with Jaeger

1. Install Jaeger operator:

   ```bash
   helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
   helm install jaeger jaegertracing/jaeger -n observability --create-namespace
   ```

2. Add OpenTelemetry SDK to the service:

   ```bash
   npm install @opentelemetry/api @opentelemetry/sdk-node @opentelemetry/instrumentation-http @opentelemetry/exporter-jaeger
   ```

3. Bootstrap tracing (`src/tracing.ts`):

   ```ts
   import { NodeSDK } from '@opentelemetry/sdk-node';
   import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
   import { JaegerExporter } from '@opentelemetry/exporter-jaeger';

   const exporter = new JaegerExporter({
     endpoint: process.env.JAEGER_ENDPOINT || 'http://jaeger-collector.observability:14268/api/traces',
   });

   const sdk = new NodeSDK({
     traceExporter: exporter,
     instrumentations: [getNodeAutoInstrumentations()],
   });

   sdk.start();
   ```

   Import this module at the very top of `app.ts`. Requests now flow into Jaeger UI, where you can view spans across services (once you add tracing to Order and Notification services similarly).

---

## Configuration & Secrets Management

* **ConfigMaps** – non‑sensitive configuration (feature flags, URLs).  
* **Secrets** – passwords, API keys. Store in Kubernetes Secrets (base64‑encoded) and reference as environment variables or volume mounts.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: product-db-secret
type: Opaque
data:
  mongo-uri: {{ .Values.env.MONGO_URI | b64enc }}
```

In Helm, you can inject the secret:

```yaml
env:
  - name: MONGO_URI
    valueFrom:
      secretKeyRef:
        name: product-db-secret
        key: mongo-uri
```

For production, consider **external secret stores** (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault) using the **External Secrets Operator**.

---

## CI/CD Pipeline (GitHub Actions Example)

`.github/workflows/ci-cd.yml`

```yaml
name: CI/CD

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        run: npm ci
      - name: Run lint & tests
        run: |
          npm run lint
          npm test

  docker-build-push:
    needs: build-test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}
      - name: Build & push image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: your-registry/product-service:${{ github.sha }}

  deploy:
    needs: docker-build-push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up kubectl
        uses: azure/setup-kubectl@v3
        with:
          version: 'v1.28.0'
      - name: Configure Kubeconfig
        run: |
          echo "${{ secrets.KUBE_CONFIG }}" > $HOME/.kube/config
      - name: Deploy with Helm
        run: |
          helm upgrade --install product ./helm/product \
            --namespace prod \
            --set image.tag=${{ github.sha }} \
            --set env.MONGO_URI="${{ secrets.MONGO_URI }}"
```

*Key points*:

- **Lint + unit tests** gate the pipeline.  
- **Docker Build‑Push** pushes a uniquely tagged image (git SHA).  
- **Helm upgrade** performs a rolling update; Kubernetes will replace pods gracefully.  

You can extend this workflow with **GitOps** tools like Argo CD or Flux for declarative deployments.

---

## Advanced Deployment Patterns

### Blue‑Green Deployments

Create two separate Deployments (`product-blue`, `product-green`) and switch the Service selector between them. Helm can manage the two releases using a `values.yaml` flag:

```yaml
deploymentColor: blue   # or green
```

The Service definition:

```yaml
selector:
  app.kubernetes.io/name: product
  app.kubernetes.io/color: {{ .Values.deploymentColor }}
```

When you’re ready, change `deploymentColor` and run `helm upgrade`. No downtime because the Service routes traffic only to the selected color.

### Canary Releases with Flagger

**Flagger** automates progressive delivery:

```bash
helm repo add flagger https://flagger.app
helm install flagger flagger/flagger \
  --namespace prod \
  --set meshProvider=istio # or nginx, contour, etc.
```

Create a **Canary** custom resource:

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: product
  namespace: prod
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: product
  service:
    port: 80
    targetPort: 3000
  analysis:
    interval: 1m
    threshold: 10
    iterations: 10
    metrics:
      - name: request-success-rate
        threshold: 99
      - name: request-duration
        threshold: 500
```

Flagger will gradually shift traffic from the stable version to the new one, monitoring the defined metrics. If thresholds are breached, it rolls back automatically.

---

## Security Considerations

| Threat | Mitigation |
|--------|------------|
| **Container Escape** | Run as non‑root user, use `readOnlyRootFilesystem`, enable `seccomp` profile. |
| **Supply‑Chain Attacks** | Pin base image digests (`node@sha256:…`), enable **SLSA** verification in CI, scan images with Trivy (`trivy image`). |
| **Network Exposure** | Use NetworkPolicies to restrict intra‑namespace traffic. |
| **API Authentication** | Deploy an API gateway (Kong, Ambassador) with JWT validation, or use **Istio** mTLS for service‑to‑service encryption. |
| **Secret Leakage** | Store secrets in external vaults, rotate regularly, audit `kubectl get secret` access. |

Example NetworkPolicy allowing only the Order service to call Product:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-order-to-product
  namespace: prod
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: product
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: order
      ports:
        - protocol: TCP
          port: 3000
  policyTypes:
    - Ingress
```

---

## Testing in a Kubernetes Environment

1. **Integration Tests** – Deploy a temporary namespace, apply Helm chart, run tests against the service endpoint, then clean up.

```bash
kubectl create namespace test-${GITHUB_SHA}
helm upgrade --install product ./helm/product -n test-${GITHUB_SHA}
# Run test script that hits http://product.test-${GITHUB_SHA}.svc.cluster.local/health
kubectl delete namespace test-${GITHUB_SHA}
```

2. **Chaos Engineering** – Use **LitmusChaos** or **Chaos Mesh** to inject failures (pod kill, network latency) and verify resilience.

3. **Load Testing** – Run `k6` or `hey` from a pod inside the cluster to simulate realistic traffic and observe HPA response.

```bash
kubectl run load-generator --image=loadimpact/k6 --restart=Never -- \
  k6 run -d 2m -vus 100 -duration 30s /scripts/product_load_test.js
```

---

## Conclusion

Building a **scalable microservice** with **Node.js** and **Kubernetes** involves more than just writing code. The journey from a single Express endpoint to a fully observable, auto‑scaled, securely deployed production service requires:

* **Thoughtful domain modeling** (DDD, OpenAPI contracts).  
* **Robust containerization** (multi‑stage Docker, non‑root users).  
* **Declarative infrastructure** (Helm charts, K8s manifests).  
* **Automatic scaling** (HPA, Cluster Autoscaler).  
* **Deep observability** (centralized logging, Prometheus metrics, Jaeger tracing).  
* **Secure configuration** (Secrets, NetworkPolicies).  
* **Continuous delivery** (GitHub Actions, Helm, optional GitOps).  
* **Advanced rollout strategies** (blue‑green, canary with Flagger).  

By following the step‑by‑step patterns in this guide, you can bootstrap a production‑grade microservice ecosystem that scales with traffic, recovers from failures, and provides the visibility needed for rapid iteration. The same principles apply to additional services—simply replicate the scaffold, adjust the Helm values, and let Kubernetes handle the rest.

Happy coding, and may your clusters stay healthy!  

---

## Resources
- [Kubernetes Documentation](https://kubernetes.io/docs/) – Official guide to all K8s concepts, APIs, and best practices.  
- [Node.js Best Practices](https://github.com/goldbergyoni/nodebestpractices) – Community‑curated list of production‑ready patterns for Node.js.  
- [Helm Charts Repository](https://artifacthub.io/) – Find, share, and use Helm charts for common services (databases, ingress controllers, monitoring).  
- [Prometheus Operator](https://github.com/prometheus-operator/prometheus-operator) – Deploy and manage Prometheus and Grafana stacks on Kubernetes.  
- [OpenTelemetry for Node.js](https://opentelemetry.io/docs/instrumentation/js/) – Instrumentation libraries and exporters for tracing and metrics.  
- [Flagger – Progressive Delivery Operator](https://flagger.app/) – Automates canary releases, A/B testing, and blue‑green deployments.  

---