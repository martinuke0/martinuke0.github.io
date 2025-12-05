---
title: "HAProxy Zero to Hero: The Definitive In‑Depth Guide to High‑Performance Load Balancing"
date: "2025-12-05T02:43:00+02:00"
draft: false
tags: ["HAProxy", "Load Balancing", "DevOps", "High Availability", "Networking"]
---

## Introduction

HAProxy is the de facto open-source load balancer and reverse proxy for high-traffic websites, APIs, and microservices. It’s fast, battle-tested, extremely configurable, and equally at home terminating TLS, routing based on headers or paths, defending against abuse, or load balancing TCP streams.

This zero-to-hero guide takes you from first principles to production-ready configurations. We’ll cover installation, core concepts, practical configuration patterns, TLS, health checks, observability, advanced features like ACLs and stick tables, and safe reloads—with copy-and-pasteable examples.

> Note: This guide focuses on the open-source HAProxy. Many techniques also apply to HAProxy Enterprise, which adds advanced modules, official support, and tooling.

## Table of Contents

- [Core Concepts](#core-concepts)
- [Installation](#installation)
- [A Minimal, Production-Ready Skeleton](#a-minimal-production-ready-skeleton)
- [Logging and Observability Basics](#logging-and-observability-basics)
- [Load Balancing Algorithms](#load-balancing-algorithms)
- [Health Checks that Catch Real Problems](#health-checks-that-catch-real-problems)
- [Session Persistence (Sticky Sessions)](#session-persistence-sticky-sessions)
- [TLS Termination, HTTP/2, and Best Practices](#tls-termination-http2-and-best-practices)
- [Routing and ACLs (Content Switching)](#routing-and-acls-content-switching)
- [Rate Limiting, Abuse Prevention, and Security](#rate-limiting-abuse-prevention-and-security)
- [Zero-Downtime Reloads and the Runtime API](#zero-downtime-reloads-and-the-runtime-api)
- [Service Discovery with DNS and Server Templates](#service-discovery-with-dns-and-server-templates)
- [TCP Mode, PROXY Protocol, and Non-HTTP Workloads](#tcp-mode-proxy-protocol-and-non-http-workloads)
- [Performance Tuning Essentials](#performance-tuning-essentials)
- [Containers and Kubernetes](#containers-and-kubernetes)
- [Troubleshooting Checklist](#troubleshooting-checklist)
- [Conclusion](#conclusion)
- [Resources](#resources)

## Core Concepts

- L4 vs L7:
  - Layer 4 (mode tcp): load balance raw TCP streams (databases, TLS passthrough).
  - Layer 7 (mode http): understand HTTP semantics (headers, paths, methods), enabling routing, header rewriting, compression, and rate limiting.
- Process model:
  - Master-worker with multi-threading. The master process coordinates zero-downtime reloads; workers handle traffic. Configure threads via `nbthread`.
- Config structure:
  - `global` and `defaults` define overarching behavior.
  - `frontend` accepts connections and applies routing logic.
  - `backend` defines server pools and health checks.
  - `listen` is a combined frontend+backend block (handy for admin stats).

## Installation

On Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y haproxy
haproxy -v
```

On RHEL/CentOS/Rocky:

```bash
sudo dnf install -y haproxy
haproxy -v
```

With Docker:

```bash
docker run -d --name haproxy -p 80:80 -p 443:443 -v $PWD/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro haproxy:3.0
```

> Tip: Use recent HAProxy versions (2.6+ LTS or 3.x) for modern features like the built-in Prometheus exporter service and improved runtime APIs.

## A Minimal, Production-Ready Skeleton

Start with a clean, well-commented `haproxy.cfg`. This example balances HTTP traffic across two app servers, sets safe timeouts, includes TLS termination, and exposes an admin/metrics endpoint.

```ini
global
  log stdout format raw local0
  # Tune worker threads to number of cores or half for experimentation
  nbthread 4
  # Admin runtime socket (for draining, scaling, etc.)
  stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
  # Default TLS options
  ssl-default-bind-options no-sslv3 no-tls-tickets
  ssl-default-bind-ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256

defaults
  log     global
  mode    http
  option  httplog
  option  dontlognull
  option  http-server-close
  timeout connect 5s
  timeout client  30s
  timeout server  30s
  timeout http-request 10s
  retries 3

# Frontend: HTTP -> redirects to HTTPS
frontend fe_http
  bind *:80
  # Redirect everything to HTTPS
  http-request redirect scheme https code 301 unless { ssl_fc }
  default_backend bk_app

# Frontend: HTTPS termination with HTTP/2
frontend fe_https
  bind *:443 ssl crt /etc/haproxy/certs/example.pem alpn h2,http/1.1
  http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" if { ssl_fc }
  default_backend bk_app

backend bk_app
  balance roundrobin
  option httpchk GET /health
  http-check expect status 200
  server app1 10.0.0.11:8080 check
  server app2 10.0.0.12:8080 check

# Admin + Prometheus metrics
frontend fe_admin
  bind *:8404
  # Prometheus metrics at /metrics
  http-request use-service prometheus-exporter if { path /metrics }
  stats enable
  stats uri /stats
  stats refresh 10s
  stats auth admin:StrongPasswordHere
```

> Note: Place your PEM bundle at `/etc/haproxy/certs/example.pem` containing the certificate, private key, and intermediates.

Validate and start:

```bash
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
sudo systemctl enable --now haproxy
```

## Logging and Observability Basics

- Logging:
  - In containers, logging to stdout (as above) is simple.
  - On VMs, use syslog: in `global`, set `log 127.0.0.1 local0 notice` and configure rsyslog to accept and store HAProxy logs.
- Stats page:
  - The `fe_admin` shows live stats at `/stats` with basic auth. Keep it firewalled or private.
- Prometheus:
  - `http-request use-service prometheus-exporter` exposes `/metrics`. Scrape with Prometheus to power Grafana dashboards.
- Custom log format:
  ```ini
  defaults
    log-format "%ci:%cp -> %fi:%fp [%t] %ft %b/%s %TR/%Tw/%Tc/%Tr/%Ta %ST %B %tsc %ac/%fc/%bc/%sc/%rc %sq/%bq {%HM %HV %HU} {%hr} {%hs}"
  ```

## Load Balancing Algorithms

Common strategies:

- roundrobin (default): simple cycling.
- leastconn: sends new requests to the server with the fewest connections; great for long-lived requests.
- source: hashes the client IP to stick to the same server (basic persistence).

Example:

```ini
backend bk_app
  balance leastconn
  server app1 10.0.0.11:8080 check
  server app2 10.0.0.12:8080 check
```

You can weight servers to skew traffic:

```ini
server app1 10.0.0.11:8080 check weight 3
server app2 10.0.0.12:8080 check weight 1
```

## Health Checks that Catch Real Problems

Move beyond TCP checks to HTTP-level checks that hit a real endpoint. Ensure your `/health` exercises critical dependencies (DB, cache) and returns 200.

```ini
backend bk_app
  option httpchk GET /health
  http-check send meth GET uri /health ver HTTP/1.1 hdr Host www.example.com
  http-check expect rstatus 2xx
  server app1 10.0.0.11:8080 check inter 2s fall 3 rise 2
  server app2 10.0.0.12:8080 check inter 2s fall 3 rise 2
```

- `fall 3`: mark down after 3 failed checks.
- `rise 2`: mark up after 2 successes.
- `inter 2s`: 2-second check interval.

## Session Persistence (Sticky Sessions)

If your app stores session state in-memory, direct a client to the same server.

Option 1: Cookie-based persistence:

```ini
backend bk_app
  balance roundrobin
  cookie SRV insert indirect nocache
  server app1 10.0.0.11:8080 check cookie s1
  server app2 10.0.0.12:8080 check cookie s2
```

Option 2: Source IP stick-table:

```ini
backend bk_app
  balance roundrobin
  stick-table type ip size 200k expire 30m
  stick on src
  server app1 10.0.0.11:8080 check
  server app2 10.0.0.12:8080 check
```

> Prefer stateless sessions or external session stores for true scalability; use stickiness only when necessary.

## TLS Termination, HTTP/2, and Best Practices

- Terminate TLS at HAProxy:
  ```ini
  bind :443 ssl crt /etc/haproxy/certs/example.pem alpn h2,http/1.1
  ```
- Redirect HTTP to HTTPS:
  ```ini
  http-request redirect scheme https code 301 unless { ssl_fc }
  ```
- Harden TLS:
  - Disable legacy protocols (`no-sslv3`).
  - Favor modern ciphers, enable HTTP/2 via ALPN.
  - HSTS header for strict HTTPS.
- Let’s Encrypt:
  - Use an external ACME client (e.g., certbot, lego) to manage certificates and store them in `/etc/haproxy/certs/`.
  - Reload HAProxy after renewal (`systemctl reload haproxy`).
- TLS passthrough (no termination) for end-to-end encryption:
  ```ini
  frontend fe_tls_passthrough
    mode tcp
    bind :443
    tcp-request inspect-delay 5s
    tcp-request content accept if { req_ssl_hello_type 1 }
    use_backend bk_tls if { req_ssl_sni -i api.example.com }
    default_backend bk_tls

  backend bk_tls
    mode tcp
    balance source
    server s1 10.0.0.20:443 check
    server s2 10.0.0.21:443 check
  ```
  In passthrough, HAProxy can route by SNI but cannot inspect HTTP headers.

## Routing and ACLs (Content Switching)

ACLs (Access Control Lists) let you switch backends based on hostnames, paths, headers, methods, or GeoIP.

```ini
frontend fe_https
  bind :443 ssl crt /etc/haproxy/certs/example.pem alpn h2,http/1.1
  acl host_api  hdr(host) -i api.example.com
  acl host_www  hdr(host) -i www.example.com
  acl is_health path -i /health

  use_backend bk_api if host_api
  use_backend bk_www if host_www
  http-request return status 200 content-type text/plain lf-string "OK" if is_health
  default_backend bk_www

backend bk_api
  balance leastconn
  server api1 10.0.1.10:9000 check
  server api2 10.0.1.11:9000 check

backend bk_www
  balance roundrobin
  server web1 10.0.2.10:8080 check
  server web2 10.0.2.11:8080 check
```

Header manipulation and compression:

```ini
backend bk_www
  http-response set-header X-Frame-Options "SAMEORIGIN"
  http-response set-header X-Content-Type-Options "nosniff"
  http-response del-header Server
  compression algo gzip
  compression type text/html text/plain text/css application/javascript
```

## Rate Limiting, Abuse Prevention, and Security

Stick tables are HAProxy’s Swiss Army knife for tracking and acting on rates, errors, and abuse.

- Global request rate limiting (per IP):

```ini
frontend fe_https
  stick-table type ip size 1m expire 10m store http_req_rate(10s)
  http-request track-sc0 src
  acl too_fast sc_http_req_rate(0) gt 100
  http-request deny deny_status 429 if too_fast
  default_backend bk_app
```

- Protect login from brute force:

```ini
frontend fe_https
  acl is_login path_beg /login
  stick-table type ip size 200k expire 15m store gpc0,http_req_rate(30s)
  http-request track-sc0 src if is_login
  # Block if more than 10 login attempts in 30s
  acl abuse sc_http_req_rate(0) gt 10
  http-request deny if is_login abuse
```

- Basic auth for admin endpoints:

```ini
acl is_admin_path path_beg /admin
http-request auth realm "Restricted" if is_admin_path !{ http_auth(admin_users) }

userlist admin_users
  user admin insecure-password StrongPasswordHere
```

- Enforce allowed methods:

```ini
acl allowed_method method GET HEAD POST
http-request deny if !allowed_method
```

## Zero-Downtime Reloads and the Runtime API

Modern HAProxy supports seamless reloads: existing connections continue on old workers while new workers load the new config.

- Validate, then reload via systemd:
  ```bash
  sudo haproxy -c -f /etc/haproxy/haproxy.cfg
  sudo systemctl reload haproxy
  ```
- Or use the master process directly:
  ```bash
  sudo haproxy -sf $(cat /run/haproxy.pid) -f /etc/haproxy/haproxy.cfg
  ```
- Runtime API via stats socket (drain servers, change weights live):
  ```bash
  sudo socat - /run/haproxy/admin.sock <<< "show servers state"
  sudo socat - /run/haproxy/admin.sock <<< "set server bk_app/app2 state drain"
  sudo socat - /run/haproxy/admin.sock <<< "set server bk_app/app2 weight 0"
  ```

> Tip: Bake runtime actions into your deploy pipelines for safe, coordinated rollouts.

## Service Discovery with DNS and Server Templates

Dynamically discover backends via DNS SRV/A records.

```ini
resolvers dns
  nameserver google 8.8.8.8:53
  resolve_retries       3
  timeout retry         1s
  hold valid            10s

backend bk_app
  balance roundrobin
  option httpchk GET /health
  default-server check resolvers dns resolve-prefer ipv4 init-addr libc,none
  # Auto-create servers web1..web10 resolved from DNS pattern
  server-template web 1-10 websrv-%d.service.consul:8080
```

- `server-template` expands servers dynamically within a range as DNS answers change.
- Use a service registry (Consul, Kubernetes headless services, etc.) to update DNS.

## TCP Mode, PROXY Protocol, and Non-HTTP Workloads

For databases or raw TCP, switch to `mode tcp`.

- MySQL load balancing:

```ini
listen mysql
  mode tcp
  bind :3306
  balance roundrobin
  option mysql-check user haproxy_check
  server db1 10.0.3.10:3306 check
  server db2 10.0.3.11:3306 check
```

- PROXY protocol preserves client IP across layers:
  - If your backend (e.g., NGINX, Envoy, AWS NLB) expects PROXY, add `send-proxy`:
    ```ini
    server web1 10.0.2.10:8080 check send-proxy
    ```
  - If HAProxy receives from an upstream that sends PROXY, accept it:
    ```ini
    bind :80 accept-proxy
    ```

## Performance Tuning Essentials

- Concurrency:
  - `nbthread`: set to number of CPU cores or start with half and benchmark.
  - Pin threads to CPUs for cache locality:
    ```ini
    cpu-map auto:1/1-4 0-3
    ```
- Connection limits:
  - `maxconn` globally and per-proxy to guard memory and file descriptors:
    ```ini
    global
      maxconn 100000
    frontend fe_https
      maxconn 20000
    ```
- Buffers and HTTP reuse:
  - Defaults fit most workloads; change `tune.bufsize` cautiously and only after profiling.
  - Enable connection reuse to backends (default in modern versions) for better efficiency.
- Health check spreading:
  - `spread-checks 5` to randomize checks and avoid thundering herds.

> Always baseline with realistic traffic and incrementally tune. Over-tuning without evidence can reduce stability.

## Containers and Kubernetes

- Docker Compose example:

```yaml
version: "3.9"
services:
  haproxy:
    image: haproxy:3.0
    ports:
      - "80:80"
      - "443:443"
      - "8404:8404"
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
      - ./certs:/etc/haproxy/certs:ro
    ulimits:
      nofile: 200000
```

- Kubernetes:
  - Use the HAProxy Ingress Controller for K8s-native configuration via Ingress/CRDs.
  - For bare-metal K8s, pair with MetalLB and HAProxy Ingress for robust edge load balancing.

## Troubleshooting Checklist

- Validate configuration:
  ```bash
  haproxy -c -f /etc/haproxy/haproxy.cfg
  ```
- Inspect live state:
  ```bash
  echo "show stat" | socat - /run/haproxy/admin.sock | cut -d, -f1-10 | column -s, -t | less
  ```
- Watch logs:
  - If logging to syslog, tail `/var/log/haproxy.log` (distro-dependent).
  - If logging to stdout (containers), `docker logs -f haproxy`.
- Connectivity:
  - Check listeners: `ss -ltnp | grep haproxy`
  - Test routes/ACLs with `curl -I -H 'Host: api.example.com' https://LB/endpoint`
- Packet captures:
  ```bash
  sudo tcpdump -i any port 80 or port 443 -n
  ```
- Health checks:
  - Validate backend `/health` endpoint outputs correct status and is fast (<100ms ideal).

## Conclusion

HAProxy brings world-class load balancing, TLS termination, routing, and security controls to any environment, from single-node labs to global multi-region architectures. By mastering core concepts—frontends, backends, ACLs, health checks, and stick tables—you can build resilient, observable, and secure traffic layers. Add safe reloads, DNS-driven discovery, and thoughtful tuning, and you’ll have a platform that scales with confidence.

Whether you’re balancing a handful of services or a complex microservice mesh, HAProxy gives you the control and performance you need—with a mature ecosystem and a vibrant community to back it up.

## Resources

- HAProxy Official Site: https://www.haproxy.org/
- HAProxy Configuration Manual (versioned): https://docs.haproxy.org/
- HAProxy Blog (deep dives and best practices): https://www.haproxy.com/blog/
- HAProxy Community (Discourse): https://discourse.haproxy.org/
- HAProxy Data Plane API (automation): https://www.haproxy.com/documentation/hapee/latest/administration/dataplaneapi/
- Prometheus Exporter Service (docs): https://www.haproxy.com/blog/haproxy-exposes-a-prometheus-metrics-endpoint/
- HAProxy Ingress Controller for Kubernetes: https://github.com/haproxytech/kubernetes-ingress
- Performance Tuning Guide (community insights): https://www.haproxy.com/blog/tuning-haproxy-for-high-traffic/
- Keepalived (VRRP for virtual IP failover): https://keepalived.org/
- Let’s Encrypt / Certbot: https://certbot.eff.org/