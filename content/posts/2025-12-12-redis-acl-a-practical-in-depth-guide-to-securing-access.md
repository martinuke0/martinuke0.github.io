---
title: "Redis ACL: A Practical, In-Depth Guide to Securing Access"
date: "2025-12-12T23:04:07.281"
draft: false
tags: ["Redis", "Security", "ACL", "Authentication", "DevOps"]
---

## Introduction

Redis Access Control Lists (ACLs) let you define who can do what across commands, keys, and channels. Introduced in Redis 6 and expanded since, ACLs are now the standard way to secure multi-tenant applications, microservices, and administrative workflows without resorting to a single, global password.

In this guide, you’ll learn how Redis ACLs work, how to design least-privilege access for different use cases, how to manage ACLs safely in production (files, replication, rotation), and how to audit and test your permissions before you deploy.

> Note: TLS, firewalls, and network-level security remain essential. ACLs manage “what a client is allowed to do” once connected; they don’t encrypt traffic or replace perimeter security.

## Table of Contents

- What ACLs Are and Why They Matter
- Core ACL Concepts and Rules
  - Users and AUTH
  - Allowing and denying commands
  - Key patterns (~)
  - Pub/Sub channel patterns (&)
  - Passwords, hashing, and user flags
- Practical Examples
  - Read-only analytics user (key-restricted)
  - Microservice writer for a single namespace
  - Pub/Sub user confined to chat channels
  - Allow only safe subcommands (CONFIG GET)
  - Deny dangerous commands
- Managing ACLs at Scale
  - The ACL file (aclfile), save/load, and bootstrapping
  - Password generation and rotation
  - Replication and Redis Cluster considerations
- Auditing and Testing
  - Inspecting users and categories
  - Dry runs, logs, and client testing
- Patterns, Edge Cases, and Pitfalls
  - Glob matching for keys and channels
  - Movable keys and scripting
  - Modules and third-party commands
- Interoperability with Clients and Infrastructure
  - AUTH behavior and legacy clients
  - Replication and Sentinel users
  - Example redis.conf snippets
- Conclusion

## What ACLs Are and Why They Matter

Before Redis 6, Redis primarily used a single “requirepass” password. That model is too coarse for modern systems. ACLs provide:

- Multiple users, each with distinct permissions
- Fine-grained control over which commands can be run
- Key-level authorization via patterns (e.g., only keys matching app:*)
- Pub/Sub channel restrictions
- Auditing and testing tools to verify permissions

Result: You can apply least-privilege access per microservice or team, reduce blast radius, and deter accidental or malicious misuse of sensitive commands.

## Core ACL Concepts and Rules

### Users and AUTH

- Redis supports multiple users. Each connection authenticates as a user with AUTH.
- AUTH supports:
  - AUTH username password (preferred for ACLs)
  - AUTH password (legacy; authenticates as the “default” user)
- The “default” user exists out-of-the-box. By configuration, it may be enabled, disabled, or restricted.

Key commands:

- ACL SETUSER: create/modify a user
- ACL GETUSER: inspect a user
- ACL LIST / ACL USERS: list users and rules
- ACL DELUSER: delete users

### Allowing and Denying Commands

You control command permission with rules:

- allcommands / nocommands: allow or deny all commands (then refine)
- +<command>: allow a specific command (e.g., +get, +set)
- -<command>: explicitly deny a command
- +@<category> / -@<category>: allow/deny a category of commands
- +<command>|<subcommand>: allow only a subcommand (e.g., +config|get)

You can inspect available categories and their membership:

- ACL CAT: list categories
- ACL CAT <category>: list commands in that category

> Important: Use categories to allow broad families (e.g., data-structure or administrative areas), and then subtract risky commands (e.g., -@dangerous). Always verify with ACL CAT to see what you’re enabling.

### Key Patterns (~)

Redis ACLs let you scope access to specific keys using glob-style patterns:

- ~<pattern>: allow keys matching the pattern
- allkeys: allow access to any key
- resetkeys: remove all key-pattern allowances

Examples:
- ~app:* (all keys starting with app:)
- ~tenant:123:* (keys under a specific tenant)
- ~cache:???:* (exactly three characters after cache:)

> Note: Key patterns apply to top-level key names, not fields inside hashes or other structures.

### Pub/Sub Channel Patterns (&)

For channel access:

- &<pattern>: allow matching channels
- allchannels: allow any channel
- resetchannels: remove all channel-pattern allowances

Example:
- &chat:* allows publishing/subscribing only under chat:* channels.

### Passwords, Hashing, and User Flags

- >password: add a plaintext password (stored hashed internally)
- #<sha256>: add a SHA-256 hash of the password (to avoid storing plaintext in config)
- resetpass: remove all passwords
- on/off: enable/disable the user
- nopass: allow auth without a password (rarely recommended)

> Best practice: Avoid “nopass” except in tightly controlled scenarios. Prefer adding password hashes via #<sha256> in the ACL file.

## Practical Examples

All examples use redis-cli. Replace values as needed.

### 1) Read-only analytics user (key-restricted)

Goal: Allow read-only queries on orders:* and customers:* data. Deny dangerous commands by default.

We’ll explicitly allow a curated set of common read commands. Tailor this list to your app.

```bash
# Create user 'analytics' with a strong password and key restrictions
ACL SETUSER analytics on >S3cure-Analytics-Password `
  resetkeys ~orders:* ~customers:* `
  nocommands `
  +get +mget +strlen +getrange `
  +exists +ttl +pttl +type `
  +scan +sscan +hscan +zscan `
  +hget +hmget +hgetall +hlen +hexists +hkeys +hvals `
  +zrange +zrevrange +zrank +zrevrank +zscore +zcard `
  +smembers +sismember +scard `
  -@dangerous
```

> Tip: If you need to add another read command later (e.g., STRLEN), append it with +strlen. Strict allow-lists are safer than broad categories for read-only users.

### 2) Microservice writer for a single namespace

Goal: A “cart-service” can write only to keys cart:* and use a minimal command set.

```bash
ACL SETUSER cart-service on >Ch@ng3Me-Cart `
  resetkeys ~cart:* `
  nocommands `
  +set +setex +psetex +incr +incrby +decr +decrby `
  +hset +hsetnx +hincrby +hincrbyfloat `
  +expire +pexpire +persist +del `
  -@dangerous
```

Consider also allowing +get for read-your-writes behavior:

```bash
ACL SETUSER cart-service +get +mget
```

### 3) Pub/Sub user confined to chat channels

Goal: “chat-user” can only publish/subscribe to chat:* channels.

```bash
ACL SETUSER chat-user on >Sup3rCh@t `
  resetchannels &chat:* `
  nocommands `
  +publish +subscribe +psubscribe +unsubscribe +punsubscribe `
  -@dangerous
```

> Note: Channel pattern checks apply to PUBLISH and to subscription commands. If you have multiple channel namespaces, add multiple &patterns.

### 4) Allow only safe subcommands (CONFIG GET)

Some administrative actions are read-only and safe to expose, others are not. You can allow only a subcommand:

```bash
# 'ops-ro' can read config but not set it
ACL SETUSER ops-ro on >OpsObserv3r `
  nocommands +info +command `
  +config|get `
  -@dangerous
```

This allows CONFIG GET while keeping CONFIG SET/RESETSTAT blocked.

### 5) Deny dangerous commands

Even for broad-privilege users, block risky operations:

```bash
# 'poweruser' gets broad access except dangerous commands
ACL SETUSER poweruser on >Pow3rUs3r `
  allkeys allcommands `
  -@dangerous
```

Commonly blocked “dangerous” commands include FLUSHALL/FLUSHDB, SHUTDOWN, and certain DEBUG/KEYS operations.

## Managing ACLs at Scale

### The ACL file (aclfile), save/load, and bootstrapping

Use an ACL file to manage users declaratively and ensure consistent state on restart.

redis.conf:

```ini
aclfile /etc/redis/users.acl
```

Example /etc/redis/users.acl:

```txt
# Default user: require password, allow all keys/commands except dangerous
user default on #3f1d...sha256hash... allkeys allcommands -@dangerous

# Read-only analytics
user analytics on #1a2b...sha256hash... resetkeys ~orders:* ~customers:* nocommands \
  +get +mget +strlen +getrange \
  +exists +ttl +pttl +type \
  +scan +sscan +hscan +zscan \
  +hget +hmget +hgetall +hlen +hexists +hkeys +hvals \
  +zrange +zrevrange +zrank +zrevrank +zscore +zcard \
  +smembers +sismember +scard -@dangerous

# Cart service
user cart-service on #4d5e...sha256hash... resetkeys ~cart:* nocommands \
  +set +setex +psetex +incr +incrby +decr +decrby \
  +hset +hsetnx +hincrby +hincrbyfloat \
  +expire +pexpire +persist +del +get +mget -@dangerous
```

Operational commands:

- ACL LOAD: reload from aclfile
- ACL SAVE: persist in-memory ACL changes to aclfile

> Recommendation: Treat the ACL file as configuration-as-code. Manage it via your usual change control and CI/CD, but avoid storing plaintext passwords. Prefer #<sha256> entries.

### Password generation and rotation

- Generate strong, random secrets:
  - ACL GENPASS [bits] returns a cryptographically strong password.
- Rotate without downtime:
  1) Add the new password alongside the old one:
     - ACL SETUSER alice >new-secret
  2) Update clients to use the new secret.
  3) Remove the old password:
     - ACL SETUSER alice resetpass >new-secret
- If you use hashes in the ACL file, pre-hash client secrets with SHA-256 and add via #<sha256>.

### Replication and Redis Cluster considerations

- Replication: ACL changes propagate from the primary to replicas automatically. Ensure replicas load the same aclfile on restart or rely on ACL SAVE from the primary before restarts.
- Cluster: Each node maintains its own ACLs. Apply ACL changes to all masters (and replicas follow their masters). Use automation to keep them consistent.
- Backups and restores: Ensure the ACL file is backed up alongside RDB/AOF where appropriate. ACLs are not stored inside RDB/AOF.

## Auditing and Testing

### Inspecting users and categories

```bash
ACL USERS          # list usernames
ACL LIST           # list users with rules
ACL GETUSER alice  # detailed view for a specific user
ACL CAT            # list categories
ACL CAT string     # list commands in the "string" category
```

### Dry runs, logs, and client testing

- ACL DRYRUN user <raw-command...>: test whether a command would be allowed for a given user without executing it.

```bash
ACL DRYRUN analytics "SET orders:1 foo"
# => DENIED: ... (explanation)
ACL DRYRUN analytics "GET orders:1"
# => ALLOWED
```

- ACL LOG: inspect recent ACL violations and clear the log.
```bash
ACL LOG            # recent denials
ACL LOG RESET      # clear log
```

- Test with redis-cli as the target user:
```bash
redis-cli -u redis://host:6379 --user analytics --pass 'S3cure-Analytics-Password' GET orders:1
```

> Tip: Integrate ACL DRYRUN into pre-deploy checks for applications that change command usage over time.

## Patterns, Edge Cases, and Pitfalls

### Glob matching for keys and channels

- Patterns use Redis-style globbing:
  - * matches any sequence, ? matches one character, [] for ranges/classes.
- Patterns match the entire key name. Design predictable prefixes (like tenant:123:*) to make authorization straightforward.
- Multi-tenant pitfalls:
  - Avoid overly broad patterns like ~*: they defeat least privilege.
  - Be explicit: ~tenant:123:* instead of ~tenant:* if tenants must be isolated.

### Movable keys and scripting

- Some commands can access keys indirectly (e.g., via scripts). If you allow scripting (EVAL/EVALSHA), ensure you trust the code path and test with ACL DRYRUN; better yet, restrict or disallow scripting for untrusted users:
```bash
ACL SETUSER app -@scripting
```
- Prefer SCAN over KEYS. KEYS is typically considered dangerous due to performance characteristics and is commonly blocked via -@dangerous.

### Modules and third-party commands

- Commands introduced by modules must be explicitly allowed. Inspect them with ACL CAT and allow by full command name (e.g., +bf.add for Bloom filter add) or by relevant categories exposed by the module.
- Always review module documentation for ACL integration and recommended rules.

## Interoperability with Clients and Infrastructure

### AUTH behavior and legacy clients

- New style: AUTH username password
- Legacy style: AUTH password authenticates as the “default” user. When migrating, ensure the default user’s rules are compatible with legacy clients or update clients to use user-specific auth.

### Replication and Sentinel users

- Replication:
  - Configure the replica to authenticate to the primary with a dedicated replication user.
  - In redis.conf:
    - masteruser repl-user
    - masterauth repl-password
  - Create the user on the primary with only the permissions necessary for replication. Typically, replication requires administrative and data access; consult your version’s docs and keep least privilege in mind.
- Redis Sentinel:
  - Sentinel itself can authenticate to Redis using a user and password (e.g., sentinel auth-user, auth-pass in sentinel.conf or corresponding env/flags).
  - Create a sentinel-specific user with only the needed permissions to monitor and issue failover commands.

### Example redis.conf snippets

```ini
# Use ACL file for declarative user management
aclfile /etc/redis/users.acl

# Replication auth (replica authenticates to primary)
masteruser repl-user
masterauth repl-password

# TLS, bind, and protected-mode are separate concerns but recommended
# tls-port 6379
# tls-cert-file /etc/ssl/redis.crt
# tls-key-file /etc/ssl/redis.key
# bind 10.0.0.5
# protected-mode yes
```

> Reminder: ACLs do not replace TLS. Use TLS for encryption in transit, and firewall rules/VPC security groups to limit network access.

## Conclusion

Redis ACLs let you replace one-size-fits-all passwords with precise, auditable permissions. By defining users per service or persona, restricting keys and channels with clear prefixes, removing dangerous commands, and validating with ACL DRYRUN and ACL LOG, you enforce least privilege without sacrificing developer velocity.

Adopt an ACL file under change control, rotate credentials safely, propagate changes through replication and cluster automation, and continually test as your application evolves. With these practices, Redis becomes a safer foundation for both production workloads and multi-tenant architectures.