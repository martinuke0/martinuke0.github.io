---
title: "Understanding Refresh Tokens: Theory, Implementation, and Security Best Practices"
date: "2026-04-01T13:34:12.233"
draft: false
tags: ["authentication","oauth2","security","jwt","api"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Access Tokens vs. Refresh Tokens: Why the Split?](#access-tokens-vs-refresh-tokens-why-the-split)  
3. [OAuth 2.0 Grant Types that Use Refresh Tokens](#oauth-20-grant-types-that-use-refresh-tokens)  
4. [Refresh Token Formats: Opaque vs. JWT](#refresh-token-formats-opaque-vs-jwt)  
5. [Secure Storage on the Client](#secure-storage-on-the-client)  
6. [Token Rotation, Revocation, and Blacklisting](#token-rotation-revocation-and-blacklisting)  
7. [Implementing the Refresh Flow – Node.js/Express Example](#implementing-the-refresh-flow---nodejsexpress-example)  
8. [Implementing the Refresh Flow – Python/Flask Example](#implementing-the-refresh-flow---pythonflask-example)  
9. [Implementing the Refresh Flow – Java/Spring Security Example](#implementing-the-refresh-flow---javaspring-security-example)  
10. [Common Pitfalls and How to Avoid Them](#common-pitfalls-and-how-to-avoid-them)  
11. [Advanced Patterns: Sliding Sessions & Device Binding](#advanced-patterns-sliding-sessions--device-binding)  
12. [Real‑World Case Studies](#real-world-case-studies)  
13. [Monitoring, Auditing, and Incident Response](#monitoring-auditing-and-incident-response)  
14. [Conclusion](#conclusion)  
15. [Resources](#resources)  

---

## Introduction

In modern web and mobile ecosystems, **stateless authentication** has become the de‑facto standard. Instead of keeping a server‑side session for each user, services hand out cryptographically signed tokens—most commonly JSON Web Tokens (JWTs)—that the client presents on each request. This model scales effortlessly, works across domains, and fits naturally with micro‑service architectures.

However, short‑lived access tokens have a drawback: once they expire, the client must obtain a new one. If the client had to ask the user to re‑authenticate every few minutes, the user experience would be terrible. The answer is the **refresh token**. A refresh token is a credential that can be exchanged for a fresh access token without requiring the user’s credentials again.

This article dives deep into the **what**, **how**, and **why** of refresh tokens. We’ll explore the OAuth 2.0 specification, compare token formats, discuss secure storage on different platforms, walk through concrete implementations in three popular stacks, and outline the security best practices that keep refresh tokens from becoming an attack vector.

> **Note:** While the concepts apply to any token‑based system, the examples focus on OAuth 2.0 because it is the most widely adopted framework for issuing and refreshing tokens.

---

## Access Tokens vs. Refresh Tokens: Why the Split?

| Aspect | Access Token | Refresh Token |
|--------|--------------|---------------|
| **Purpose** | Authorize API calls (resource server) | Obtain new access tokens |
| **Typical Lifetime** | Minutes (5‑15 min) | Days, weeks, or indefinite |
| **Visibility** | Sent on every request (Authorization header) | Sent only to the token endpoint |
| **Format** | Often JWT (self‑contained) | Usually opaque, sometimes JWT |
| **Revocation** | Hard to revoke without a blacklist | Revoked via server‑side store |
| **Security Impact if Stolen** | Allows immediate API access until expiration | Enables long‑term token abuse (if not rotated) |

### The Security Rationale

1. **Minimize Exposure:** Access tokens travel over the wire with every API call. Keeping their lifespan short reduces the window an attacker can exploit if they intercept a token.
2. **Separation of Duties:** The client never needs to store the user’s password after the initial authentication. The refresh token, which is more powerful, stays out of the request path.
3. **Scalable Revocation:** Because refresh tokens are stored server‑side (or are short‑lived JWTs with revocation lists), a compromised token can be invalidated without affecting other users.

### Flow Overview

1. **User authenticates** (e.g., via Authorization Code flow).  
2. **Authorization server** issues an **access token** (short‑lived) **and a refresh token** (long‑lived).  
3. **Client** uses the access token for API calls.  
4. When the access token expires, the client **POSTs the refresh token** to the token endpoint.  
5. The server validates the refresh token, issues a **new access token** (and optionally a **new refresh token**).  

---

## OAuth 2.0 Grant Types that Use Refresh Tokens

While the **Authorization Code** grant is the most common, several other grant types also support refresh tokens:

| Grant Type | Typical Use‑Case | Refresh Token Support |
|------------|------------------|-----------------------|
| **Authorization Code** | Web apps, mobile apps (with PKCE) | ✅ |
| **Resource Owner Password Credentials** (ROPC) | Legacy apps where user credentials are directly collected | ✅ (but discouraged) |
| **Client Credentials** | Machine‑to‑machine communication (no user) | ❌ (no refresh token) |
| **Device Authorization** | TVs, IoT devices with limited UI | ✅ (via device flow) |
| **Refresh Token** (dedicated) | Used to exchange a refresh token for a new access token | ✅ (obviously) |

The **Authorization Code** flow with **PKCE** (Proof Key for Code Exchange) is now the recommended approach for public clients (mobile, SPA) because it mitigates interception attacks.

### Spec Reference

The OAuth 2.0 RFC 6749 §6 defines the refresh token grant. It states:

> *The client makes a request to the token endpoint using the grant_type parameter set to "refresh_token". The request includes the refresh token and, if applicable, the client credentials.*

---

## Refresh Token Formats: Opaque vs. JWT

### Opaque Refresh Tokens

* **Definition:** A random string with no intrinsic meaning to the client (e.g., `9b2a5c3e-1f4d-4a6c-9fdd-2e6f7c1d4baf`).  
* **Pros:**  
  * Simpler server‑side revocation (lookup in DB).  
  * No risk of client‑side token tampering because the token cannot be parsed.  
* **Cons:**  
  * Requires a database lookup on every token refresh, adding latency.  
  * Larger storage footprint if many tokens are issued.

### JWT Refresh Tokens

* **Definition:** A JSON Web Token, typically signed with HS256 or RS256, containing claims such as `sub`, `iat`, `exp`, and optionally a `jti` (JWT ID).  
* **Pros:**  
  * Stateless verification (no DB hit) if you trust the signature and expiration.  
  * Can embed additional context (device ID, scope) useful for fine‑grained policies.  
* **Cons:**  
  * Revocation is harder; you need a blacklist or short expiration plus rotation.  
  * Larger payload (base64url encoded) may increase network overhead.

### Choosing Between Them

| Situation | Recommended Format |
|-----------|--------------------|
| **High security, frequent revocation** (e.g., banking) | Opaque + DB storage |
| **Performance‑critical, low‑risk** (e.g., internal API) | JWT with short `exp` and rotation |
| **Multi‑tenant SaaS with per‑tenant key management** | Opaque (allows per‑tenant key rotation without re‑issuing JWTs) |

---

## Secure Storage on the Client

How you store a refresh token depends heavily on the client platform.

### 1. Native Mobile Apps (iOS/Android)

| Platform | Recommended Store | Rationale |
|---------|-------------------|-----------|
| **iOS** | Keychain Services | Encrypted, hardware‑backed, survives app reinstalls (optional). |
| **Android** | EncryptedSharedPreferences or Android Keystore | Prevents extraction via root or debugging tools. |

**Example (iOS – Swift):**

```swift
import Security

func storeRefreshToken(_ token: String) {
    let data = token.data(using: .utf8)!
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrAccount as String: "refresh_token",
        kSecValueData as String: data,
        kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    ]
    SecItemAdd(query as CFDictionary, nil)
}
```

### 2. Single‑Page Applications (SPA)

* **Avoid storing refresh tokens in the browser altogether.**  
* Use the **Authorization Code with PKCE** flow where the server issues **short‑lived access tokens** and **no refresh token** to the SPA. Instead, the SPA silently obtains a new access token via an **iframe** or **silent refresh** using the **Authorization Server’s session**.  

If a refresh token *must* be stored (rare), place it in **httpOnly, Secure, SameSite=Strict** cookies. This prevents JavaScript access and mitigates XSS.

### 3. Server‑Side Web Apps

* Store refresh tokens in a **server‑side session store** (e.g., Redis, database).  
* Keep them out of the client entirely; the client only receives a session cookie.

### 4. Desktop Applications

* Use OS‑specific secure storage: Windows Credential Locker, macOS Keychain, or Linux’s Secret Service (e.g., libsecret).  

### Threat Model Summary

| Threat | Mitigation |
|-------|------------|
| **XSS** (client‑side script reads token) | Store in httpOnly cookie or OS keychain; avoid localStorage. |
| **Man‑in‑the‑Middle (MITM)** | Enforce TLS everywhere; use PKCE for public clients. |
| **Token leakage via logs** | Never log full token strings; mask them (`****`). |
| **Device theft** | Bind refresh token to device ID; rotate on each use. |

---

## Token Rotation, Revocation, and Blacklisting

### Why Rotate?

If a refresh token is stolen, an attacker could keep exchanging it for new access tokens forever. **Refresh token rotation** mitigates this by issuing a *new* refresh token every time the client uses the old one. The server invalidates the old token immediately after a successful exchange.

### Rotation Flow

1. Client sends **old refresh token** to token endpoint.  
2. Server validates it, issues **new access token** **and** **new refresh token**.  
3. Server stores the new refresh token and marks the old one as **revoked** (or deletes it).  
4. If the old token is used again (perhaps because the attacker intercepted it before rotation), the server detects that it’s revoked and rejects the request.

### Revocation Strategies

1. **Database Flag** – Each opaque token has a `revoked` boolean column.  
2. **Blacklist Cache** – Store revoked JWT IDs (`jti`) in Redis with a TTL equal to the token’s original expiration.  
3. **Sliding Expiration** – Combine rotation with a sliding window; tokens automatically become unusable after a period of inactivity.  

### Implementation Tip (Node.js + Redis)

```js
// revoke token
await redis.set(`revoked:${jti}`, 'true', 'EX', tokenExpirySeconds);

// middleware to check revocation
app.use(async (req, res, next) => {
  const token = extractAccessToken(req);
  const { jti } = jwt.decode(token);
  const revoked = await redis.get(`revoked:${jti}`);
  if (revoked) return res.status(401).json({ error: 'token_revoked' });
  next();
});
```

---

## Implementing the Refresh Flow — Node.js/Express Example

Below is a minimal, production‑ready implementation using **express**, **jsonwebtoken**, and **sequelize** (PostgreSQL) for opaque refresh tokens.

### Project Structure

```
/src
  ├─ app.js
  ├─ routes/
  │    └─ auth.js
  ├─ models/
  │    └─ RefreshToken.js
  └─ utils/
       ├─ token.js
       └─ crypto.js
```

### 1. Model (`models/RefreshToken.js`)

```js
const { Model, DataTypes } = require('sequelize');
module.exports = (sequelize) => {
  class RefreshToken extends Model {}
  RefreshToken.init({
    token: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    userId: { type: DataTypes.INTEGER, allowNull: false },
    expiresAt: { type: DataTypes.DATE, allowNull: false },
    revoked: { type: DataTypes.BOOLEAN, defaultValue: false },
    createdAt: DataTypes.DATE,
    updatedAt: DataTypes.DATE,
  }, { sequelize, modelName: 'RefreshToken' });
  return RefreshToken;
};
```

### 2. Token Utilities (`utils/token.js`)

```js
const jwt = require('jsonwebtoken');
const config = require('../config');

function signAccessToken(user) {
  return jwt.sign(
    { sub: user.id, name: user.name, role: user.role },
    config.accessTokenSecret,
    { expiresIn: '10m' } // short-lived
  );
}

module.exports = { signAccessToken };
```

### 3. Auth Routes (`routes/auth.js`)

```js
const express = require('express');
const router = express.Router();
const { signAccessToken } = require('../utils/token');
const { RefreshToken } = require('../models');
const { Op } = require('sequelize');

// -------------------------------------------------
// 1️⃣ Login – issue both tokens
// -------------------------------------------------
router.post('/login', async (req, res) => {
  const { username, password } = req.body;
  const user = await authenticate(username, password); // implement your own
  if (!user) return res.status(401).json({ error: 'invalid_credentials' });

  const accessToken = signAccessToken(user);
  const refresh = await RefreshToken.create({
    userId: user.id,
    expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000), // 30 days
  });

  res.json({ accessToken, refreshToken: refresh.token });
});

// -------------------------------------------------
// 2️⃣ Refresh – rotate token
// -------------------------------------------------
router.post('/token', async (req, res) => {
  const { refreshToken } = req.body;
  if (!refreshToken) return res.status(400).json({ error: 'missing_token' });

  const stored = await RefreshToken.findOne({
    where: {
      token: refreshToken,
      expiresAt: { [Op.gt]: new Date() },
      revoked: false,
    },
  });

  if (!stored) return res.status(401).json({ error: 'invalid_refresh' });

  // Rotate: revoke old token
  stored.revoked = true;
  await stored.save();

  // Issue new tokens
  const user = await getUserById(stored.userId);
  const newAccess = signAccessToken(user);
  const newRefresh = await RefreshToken.create({
    userId: user.id,
    expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000),
  });

  res.json({
    accessToken: newAccess,
    refreshToken: newRefresh.token,
  });
});

module.exports = router;
```

### 4. Middleware to Protect Resources (`utils/authMiddleware.js`)

```js
const jwt = require('jsonwebtoken');
const config = require('../config');

function authenticateAccessToken(req, res, next) {
  const auth = req.headers.authorization;
  if (!auth?.startsWith('Bearer ')) return res.sendStatus(401);
  const token = auth.slice(7);
  try {
    const payload = jwt.verify(token, config.accessTokenSecret);
    req.user = payload;
    next();
  } catch (e) {
    return res.sendStatus(401);
  }
}

module.exports = { authenticateAccessToken };
```

### 5. Running the App

```bash
npm install express sequelize pg pg-hstore jsonwebtoken
node src/app.js
```

**Key takeaways from the code:**

* Refresh tokens are **opaque UUIDs** stored in a relational DB.
* On each refresh, the old token is **revoked** and a new one issued (rotation).
* Access tokens are **JWTs** with a short TTL, verified without DB lookups.
* All interactions happen over **HTTPS** (enforced at the infrastructure level).

---

## Implementing the Refresh Flow — Python/Flask Example

Flask paired with **SQLAlchemy** and **PyJWT** can replicate the same pattern. We'll also demonstrate a **JWT refresh token** variant for contrast.

### 1. Setup

```bash
pip install Flask Flask-SQLAlchemy PyJWT python-dotenv
```

### 2. Application (`app.py`)

```python
import os, uuid, datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import jwt

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tokens.db'
app.config['ACCESS_SECRET'] = os.getenv('ACCESS_SECRET', 'access-secret')
app.config['REFRESH_SECRET'] = os.getenv('REFRESH_SECRET', 'refresh-secret')
db = SQLAlchemy(app)

# -------------------------------------------------
# Model for opaque refresh tokens
# -------------------------------------------------
class RefreshToken(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, default=False)

# -------------------------------------------------
# Helper: create access JWT
# -------------------------------------------------
def create_access_token(user_id):
    payload = {
        'sub': user_id,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    }
    return jwt.encode(payload, app.config['ACCESS_SECRET'], algorithm='HS256')

# -------------------------------------------------
# Helper: create JWT refresh token (optional)
# -------------------------------------------------
def create_jwt_refresh_token(user_id):
    payload = {
        'sub': user_id,
        'jti': str(uuid.uuid4()),
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=30)
    }
    return jwt.encode(payload, app.config['REFRESH_SECRET'], algorithm='HS256')

# -------------------------------------------------
# Login endpoint – issues both tokens
# -------------------------------------------------
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username, password = data.get('username'), data.get('password')
    # Dummy auth – replace with real DB check
    if username != 'alice' or password != 'wonderland':
        return jsonify({'error': 'invalid_credentials'}), 401

    user_id = 1  # static for demo
    access = create_access_token(user_id)

    # Choose opaque or JWT refresh token
    # opaque:
    rt = RefreshToken(user_id=user_id,
                     expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=30))
    db.session.add(rt)
    db.session.commit()
    refresh = rt.id

    # # JWT variant:
    # refresh = create_jwt_refresh_token(user_id)

    return jsonify({'access_token': access, 'refresh_token': refresh})

# -------------------------------------------------
# Refresh endpoint – handles rotation
# -------------------------------------------------
@app.route('/refresh', methods=['POST'])
def refresh():
    data = request.json
    token = data.get('refresh_token')
    if not token:
        return jsonify({'error': 'missing_token'}), 400

    # Opaque token path
    rt = RefreshToken.query.filter_by(id=token, revoked=False).first()
    if not rt or rt.expires_at < datetime.datetime.utcnow():
        return jsonify({'error': 'invalid_refresh'}), 401

    # Rotate
    rt.revoked = True
    db.session.add(rt)

    # Issue new tokens
    user_id = rt.user_id
    new_access = create_access_token(user_id)
    new_rt = RefreshToken(user_id=user_id,
                          expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=30))
    db.session.add(new_rt)
    db.session.commit()

    return jsonify({'access_token': new_access, 'refresh_token': new_rt.id})

# -------------------------------------------------
# Protected resource example
# -------------------------------------------------
@app.route('/profile')
def profile():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({'error': 'token_missing'}), 401
    token = auth.split()[1]
    try:
        payload = jwt.decode(token, app.config['ACCESS_SECRET'], algorithms=['HS256'])
        return jsonify({'user_id': payload['sub'], 'msg': 'Hello!'})
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'token_expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'invalid_token'}), 401

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True)
```

### Highlights

* The same **rotation** logic is applied to the opaque refresh token.
* Commented section shows how to switch to a **JWT refresh token** if you prefer stateless verification.
* The `profile` endpoint demonstrates **access token validation**.

---

## Implementing the Refresh Flow — Java/Spring Security Example

Spring Security 5+ ships with first‑class support for OAuth 2.0 Resource Server and Client. Below is a concise configuration that uses **opaque refresh tokens stored in a JPA repository**.

### 1. Maven Dependencies

```xml
<dependencies>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-security</artifactId>
    </dependency>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
        <groupId>org.springframework.security</groupId>
        <artifactId>spring-security-oauth2-authorization-server</artifactId>
        <version>0.4.0</version>
    </dependency>
    <dependency>
        <groupId>com.nimbusds</groupId>
        <artifactId>nimbus-jose-jwt</artifactId>
    </dependency>
    <!-- H2 for demo -->
    <dependency>
        <groupId>com.h2database</groupId>
        <artifactId>h2</artifactId>
        <scope>runtime</scope>
    </dependency>
</dependencies>
```

### 2. Entity (`RefreshToken.java`)

```java
@Entity
@Table(name = "refresh_tokens")
public class RefreshToken {
    @Id
    private String token; // UUID string

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false)
    private Instant expiresAt;

    @Column(nullable = false)
    private boolean revoked = false;

    // getters & setters omitted for brevity
}
```

### 3. Repository

```java
public interface RefreshTokenRepository extends JpaRepository<RefreshToken, String> {
    Optional<RefreshToken> findByTokenAndRevokedFalseAndExpiresAtAfter(String token, Instant now);
}
```

### 4. Security Configuration

```java
@EnableWebSecurity
public class SecurityConfig extends WebSecurityConfigurerAdapter {

    @Value("${jwt.access.secret}")
    private String accessSecret;

    @Autowired
    private RefreshTokenRepository refreshRepo;

    @Override
    protected void configure(HttpSecurity http) throws Exception {
        http
            .csrf().disable()
            .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS)
            .and()
            .authorizeRequests()
                .antMatchers("/login", "/token").permitAll()
                .anyRequest().authenticated()
            .and()
            .addFilterBefore(new JwtAuthenticationFilter(accessSecret), UsernamePasswordAuthenticationFilter.class);
    }

    // ---- AuthenticationManager bean for /login endpoint ----
    @Bean
    @Override
    public AuthenticationManager authenticationManagerBean() throws Exception {
        return super.authenticationManagerBean();
    }
}
```

### 5. JWT Filter (`JwtAuthenticationFilter.java`)

```java
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final String secret;

    public JwtAuthenticationFilter(String secret) {
        this.secret = secret;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (header != null && header.startsWith("Bearer ")) {
            String token = header.substring(7);
            try {
                SignedJWT signedJWT = SignedJWT.parse(token);
                JWSVerifier verifier = new MACVerifier(secret);
                if (signedJWT.verify(verifier)) {
                    JWTClaimsSet claims = signedJWT.getJWTClaimsSet();
                    if (new Date().before(claims.getExpirationTime())) {
                        UsernamePasswordAuthenticationToken auth = new UsernamePasswordAuthenticationToken(
                                claims.getSubject(), null, List.of(new SimpleGrantedAuthority("USER")));
                        SecurityContextHolder.getContext().setAuthentication(auth);
                    }
                }
            } catch (Exception e) {
                // invalid token – let it fall through to 401 later
            }
        }
        filterChain.doFilter(request, response);
    }
}
```

### 6. Controllers

```java
@RestController
public class AuthController {

    @Autowired private AuthenticationManager authManager;
    @Autowired private RefreshTokenRepository refreshRepo;

    @Value("${jwt.access.secret}")
    private String accessSecret;

    @PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody AuthRequest req) {
        try {
            Authentication auth = authManager.authenticate(
                new UsernamePasswordAuthenticationToken(req.getUsername(), req.getPassword()));
            String userId = ((UserDetails) auth.getPrincipal()).getUsername(); // assume ID = username

            // issue access token
            String access = JwtUtil.createAccessToken(userId, accessSecret);

            // issue opaque refresh token
            RefreshToken rt = new RefreshToken();
            rt.setToken(UUID.randomUUID().toString());
            rt.setUserId(Long.valueOf(userId));
            rt.setExpiresAt(Instant.now().plus(30, ChronoUnit.DAYS));
            refreshRepo.save(rt);

            return ResponseEntity.ok(Map.of(
                "access_token", access,
                "refresh_token", rt.getToken()));
        } catch (AuthenticationException ex) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("error", "invalid_credentials"));
        }
    }

    @PostMapping("/token")
    public ResponseEntity<?> refresh(@RequestBody Map<String, String> body) {
        String token = body.get("refresh_token");
        if (token == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "missing_token"));
        }

        Optional<RefreshToken> opt = refreshRepo.findByTokenAndRevokedFalseAndExpiresAtAfter(
                token, Instant.now());

        if (opt.isEmpty()) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("error", "invalid_refresh"));
        }

        RefreshToken old = opt.get();
        old.setRevoked(true);
        refreshRepo.save(old);

        // new tokens
        String access = JwtUtil.createAccessToken(old.getUserId().toString(), accessSecret);
        RefreshToken newRt = new RefreshToken();
        newRt.setToken(UUID.randomUUID().toString());
        newRt.setUserId(old.getUserId());
        newRt.setExpiresAt(Instant.now().plus(30, ChronoUnit.DAYS));
        refreshRepo.save(newRt);

        return ResponseEntity.ok(Map.of(
                "access_token", access,
                "refresh_token", newRt.getToken()));
    }
}
```

### 7. JWT Utility (`JwtUtil.java`)

```java
public class JwtUtil {

    public static String createAccessToken(String subject, String secret) {
        try {
            JWSSigner signer = new MACSigner(secret);
            JWTClaimsSet claims = new JWTClaimsSet.Builder()
                    .subject(subject)
                    .issueTime(new Date())
                    .expirationTime(Date.from(Instant.now().plus(10, ChronoUnit.MINUTES)))
                    .build();

            SignedJWT jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claims);
            jwt.sign(signer);
            return jwt.serialize();
        } catch (JOSEException e) {
            throw new RuntimeException(e);
        }
    }
}
```

### Running the Demo

```bash
./mvnw spring-boot:run
```

The Spring Boot application now supports:

* `/login` – returns short‑lived access JWT + opaque refresh token.  
* `/token` – rotates the refresh token and returns a fresh access token.  

**Key Spring‑specific notes:**

* `SecurityContextHolder` is populated by the JWT filter, keeping the rest of the app stateless.  
* The `RefreshToken` entity is persisted in an H2 database for demonstration, but production should use a hardened RDBMS or NoSQL store with encryption at rest.  

---

## Common Pitfalls and How to Avoid Them

| Pitfall | Consequence | Mitigation |
|----------|--------------|------------|
| **Storing refresh token in localStorage** | Vulnerable to XSS; attacker can read token and silently obtain new access tokens. | Use httpOnly Secure SameSite cookies or OS keychain. |
| **Never rotating refresh tokens** | Long‑lived token becomes a “master key.” | Implement rotation; invalidate old token immediately. |
| **Exposing the token endpoint to CSRF** | Malicious site can trigger token refresh on behalf of victim. | Require `Authorization` header or `X‑Requested‑With` + SameSite cookies; enforce PKCE. |
| **Using the same secret for access and refresh JWTs** | Compromise of one token type compromises the other. | Separate secrets and key rotation policies. |
| **Unlimited token reuse** | Allows replay attacks. | Store a `jti` (JWT ID) and reject reused IDs; enforce one‑time use for refresh tokens. |
| **Skipping audience (`aud`) claim** | Tokens may be accepted by unintended services. | Include `aud` and validate it on each resource server. |
| **Not checking token revocation** | Revoked tokens still accepted if they haven’t expired. | Cache revocation list; check DB for opaque tokens on each refresh. |
| **Using refresh tokens in SPAs** | Browser environment is hard to secure. | Prefer Authorization Code with PKCE and silent token renewal via the auth server’s session cookie. |
| **Hard‑coding token lifetimes** | Inflexible for different risk levels. | Make lifetimes configurable per client or per scope. |
| **Insufficient logging** | Hard to detect abuse. | Log every refresh attempt, include IP, user‑agent, and token ID (hashed). |

---

## Advanced Patterns: Sliding Sessions & Device Binding

### Sliding Sessions

A **sliding session** extends the refresh token’s lifetime each time it is used, as long as the user remains active. Implementation steps:

1. Set a **maximum absolute expiration** (e.g., 90 days).  
2. On each successful refresh, compute `newExpires = min(now + 30 days, absoluteExpiration)`.  
3. Store `absoluteExpiration` in the token payload or DB.  

This balances usability (active users stay logged in) with security (inactive tokens age out).

### Device Binding

Binding a refresh token to a specific device mitigates token theft across devices.

* **Approach:** Include a device fingerprint (e.g., hashed device ID, public key) in the token’s claims or DB row.  
* **Verification:** When the refresh endpoint receives a token, compare the stored fingerprint with the request’s fingerprint (sent via header or derived from TLS client cert).  
* **Rotation:** If the fingerprint changes, reject the request and force re‑authentication.

### Using Proof‑Key‑For‑Code‑Exchange (PKCE) with Refresh Tokens

Public clients (mobile, SPA) cannot keep a client secret. PKCE adds a **code verifier** that is bound to the original authorization request. When exchanging a refresh token, you can require the same code verifier (or a derived secret) to be sent, ensuring that only the original client can use the token.

```http
POST /token HTTP/1.1
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&
refresh_token=abcd1234&
client_id=mobile-app&
code_verifier=xyz987
```

The server validates that `code_verifier` matches the one stored with the original authorization code. This pattern is recommended by the OAuth Working Group as **Refresh Token Binding**.

---

## Real‑World Case Studies

### 1. Google OAuth 2.0

* **Refresh Token Lifetime:** Indefinite until revoked.  
* **Rotation Policy:** Google does **not** rotate automatically; developers must implement revocation via the **Token Revocation endpoint**.  
* **Security Measures:**  
  * Refresh tokens are **opaque** strings.  
  * They can be **restricted to a specific client ID** and **scopes**.  
  * Google supports **device‑level refresh tokens** for installed apps, tying tokens to a device ID.

### 2. Auth0

* **Refresh Token Types:** Opaque by default; can enable **JWT Refresh Tokens** for confidential clients.  
* **Rotation:** Auth0 offers **Refresh Token Rotation** out‑of‑the‑box. Each token can be used once; the old token is automatically invalidated.  
* **Revocation:** A **Refresh Token Revocation API** allows administrators to revoke tokens per user or per client.  
* **Best‑Practice Guidance:** Auth0 recommends using **Refresh Token Rotation** together with **Refresh Token Expiration** (e.g., 30 days) and **Refresh Token Revocation** on password change.

### 3. Azure Active Directory (Azure AD)

* **Token Model:** Access tokens are JWTs (default 1 hour). Refresh tokens are **opaque** and have a **maximum lifetime of 90 days** with **sliding expiration** (renewed on each use).  
* **Conditional Access:** Azure AD can enforce **MFA** or **device compliance** during a refresh; if a refresh request fails policies, the token is denied.  
* **Revocation:** Admins can **revoke refresh tokens** by resetting the user’s sign‑in session or by using the **revokeSignInSessions** Graph API.

These case studies illustrate that while the core OAuth 2.0 spec is simple, major providers extend it with rotation, sliding windows, and policy checks to meet enterprise security requirements.

---

## Monitoring, Auditing, and Incident Response

A robust token strategy includes observability.

### Logging Essentials

* **Event Type** – `refresh_success`, `refresh_failure`, `revocation`.  
* **User Identifier** – `sub` claim or DB user ID (hashed for privacy).  
* **Token Identifier** – `jti` (for JWT) or token UUID (for opaque).  
* **Client ID** – Which application requested the refresh.  
* **IP Address & User‑Agent** – Detect abnormal locations or devices.  
* **Timestamp** – UTC, ISO‑8601.

### Alerting

* **Spike Detection:** > N refreshes per minute per user → possible token theft.  
* **Failed Refresh Ratio:** High failure rate could indicate a **brute‑force** attack on token IDs.  
* **Geographic Anomalies:** Refresh from a new country combined with a successful login → trigger MFA.

### Incident Playbook

1. **Identify** compromised refresh token via logs.  
2. **Revoke** the token (set `revoked = true` or add to blacklist).  
3. **Force logout** of the user (invalidate all active access tokens).  
4. **Notify** the user and optionally require password change.  
5. **Review** the root cause (e.g., XSS, insecure storage).  

Automating steps 2–4 with a **Security Operations** script reduces dwell time dramatically.

---

## Conclusion

Refresh tokens are the linchpin that makes modern stateless authentication both **secure** and **user‑friendly**. By issuing a short‑lived access token for API calls and a long‑lived, tightly controlled refresh token for renewal, we achieve:

* **Reduced attack surface** – compromised access tokens expire quickly.  
* **Scalable revocation** – refresh tokens live in a server‑side store that can be invalidated on demand.  
* **Seamless UX** – users stay logged in without re‑entering credentials.

However, the power of refresh tokens comes with responsibility. Implementing **rotation**, **binding**, **proper storage**, and **comprehensive monitoring** are non‑negotiable for production‑grade systems. The code snippets across Node.js, Python, and Java illustrate that the concepts translate consistently across languages, while the real‑world case studies show how leading providers adapt the spec to meet enterprise needs.

By following the best practices outlined here—choosing the right token format, securing client storage, rotating on each use, and maintaining vigilant observability—you can harness refresh tokens safely and confidently in any modern application.

---

## Resources

* [OAuth 2.0 Authorization Framework (RFC 6749)](https://datatracker.ietf.org/doc/html/rfc6749) – The official specification describing the refresh token grant.  
* [OAuth 2.0 Security Best Current Practice (RFC 6819)](https://datatracker.ietf.org/doc/html/rfc6819) – Guidance on protecting tokens, including refresh token rotation.  
* [Auth0 Refresh Token Rotation Documentation](https://auth0.com/docs/tokens/refresh-token/refresh-token-rotation) – Practical guide and SDK examples for implementing rotation.  
* [Google Identity Platform – Refresh Tokens](https://developers.google.com/identity/protocols/oauth2/web-server#offline) – Details on Google’s long‑lived refresh tokens and revocation.  
* [Azure AD Token Lifetimes and Refresh Tokens](https://learn.microsoft.com/azure/active-directory/develop/active-directory-configurable-token-lifetimes) – Explanation of sliding expiration and conditional access.  

---