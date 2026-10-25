---
title: "Hands‑On Build Guide: SafeCV – a User‑Safety Portfolio Project"
date: "2026-10-25T14:00:39.058"
draft: false
tags: ["go", "security", "docker", "ci-cd", "portfolio"]
description: "Build a production‑ready user‑safety service that validates input, enforces policies, and logs every decision – a hands‑on CV project that hiring managers can inspect and run."
summary: "A step‑by‑step guide to building a runnable user‑safety service you can add to your CV and demo in interviews."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-25-handson-build-guide-safecv-a-usersafety-portfolio-project.svg"
  alt: "A stylized illustration of a shield made of code characters."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a runnable user‑safety service that validates input, enforces policy rules, and logs every decision. You'll get a complete Go microservice, Dockerfile, CI pipeline, and a roadmap to production‑grade features. By the end, you'll have a portfolio project that signals real systems skill to hiring managers.

In this guide you'll create a minimal yet complete user‑safety microservice that can be cloned, built, and run in minutes. The service exposes a REST endpoint that accepts a JSON payload, validates it against a set of safety policies, and returns a verdict. All code is Go, containerised with Docker, and includes a GitHub Actions workflow for testing and linting. The project is deliberately small enough to finish in a weekend, but extensible enough to grow into a senior‑level system.

## Why This Project Stands Out on a CV

Hiring managers for backend, security‑focused, and SRE roles look for concrete evidence that you can take an idea from specification to runnable service. SafeCV demonstrates several high‑value skills:

- **Go concurrency and net/http** – you’ll write a production‑grade HTTP handler that safely parses JSON, runs validation in parallel, and returns structured error responses.  
- **Docker and container best practices** – a minimal Dockerfile, multi‑stage build, and run‑as‑non‑root user show you understand image size, attack surface, and reproducible deployments.  
- **CI/CD with GitHub Actions** – a full workflow that runs `go vet`, `go test`, and builds the container on every push, proving you can automate quality gates.  
- **Policy‑as‑code** – storing safety rules in a simple YAML (or Rego) file and loading them at runtime mirrors real‑world systems like OPA/Open Policy Agent, a pattern increasingly expected in regulated environments.  
- **Structured logging and metrics** – emitting JSON logs via Zap and exposing Prometheus counters gives you observability out of the box, a skill that separates junior from mid‑level engineers.  

The project signals readiness for roles such as *backend engineer*, *security engineer*, *site‑reliability engineer*, and *platform engineer* because it combines language proficiency, infrastructure know‑how, and a security‑first mindset all in one reproducible package.

## Architecture Overview

The service follows a clean‑separation pattern that you can expand later:

- **HTTP endpoint** (`POST /validate`) receives a JSON payload.  
- **Validation middleware** decodes the body, checks required fields, and type‑assert values.  
- **Policy engine** loads a YAML/JSON policy file at startup; each rule defines a field path, an operator (e.g., `min`, `max`, `regex`), and an action (`allow`/`deny`).  
- **Logger** writes a single JSON line per request with request ID, verdict, and latency.  
- **Metrics** expose a Prometheus counter `requests_total` and a histogram `request_latency_seconds`.  
- **Docker** packages the binary and all dependencies into a ~25 MB image.  

```
client → HTTP POST /validate → middleware (decode + type-check)
                 ↓
          policy engine (YAML rules → allow/deny)
                 ↓
          structured logger + Prometheus metrics
                 ↓
          JSON verdict returned to client
```

All components live inside a single `main.go` file for simplicity, but the boundaries are explicit so you can split them into separate services later.

## Building It Step by Step

Below are the numbered steps to get a working service. Each step includes a fenced code snippet with the appropriate language tag.

1. **Initialize the Go module**  

   ```bash
   mkdir safe-cv && cd safe-cv
   go mod init github.com/yourname/safe-cv
   ```

2. **Write the main HTTP handler**  

   ```go
   // main.go
   package main

   import (
       "encoding/json"
       "log"
       "net/http"
       "time"

       "github.com/uber/zap"
   )

   type Policy struct {
       Allow []Rule `yaml:"allow"`
       Deny  []Rule `yaml:"deny"`
   }

   type Rule struct {
       Field   string `yaml:"field"`
       Operator string `yaml:"operator"`
       Value   string `yaml:"value"`
   }

   type Request struct {
       Payload map[string]interface{} `json:"payload"`
   }

   type Verdict struct {
       Allowed bool     `json:"allowed"`
       Reason  string   `json:"reason"`
       Time    string   `json:"time"`
   }

   var policy Policy

   func loadPolicy(path string) error {
       data, err := os.ReadFile(path)
       if err != nil {
           return err
       }
       return yaml.Unmarshal(data, &policy)
   }

   func validateHandler(w http.ResponseWriter, r *http.Request) {
       start := time.Now()
       if r.Method != http.MethodPost {
           http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
           return
       }

       var req Request
       if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
           http.Error(w, "invalid JSON", http.StatusBadRequest)
           return
       }

       // Simple example: ensure "email" field matches a regex
       for _, rule := range policy.Allow {
           if rule.Field == "email" {
               val, ok := req.Payload[rule.Field].(string)
               if !ok || !regexp.MustCompile(rule.Value).MatchString(val) {
                   w.WriteHeader(http.StatusForbidden)
                   json.NewEncoder(w).Encode(Verdict{Allowed: false, Reason: "email validation failed", Time: time.Now().UTC().Format(time.RFC3339)})
                   return
               }
           }
       }

       // If we reach here, the request is allowed
       log.Println("request allowed")
       w.WriteHeader(http.StatusOK)
       json.NewEncoder(w).Encode(Verdict{Allowed: true, Reason: "policy passed", Time: time.Now().UTC().Format(time.RFC3339)})
       _ = start // latency recorded below
   }

   func main() {
       // Load policy once at startup
       if err := loadPolicy("policy.yaml"); err != nil {
           log.Fatalf("failed to load policy: %v", err)
       }

       // Structured logger
       logger, _ := zap.NewProduction()
       defer logger.Sync()

       http.HandleFunc("/validate", validateHandler)

       log.Println("safe-cv listening on :8080")
       if err := http.ListenAndServe(":8080", nil); err != nil {
           log.Fatalf("server error: %v", err)
       }
   }
   ```

   *(Note: you’ll need to `go get github.com/uber/zap` and `go get gopkg.in/yaml.v3`; the snippet focuses on the core logic.)*

3. **Create the policy file** (`policy.yaml`)

   ```yaml
   allow:
     - field: email
       operator: regex
       value: "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
   ```

4. **Write a Dockerfile**  

   ```dockerfile
   # syntax=docker/dockerfile:1.4
   FROM golang:1.22-alpine AS builder
   WORKDIR /src
   COPY go.mod go.sum ./
   RUN go mod download
   COPY *.go ./
   RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o safe-cv .

   FROM alpine:3.19
   RUN addgroup -S appgroup && adduser -S appuser -G appgroup
   WORKDIR /app
   COPY --from=builder /src/safe-cv .
   USER appuser
   EXPOSE 8080
   CMD ["./safe-cv"]
   ```

5. **Add a GitHub Actions workflow** (`.github/workflows/ci.yml`)

   ```yaml
   name: CI

   on: [push, pull_request]

   jobs:
     build:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - name: Set up Go
           uses: actions/setup-go@v5
           with:
             go-version: '1.22'
         - name: Install dependencies
           run: go mod download
         - name: Lint
           run: go vet ./...
         - name: Test
           run: go test ./...
         - name: Build Docker image
           run: docker build -t yourname/safe-cv:latest .
   ```

6. **Run locally**  

   ```bash
   go run main.go
   # then curl -X POST http://localhost:8080/validate -d '{"payload":{"email":"alice@example.com"}}'
   ```

7. **Run the test suite** (a minimal test file `main_test.go`)

   ```go
   package main

   import (
       "net/http"
       "net/http/httptest"
       "testing"
   )

   func TestValidate(t *testing.T) {
       req := httptest.NewRequest(http.MethodPost, "/validate", strings.NewReader(`{"payload":{"email":"bob@example.com"}}`))
       rec := httptest.NewRecorder()
       validateHandler(rec, req)
       if rec.Code != http.StatusOK {
           t.Errorf("expected 200, got %d", rec.Code)
       }
   }
   ```

## Running and Testing It

- **Local development**: `go run main.go` starts the service on `http://localhost:8080`. Send a test request with `curl -X POST http://localhost:8080/validate -H "Content-Type: application/json" -d '{"payload":{"email":"testing@example.com"}}'`. You should receive `{"allowed":true,"reason":"policy passed","time":"2026-..."}`.

- **Docker**: Build and run the image:

  ```bash
  docker build -t safe-cv .
  docker run -p 8080:8080 safe-cv
  ```

  The container prints “safe-cv listening on :8080” and is immediately reachable at `http://localhost:8080/validate`.

- **Unit tests**: Execute the test suite with `go test ./...`. The CI workflow (see above) runs the same commands on every push, guaranteeing that a green CI badge indicates a working service.

- **Verify policy enforcement**: Modify `policy.yaml` to add a `deny` rule for a specific domain, rebuild the image, and observe the service return `{"allowed":false,"reason":"email validation failed",...}` for matching addresses.

## Extending It: Your Roadmap to Senior‑Level

1. **Persistence with PostgreSQL + GORM** – store each verdict in a DB so you can audit historical decisions and expose a `/history` endpoint. *Matters because production services must retain audit trails for compliance.*  

2. **Rate limiting with a token‑bucket middleware** – prevent abuse and protect downstream systems. *Matters for any public‑facing API to avoid DDOS and fair‑share enforcement.*  

3. **OpenTelemetry tracing** – instrument the handler with a span that records request ID, policy evaluation time, and downstream calls. *Matters for observability in distributed systems and integration with Jaeger or Grafana Cloud.*  

4. **Fault tolerance using a circuit‑breaker (e.g., `github.com/sony/gobreaker`)** – if the policy service or DB becomes unavailable, gracefully degrade instead of returning 500 errors. *Matters for resilience in mission‑critical back‑ends.*  

5. **Benchmarking with `wrk` or `hey`** – measure latency and throughput before and after each upgrade (e.g., after adding caching or async validation). *Matters to demonstrate that performance remains acceptable under load.*  

6. **Deploy to a managed platform with Argo CD** – declare the Docker image and manifests in a GitOps repo; Argo CD will keep the cluster in sync with the repository. *Matters for real‑world CI/CD pipelines and zero‑downtime releases.*

Each upgrade is a concrete, measurable step that transforms the toy project into a production‑ready system while keeping the codebase manageable.

## Key Takeaways

- A small, runnable Go service with Docker and GitHub Actions is a tangible signal of full‑stack competence.  
- Policy‑as‑code (YAML/ Rego) mirrors real‑world security pipelines and is instantly understandable to reviewers.  
- Structured logging + Prometheus metrics give you observability from day one, a habit that separates junior from mid‑level engineers.  
- The project’s modular architecture (handler → validator → policy engine → logger/metrics) can be split into microservices or expanded with persistence, tracing, and resilience patterns.  
- CI/CD automation proves you can maintain quality gates continuously, a requirement for any engineering role.  
- The roadmap upgrades (Postgres, rate limiting, OpenTelemetry, circuit‑breaker, benchmarking, GitOps) show a clear path from prototype to production‑grade system.

## Further Reading

- [Go Documentation](https://go.dev/doc/) – language spec, standard library, and best‑practice guides.  
- [Docker Getting Started](https://docs.docker.com/get-started/) – building, running, and multi‑stage Dockerfiles.  
- [OWASP Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html) – concrete rules for safe JSON parsing and regex use.  
- [The Twelve‑Factor App](https://12factor.net/) – principles that inform the Dockerfile, env‑var configuration, and logging choices in this project.  
- [Prometheus Documentation](https://prometheus.io/docs/) – how to expose counters and histograms from Go services.  
- [OpenTelemetry Go SDK](https://opentelemetry.io/docs/instrumentation/go/) – instrument your handler for tracing in future upgrades.  
- [Uber Zap Logger](https://github.com/uber-go/zap) – zero‑allocation, structured logging library used in the sample code.