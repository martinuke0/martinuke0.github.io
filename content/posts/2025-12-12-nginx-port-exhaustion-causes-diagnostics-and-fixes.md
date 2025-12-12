---
title: "Nginx Port Exhaustion: Causes, Diagnostics, and Fixes"
date: "2025-12-12T16:42:38.359"
draft: false
tags: ["nginx", "networking", "performance", "linux", "devops"]
---

## Introduction

Port exhaustion is a pernicious, often misunderstood failure mode that can bring a high-traffic Nginx deployment to its knees. The symptoms are intermittent and confusing—spiky 5xx error rates, “Cannot assign requested address” in logs, and upstream timeouts—yet the root cause is usually simple: you ran out of usable ephemeral ports for outbound connections.

In this article, we’ll explain what port exhaustion is and why Nginx is especially prone to it in reverse-proxy scenarios. We’ll cover how to diagnose it accurately, provide practical fixes at the Nginx and OS levels, and offer architectural strategies to prevent it from recurring. Whether you’re running bare metal, in containers, or behind a cloud NAT gateway, this guide will help you understand and solve Nginx port exhaustion.

## Table of contents

- [What is port exhaustion?](#what-is-port-exhaustion)
- [Why Nginx hits port exhaustion](#why-nginx-hits-port-exhaustion)
  - [Ephemeral ports and TIME_WAIT](#ephemeral-ports-and-time_wait)
  - [NAT gateways and SNAT](#nat-gateways-and-snat)
  - [Not to be confused with FD limits](#not-to-be-confused-with-fd-limits)
- [Common symptoms and error signatures](#common-symptoms-and-error-signatures)
- [When you’ll hit it: quick capacity math](#when-youll-hit-it-quick-capacity-math)
- [Diagnosing port exhaustion](#diagnosing-port-exhaustion)
- [Nginx-level fixes](#nginx-level-fixes)
  - [Enable and tune upstream keepalive](#enable-and-tune-upstream-keepalive)
  - [Avoid closing upstream connections](#avoid-closing-upstream-connections)
  - [Limit connection churn to each upstream](#limit-connection-churn-to-each-upstream)
- [OS and kernel tuning](#os-and-kernel-tuning)
  - [Expand the ephemeral port range](#expand-the-ephemeral-port-range)
  - [Reduce TIME_WAIT pressure](#reduce-time_wait-pressure)
  - [Reserve or exclude ports safely](#reserve-or-exclude-ports-safely)
  - [File descriptor limits (different problem)](#file-descriptor-limits-different-problem)
- [Architecture strategies](#architecture-strategies)
  - [Shard source IPs with proxy_bind](#shard-source-ips-with-proxy_bind)
  - [Reduce connection creation rate](#reduce-connection-creation-rate)
  - [Mind the NAT gateway or firewall](#mind-the-nat-gateway-or-firewall)
  - [Kubernetes-specific notes](#kubernetes-specific-notes)
- [Example configurations](#example-configurations)
- [Conclusion](#conclusion)
- [Resources](#resources)

## What is port exhaustion?

Every outbound TCP connection uses a local ephemeral port. The tuple that identifies a TCP connection is:

- source IP, source port, destination IP, destination port

For a given source IP, destination IP, and destination port, the kernel must allocate a unique local source port from the ephemeral range (e.g., 32768–60999 by default on many Linux systems). If you create outbound connections faster than ports are freed, or if many connections linger in TIME_WAIT, you can “run out” of unique local ports for that destination tuple. At that point, new connects fail with an error like EADDRNOTAVAIL (“Cannot assign requested address”).

## Why Nginx hits port exhaustion

As a reverse proxy, Nginx accepts client connections and creates outbound connections to upstream servers (app servers, APIs, caches). Each outbound connect consumes an ephemeral port on the Nginx host (or on the NAT device performing SNAT if one exists).

### Ephemeral ports and TIME_WAIT

- When Nginx closes a client-side or upstream-side TCP connection, one side (often the side that actively closes) enters TIME_WAIT to ensure delayed packets don’t corrupt a future connection. On Linux, TIME_WAIT typically lasts ~60 seconds.
- A socket in TIME_WAIT still ties up that local port for the same destination tuple. Heavy rates of short-lived connections to the same upstream cause a buildup of TIME_WAIT sockets, increasing the chance of port exhaustion.

> Note: TIME_WAIT is normal and necessary. The fix is to reduce connection churn or increase capacity, not to try to “eliminate” TIME_WAIT entirely.

### NAT gateways and SNAT

If your Nginx instance egresses through a NAT gateway or firewall that performs source NAT (SNAT), ephemeral port capacity may be enforced on the NAT device, not just your host. Cloud NATs (e.g., AWS NAT Gateway, GCP Cloud NAT, Azure NAT) track mappings of source ports. If the NAT saturates its per-IP or per-destination mapping capacity, connects fail upstream even if your host has free ports.

### Not to be confused with FD limits

Port exhaustion is different from running out of file descriptors (FDs). FD exhaustion yields errors like EMFILE (“Too many open files”) and shows up in Nginx as accept() failures or “(24: Too many open files)” in error logs. Port exhaustion yields “Cannot assign requested address” on connect().

You can have plenty of free FDs and still hit port exhaustion.

## Common symptoms and error signatures

- Nginx error log entries such as:
  - connect() to upstream 10.0.0.10:8080 failed (99: Cannot assign requested address) while connecting to upstream
  - upstream timed out (110: Connection timed out) while reading response header from upstream
- Spiky 502/504 error rates during traffic bursts
- Many sockets in TIME_WAIT toward a particular upstream:
  - ss -tan state time-wait | awk '{print $5}' | sort | uniq -c | sort -nr
- On NAT gateways, dropped or failed connections with similar EADDRNOTAVAIL behavior

## When you’ll hit it: quick capacity math

Consider a single Nginx source IP connecting to one upstream IP:port.

- Ephemeral range size (default example): 60999 − 32768 + 1 ≈ 28,232 ports
- TIME_WAIT ~ 60s

If each upstream request creates a new TCP connection and closes it, the approximate sustainable connect rate to that same upstream tuple is:

- 28,232 ports / 60 s ≈ 470 connects per second per source IP per destination tuple

In real life, jitter, retries, and partial reuse reduce this further. With multiple upstream servers or multiple source IPs, capacity increases linearly per distinct tuple.

The fastest and most effective relief: reuse connections (keepalive).

## Diagnosing port exhaustion

1. Check ephemeral port range:
   - cat /proc/sys/net/ipv4/ip_local_port_range
2. Observe TIME_WAIT and connection states:
   - ss -s
   - ss -tan state time-wait
   - ss -tan sport = :80 or filter by dst to a specific upstream
3. Look for EADDRNOTAVAIL errors in Nginx logs:
   - grep -E "Cannot assign requested address|EADDRNOTAVAIL" /var/log/nginx/error.log
4. Confirm not an FD limit issue:
   - ulimit -n
   - Check for “Too many open files” in logs
5. If behind NAT, inspect NAT mappings/counters:
   - conntrack -S (Linux hosts running conntrack)
   - Cloud NAT metrics (e.g., AWS NAT Gateway “Active Connections,” “Connection Attempts,” error counters)
6. Capture a short tcpdump to correlate failures:
   - sudo tcpdump -nn host <upstream_ip> and tcp port <port> -i eth0

> Tip: If errors cluster around one specific upstream IP:port, you’re likely exhausting that single tuple’s capacity. Sharding across more upstream IPs or source IPs helps immediately.

## Nginx-level fixes

### Enable and tune upstream keepalive

Upstream keepalive keeps a pool of idle TCP connections to upstream servers that can be reused, drastically reducing connection creation and TIME_WAIT churn.

Example (Nginx 1.15.3+ for per-upstream keepalive_* controls):

```nginx
http {
    upstream api_backend {
        zone api_backend 64k;            # share state across workers
        server 10.0.0.10:8080 max_fails=3 fail_timeout=10s;
        server 10.0.0.11:8080 max_fails=3 fail_timeout=10s;

        keepalive 512;                   # idle connections per worker
        keepalive_requests 1000;         # requests per connection before recycle
        keepalive_timeout 60s;           # idle timeout per connection
    }

    server {
        listen 80;

        location / {
            proxy_http_version 1.1;
            proxy_set_header Connection "";   # allow keepalive to upstream
            proxy_socket_keepalive on;        # enable TCP keepalive probes

            proxy_pass http://api_backend;
        }
    }
}
```

Key points:
- keepalive in upstream stores idle connections per worker process.
- proxy_http_version 1.1 plus clearing Connection prevents “Connection: close”.
- keepalive_requests and keepalive_timeout help balance reuse and periodic recycling.

### Avoid closing upstream connections

Ensure upstreams don’t force close:
- Some application servers add “Connection: close” or have low keepalive timeouts. Raise their keepalive timeout and request limits to match or exceed Nginx’s settings.
- Avoid adding hop-by-hop headers that disable keepalive.

### Limit connection churn to each upstream

- Balance traffic across multiple upstream IPs to increase tuple diversity.
- Avoid excessive health checks that open and close connections rapidly.
- Prefer fewer, longer-lived connections over many short ones, especially for chatty microservices.

> Note: Nginx open source does not multiplex multiple requests over a single upstream connection (HTTP/2 to upstream is not supported in the generic proxy module). Keepalive reuses connections serially. This is still a big win because most churn comes from creating and closing connections, not concurrency on a single connection.

## OS and kernel tuning

### Expand the ephemeral port range

A larger ephemeral range increases available ports and thus sustainable connect rates.

```bash
# View current range
cat /proc/sys/net/ipv4/ip_local_port_range

# Example tuning (persist in /etc/sysctl.conf as shown below)
sudo sysctl -w net.ipv4.ip_local_port_range="10000 65535"
```

Persist in /etc/sysctl.conf:

```bash
# /etc/sysctl.conf
net.ipv4.ip_local_port_range = 10000 65535
```

> Choose a range that does not overlap with well-known or application-reserved ports. If you must reserve ports, use ip_local_reserved_ports (below).

### Reduce TIME_WAIT pressure

Options to reduce TIME_WAIT impact on the client side:

- Lower tcp_fin_timeout conservatively to let connections clear faster:
  ```bash
  sudo sysctl -w net.ipv4.tcp_fin_timeout=15
  ```
- Consider enabling reuse of client-side TIME_WAIT sockets for new outgoing connections:
  ```bash
  # Allows reusing sockets in TIME_WAIT for new outgoing connections when safe
  sudo sysctl -w net.ipv4.tcp_tw_reuse=1
  ```
  Use with care and testing. This helps mainly when connecting to many different destinations over time. Do not enable tcp_tw_recycle (removed from modern kernels due to correctness issues).

- Ensure TCP timestamps are enabled (they are by default on modern kernels), which helps safe reuse logic.

> Caution: Over-aggressive tuning can introduce subtle networking issues. Test under production-like load before rollout.

### Reserve or exclude ports safely

If your host runs services that require specific port ranges, reserve them so the kernel won’t allocate them as ephemeral:

```bash
# Reserve ports 30000-30100 and 31000-31100
sudo sysctl -w net.ipv4.ip_local_reserved_ports="30000-30100,31000-31100"
```

Combine this with an expanded ephemeral range to avoid collisions.

### File descriptor limits (different problem)

Increase FD limits to avoid separate bottlenecks:

```bash
# Temporarily
ulimit -n 200000

# Systemd service override (recommended for Nginx)
# /etc/systemd/system/nginx.service.d/override.conf
[Service]
LimitNOFILE=200000
```

And align Nginx:
```nginx
worker_rlimit_nofile 200000;
events {
    worker_connections 65536;
}
```

Remember: FD tuning does not solve port exhaustion, but both limits often surface together under high load.

## Architecture strategies

### Shard source IPs with proxy_bind

Because ephemeral ports are counted per source IP, adding more source IPs increases capacity linearly. On a multi-homed host (or with multiple assigned IPs), you can direct Nginx to bind different upstream connections to different source IPs.

```nginx
http {
    upstream api_backend {
        zone api_backend 64k;
        server 10.0.0.10:8080;
        server 10.0.0.11:8080;
        keepalive 512;
    }

    map $uri $egress_ip {
        default          192.0.2.10;   # primary egress IP
        ~^/heavy-path    192.0.2.11;   # shard heavy traffic to a second IP
    }

    server {
        listen 80;

        location / {
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_bind $egress_ip;     # bind local source IP for upstream connects
            proxy_pass http://api_backend;
        }
    }
}
```

> If you egress through a NAT gateway, adding more public NAT IPs (elastic IPs) behind the gateway provides similar port scaling on the NAT.

### Reduce connection creation rate

- Enable client-side HTTP/2 and keepalive to reduce client-to-Nginx connection churn.
- Cache responses at Nginx where possible to avoid upstream calls.
- Batch, coalesce, or collapse duplicate requests with proxy_cache and cache locking.
- For gRPC, Nginx can proxy HTTP/2 to upstream (grpc/grpcs modules), allowing persistent streams.

### Mind the NAT gateway or firewall

- Monitor NAT connection tables and error counters.
- Scale NAT capacity with additional IPs or gateways if your connect rates approach per-IP limits.
- Adjust NAT timeouts to suit your traffic pattern (e.g., shorter for idle TCP flows, where safe).

### Kubernetes-specific notes

- In-cluster Nginx (Ingress controller) may SNAT via the node or CNI. Port exhaustion can occur on:
  - The Nginx pod’s node
  - The egress gateway/NAT
  - The upstream Service VIP or backends (if aggressively scaled)
- Watch conntrack table usage on nodes:
  - sysctl net.netfilter.nf_conntrack_max
  - conntrack -S
- Cluster NAT and Service topologies (externalTrafficPolicy, egress gateways) affect where exhaustion manifests.

## Example configurations

1) Minimal upstream keepalive for APIs:

```nginx
upstream api_backend {
    zone api_backend 64k;
    server 10.10.0.10:9000;
    server 10.10.0.11:9000;

    keepalive 256;
    keepalive_requests 2000;
    keepalive_timeout 75s;
}

server {
    listen 443 ssl http2;

    location /api/ {
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 30s;
        proxy_connect_timeout 2s;
        proxy_send_timeout 30s;
        proxy_socket_keepalive on;

        proxy_pass http://api_backend;
    }
}
```

2) OS sysctl tuning (persist in /etc/sysctl.conf):

```bash
# Increase ephemeral ports
net.ipv4.ip_local_port_range = 10000 65535

# Conservative TIME_WAIT pressure reduction
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1

# Optional: reserve non-ephemeral ports for other daemons
net.ipv4.ip_local_reserved_ports = 30000-30100,31000-31100
```

Apply:
```bash
sudo sysctl -p
```

3) Quick troubleshooting commands:

```bash
# Ephemeral range
cat /proc/sys/net/ipv4/ip_local_port_range

# Connection state summary
ss -s

# TIME_WAIT connections toward a suspect upstream
ss -tan state time-wait '( dport = :8080 )' | wc -l

# Look for EADDRNOTAVAIL in Nginx logs
grep -E "Cannot assign requested address|EADDRNOTAVAIL" /var/log/nginx/error.log

# NAT/conntrack stats (if applicable)
conntrack -S
```

4) Sharding source IPs using proxy_bind:

```nginx
map $request_uri $egress_ip {
    default 198.51.100.10;
    ~^/bulk 198.51.100.11;
}

server {
    listen 80;
    location / {
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_bind $egress_ip;
        proxy_pass http://api_backend;
    }
}
```

## Conclusion

Nginx port exhaustion arises when outbound connections to upstreams consume ephemeral ports faster than they can be freed—often amplified by TIME_WAIT accumulation, NAT constraints, and short-lived request patterns. The good news: it’s both diagnosable and fixable.

Focus your efforts on:
- Reusing upstream connections with keepalive
- Expanding ephemeral capacity and reducing TIME_WAIT pressure safely
- Sharding source IPs or scaling NAT resources when needed
- Reducing connection churn with caching and smarter request patterns

With these steps, you can turn “Cannot assign requested address” from a production fire into a non-event—and keep your reverse proxy humming under heavy load.

## Resources

- NGINX docs: Keepalive connections to upstream servers
  - https://nginx.org/en/docs/http/ngx_http_upstream_module.html#keepalive
- NGINX proxy module reference
  - https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- Linux ephemeral ports and sysctl tuning
  - ip_local_port_range: https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt
- TIME_WAIT and TCP behavior
  - RFC 793 (TCP), RFC 7323 (TCP Timestamps)
- NAT gateway port scaling (cloud)
  - AWS NAT Gateway quotas: https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html
  - GCP Cloud NAT capacity: https://cloud.google.com/nat/docs/overview
- conntrack basics
  - https://wiki.nftables.org/wiki-nftables/index.php/Conntrack_states

> Always validate kernel tunings and Nginx changes in a staging environment under load tests that approximate production traffic.