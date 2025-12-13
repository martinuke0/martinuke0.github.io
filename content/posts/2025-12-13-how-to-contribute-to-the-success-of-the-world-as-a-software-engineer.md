---
title: "How to Contribute to the Success of the World as a Software Engineer"
date: "2025-12-13T12:42:00.889"
draft: false
tags: ["software-engineering", "career", "impact", "open-source", "ethics"]
---

## Introduction

Software shapes economies, governments, education, healthcare, and the environment. As a software engineer, you have unusual leverage: a small team can build systems that serve millions, influence policy, or accelerate science. But leverage cuts both ways—without intent and rigor, software can also amplify harm.

This article is a practical, comprehensive guide to making your engineering work meaningfully contribute to the success of the world. It blends strategy (what to work on), tactics (how to work), and habits (how to sustain impact), with concrete examples and code you can apply immediately.

> Note: “Success of the world” is a broad phrase. Here, it means technology that improves human well-being, protects rights and the climate, strengthens institutions, and reduces inequities, while minimizing unintended harm.

## Table of Contents

- [Define “Success” and Pick a North Star](#define-success-and-pick-a-north-star)
- [Choose Problems That Matter](#choose-problems-that-matter)
- [Build Responsibly: Product, Process, and Outcomes](#build-responsibly-product-process-and-outcomes)
- [Contribute via Open Source and Standards](#contribute-via-open-source-and-standards)
- [Reliability, Testing, and Safety as Impact Multipliers](#reliability-testing-and-safety-as-impact-multipliers)
- [Privacy, Security, and Data Ethics](#privacy-security-and-data-ethics)
- [Leverage Through Mentoring, Docs, and Internal Platforms](#leverage-through-mentoring-docs-and-internal-platforms)
- [Sustainable and Carbon-Aware Engineering](#sustainable-and-carbon-aware-engineering)
- [Accessibility and Inclusive Design](#accessibility-and-inclusive-design)
- [Civic Tech, Policy, and Public Interest Work](#civic-tech-policy-and-public-interest-work)
- [Career Strategy for Maximum Impact](#career-strategy-for-maximum-impact)
- [Habits That Compound Over Time](#habits-that-compound-over-time)
- [Measure and Communicate Your Impact](#measure-and-communicate-your-impact)
- [Conclusion](#conclusion)

## Define “Success” and Pick a North Star

Before you decide what to build, define the outcomes you want to improve and how you’ll know it’s working.

- Anchor to widely recognized goals:
  - United Nations Sustainable Development Goals (SDGs)
  - OECD well-being indicators
  - Local community priorities (public health, transit access, digital equity)
- Clarify your personal North Star:
  - Who benefits? Who might be harmed?
  - What is the time horizon? Immediate relief, long-term capacity-building, or systemic change?
  - What guardrails and metrics will guide you?

A simple framing that works in teams: “We aim to increase [desirable outcome] for [population] by [X%] within [time], while maintaining [safety/privacy constraints].”

## Choose Problems That Matter

Leverage comes from working on high-importance problems where your skills are a key constraint.

- High-impact domains for engineers:
  - Climate and energy: grid software, building efficiency, carbon accounting, carbon-aware scheduling
  - Health: open EHR interoperability, clinical decision support, public health surveillance
  - Education: low-bandwidth learning apps, open curricula, teacher tools, credentialing
  - Government and justice: benefits access, court scheduling, transparency, procurement tools
  - Infrastructure: identity, payments, logistics, safety-critical systems
  - Security and privacy: secure messaging, end-to-end encrypted collaboration, safety tooling for NGOs
- Choose with a simple rubric:
  1. Scale: How many people are affected?
  2. Neglectedness: Are capable teams already on it?
  3. Tractability: Can incremental progress be made with available resources?
  4. Risk: What are failure modes and potential harms?

> Note: It’s okay to choose a path that balances impact and personal sustainability. Burnout helps no one.

## Build Responsibly: Product, Process, and Outcomes

Impact isn’t only what you build; it’s how you build.

- Start with real users. Conduct interviews and participatory design with the communities your software serves.
- Prioritize inclusivity and safety. Assume adversaries exist; assume users have diverse abilities, devices, languages, and connectivity.
- Optimize for outcomes, not vanity metrics. Engagement alone isn’t success if it displaces healthier alternatives or violates privacy.

Example: lightweight outcome tracking for a learning app

```python
# outcomes.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class LearningOutcome:
    user_id_hash: str  # salted hash; never store raw IDs
    lesson_id: str
    pre_score: Optional[int]
    post_score: Optional[int]

    @property
    def delta(self) -> Optional[int]:
        if self.pre_score is None or self.post_score is None:
            return None
        return self.post_score - self.pre_score

def is_meaningful_improvement(delta: Optional[int]) -> bool:
    return delta is not None and delta >= 10
```

This focuses on learning gains (an outcome), not time-on-app (an output).

## Contribute via Open Source and Standards

Open collaboration spreads benefits beyond your organization and reduces duplication.

- Contribute patches, docs, and tests to critical dependencies.
- Publish interoperable APIs and adhere to standards (e.g., FHIR for health, OIDC/OAuth for identity).
- Write a clear CONTRIBUTING guide and a code of conduct.

Example: minimal CONTRIBUTING.md template

```md
# Contributing

Thanks for helping improve this project! To contribute:

1. Open an issue to discuss significant changes before coding.
2. Fork the repo and create a feature branch: `feat/short-description`.
3. Add tests and docs with your change.
4. Run the full test suite: `make test`.
5. Submit a PR referencing related issues. We use Conventional Commits.

## Development setup
- Python >= 3.11
- `make setup` to install deps, `make test` to run tests.
- Lint with `ruff`, format with `black`.

## Code of Conduct
We enforce the Contributor Covenant. Be respectful and inclusive.
```

Automate CI to keep drive-by contributions healthy:

```yaml
# .github/workflows/ci.yml
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pip install -r requirements-dev.txt
      - run: make lint && make test
```

## Reliability, Testing, and Safety as Impact Multipliers

Software that fails at the wrong moment can cause real-world harm. Reliability is an ethical requirement.

- Testing discipline:
  - Unit tests for core logic
  - Property-based tests for critical invariants
  - Contract tests for inter-service APIs
- Operability:
  - Clear SLOs/SLIs, observability, graceful degradation
  - Blameless postmortems and incident response runbooks
- Safety:
  - Feature flags and staged rollouts
  - Kill switches for risky models or features

Example: small, fast unit test

```python
# tests/test_scoring.py
import pytest
from outcomes import LearningOutcome, is_meaningful_improvement

def test_delta_and_threshold():
    lo = LearningOutcome("userhash", "lesson123", pre_score=55, post_score=68)
    assert lo.delta == 13
    assert is_meaningful_improvement(lo.delta)
```

Example: feature flag check (server-side)

```python
# flags.py
import os

def feature_enabled(name: str) -> bool:
    return os.getenv(f"FLAG_{name.upper()}", "false").lower() == "true"
```

## Privacy, Security, and Data Ethics

Trust is foundational. Build with data minimization, consent, and secure defaults.

- Principles:
  - Collect only what you need
  - Store the minimum duration necessary
  - Anonymize or pseudonymize by default
  - Provide clear consent and opt-outs
  - Secure at rest and in transit with modern cryptography
- Threat model early. Consider abuse scenarios, harassment risks, and re-identification attacks.
- Use mature libraries for crypto; avoid rolling your own.

Example: privacy-preserving logging

```python
# privacy_log.py
import hashlib
import os
from datetime import datetime

SALT = os.environ.get("USER_HASH_SALT", "rotate-this-regularly")

def user_hash(user_id: str) -> str:
    return hashlib.sha256((SALT + user_id).encode()).hexdigest()[:16]

def log_event(event_name: str, user_id: str, metadata: dict):
    safe_user = user_hash(user_id)
    redacted = {k: ("[REDACTED]" if k in {"email", "phone"} else v) for k, v in metadata.items()}
    line = {"ts": datetime.utcnow().isoformat() + "Z", "event": event_name, "user": safe_user, **redacted}
    print(line)  # send to append-only, access-controlled sink
```

Example: strong password hashing with Argon2 (Python)

```python
# auth.py
from argon2 import PasswordHasher
ph = PasswordHasher()  # defaults are sane; configure memory/time if needed

def hash_password(pw: str) -> str:
    return ph.hash(pw)

def verify_password(hash_str: str, pw: str) -> bool:
    try:
        return ph.verify(hash_str, pw)
    except Exception:
        return False
```

> Note: Apply data protection by design and by default (e.g., GDPR principles) even if you’re not legally required. It’s the right thing to do.

## Leverage Through Mentoring, Docs, and Internal Platforms

Your impact scales when others build better and faster.

- Mentoring and pairing: upscale juniors, spread good norms.
- Code review: focus on correctness, readability, and long-term maintenance.
- Internal platforms: build paved roads—secure, observable templates, and shared services.
- Documentation: invest in design docs, runbooks, and architecture decision records (ADRs).

Simple ADR template:

```md
# ADR-001: Choose Postgres for transactional store
Date: 2025-01-17
Status: Accepted

## Context
We need a reliable OLTP database with strong consistency and mature tooling.

## Decision
Use Postgres 16 with logical replication and pg_partman for partitioning.

## Consequences
+ Mature ecosystem, easy local dev
- Need careful tuning for high write volume
```

## Sustainable and Carbon-Aware Engineering

Software runs on electricity. Efficiency is climate action.

- Design for efficiency:
  - Choose efficient algorithms and data structures
  - Profile hotspots before scaling hardware
  - Prefer vectorized, batch operations for data jobs
- Carbon-aware scheduling:
  - Shift flexible workloads to times/regions with cleaner grids
- Reduce waste:
  - Right-size instances, autoscale, sleep idle workers
  - Cache intelligently; avoid unnecessary network calls

Example: carbon-aware batch job scheduling (Python)

```python
# carbon_aware.py
import os, time, requests
from datetime import datetime

CARBON_API = os.getenv("CARBON_API", "https://api.carbonintensity.org.uk/intensity")
THRESHOLD = int(os.getenv("CARBON_THRESHOLD", "200"))  # gCO2/kWh

def current_intensity() -> int:
    r = requests.get(CARBON_API, timeout=5)
    r.raise_for_status()
    data = r.json()
    # Normalize to a single integer; API shapes vary by provider.
    if isinstance(data, dict) and "data" in data:
        return int(data["data"][0]["intensity"]["actual"] or data["data"][0]["intensity"]["forecast"])
    # Fallback
    return int(data.get("intensity", 300))

def run_job():
    print("Running job at", datetime.utcnow().isoformat(), "Z")
    # ... your actual workload ...

if __name__ == "__main__":
    for _ in range(12):  # retry for up to ~1 hour
        if current_intensity() <= THRESHOLD:
            run_job()
            break
        print("High carbon intensity; sleeping 5 minutes")
        time.sleep(300)
```

> Note: For global workloads, consider region-aware placement using providers’ carbon data or third-party services.

## Accessibility and Inclusive Design

Accessible software broadens impact and is often legally required.

- Basics:
  - Provide semantic HTML, proper labels, focus management
  - Maintain color contrast (WCAG AA/AAA)
  - Support screen readers and keyboard navigation
  - Offer captions/transcripts for media
  - Design for low bandwidth and intermittent connectivity
- Test with real users and assistive technologies (NVDA, VoiceOver).

Example: accessible button and status region

```html
<button id="saveBtn" aria-describedby="saveDesc">Save</button>
<p id="saveDesc" class="sr-only">Saves your changes</p>
<div id="status" role="status" aria-live="polite"></div>

<script>
document.getElementById('saveBtn').addEventListener('click', async () => {
  const status = document.getElementById('status');
  status.textContent = 'Saving...';
  try {
    await fetch('/api/save', { method: 'POST' });
    status.textContent = 'Saved successfully.';
  } catch {
    status.textContent = 'Save failed. Please retry.';
  }
});
</script>

<style>
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}
</style>
```

## Civic Tech, Policy, and Public Interest Work

Governments and NGOs need engineers.

- Volunteer:
  - Contribute to civic tech groups, hack nights, or disaster response mapping
  - Offer pro bono sprints for nonprofits with clear scopes
- Work in/with the public sector:
  - Modernize legacy systems that affect millions (benefits, licensing, procurement)
  - Build open APIs and adhere to accessibility and security standards
- Engage policy:
  - Provide technical input on AI, privacy, and competition regulation
  - Write clear, non-jargon explanations for policymakers and the public

> Tip: Public interest work benefits from patience, documentation, and empathy for constraints like procurement rules.

## Career Strategy for Maximum Impact

Your job choices determine your long-run leverage.

- Evaluate employers:
  - Mission alignment and credible theory of change
  - Leadership’s track record on ethics, safety, and transparency
  - Willingness to measure outcomes and act on evidence
- Roles that multiply impact:
  - Platform/productivity engineering
  - Security/privacy engineering
  - Reliability/SRE for critical services
  - ML safety and evaluation
- Earn-to-give and hybrid models:
  - If you thrive in high-earning roles, commit a meaningful percentage to effective charities
  - Balance with direct work or open-source contributions
- Side projects and fellowships:
  - Build targeted tools for NGOs, schools, clinics
  - Apply for grants and fellowships in civic tech or science tooling

## Habits That Compound Over Time

Small, consistent behaviors create outsized impact.

- Write: design docs, postmortems, public blogs, and README files that teach others
- Practice code health: readable, tested, documented, observable code
- Learn continuously: security, data ethics, domain knowledge
- Build relationships: collaborate across disciplines (policy, design, operations)
- Reflect: hold quarterly retrospectives on your personal impact plan

Simple personal impact retro prompts:

1. What outcomes did my work measurably improve?
2. What risks did I mitigate or introduce?
3. Where did I unblock others at scale?
4. What should I stop, start, continue next quarter?

## Measure and Communicate Your Impact

If you can’t measure it, you can’t improve it—and you can’t persuade others to help.

- Define metrics tied to outcomes:
  - Health: reduction in missed appointments, improved adherence
  - Education: learning gains, course completion
  - Climate: kWh saved, gCO2e avoided
  - Access: time to receive benefits, percentage of successful applications
- Pair metrics with guardrails:
  - Privacy budget, fairness metrics across demographics
  - Error budgets and availability SLOs
- Communicate clearly:
  - Public dashboards when appropriate
  - Case studies with methods, caveats, and limitations
  - Transparent postmortems and roadmaps

Example: simple SLO tracking concept

```python
# slo.py
from statistics import mean

def availability_sli(events):
    # events: list of booleans (True = healthy)
    return mean(1.0 if e else 0.0 for e in events)

def meets_slo(sli: float, target: float = 0.995) -> bool:
    return sli >= target
```

## Conclusion

You don’t need to found a unicorn to help the world. You need clarity on what matters, the discipline to build responsibly, and the humility to measure and iterate. Choose problems worth solving, design for safety and inclusion, contribute to shared infrastructure, and scale your impact by empowering others. Whether you’re optimizing carbon-aware workloads, securing communications for at-risk users, improving accessibility, or modernizing public services, your engineering craft can be a force multiplier for global well-being.

Start with one step this week: pick a domain, write your North Star, contribute a small PR, add tests, improve accessibility, or draft an ADR. Small, consistent contributions compound—across teams, products, and ultimately, the world.