---
title: "From Terraform to Token Economics: The Six Skills That Became One Discipline"
date: "2026-09-05T18:53:48.722"
draft: false
tags: ["ai-infrastructure", "kubernetes", "gpu-orchestration", "inference-routing", "finops", "sre"]
description: "How AI infrastructure fuses Terraform, Kubernetes, GPU orchestration, inference-aware routing, SRE, and FinOps into one operational discipline."
summary: "AI infrastructure is no longer a subfield of MLOps — it is the convergence of six traditional disciplines. Here is how Terraform, Kubernetes, GPU scheduling, inference routing, SRE, and FinOps are collapsing into a single operating model."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-from-terraform-to-token-economics-the-six-skills-that-became-one-discipline.svg"
  alt: "Abstract visualization of AI infrastructure layers blending orchestration, networking, observability, and cost optimization."
  caption: ""
  relative: false
---

> **TL;DR** — AI infrastructure is not "MLOps with GPUs." It is the collapse of six mature disciplines — Terraform, Kubernetes, GPU orchestration, inference-aware routing, SRE, and FinOps — into one operating model where the unit of accounting is the token and the unit of failure is a 200ms p99 regression on a cold A100.

A few years ago, "AI infrastructure" was a slide in someone else's deck. It lived next to "data labeling" and "model registry" on a MarTech vendor's homepage. That world is gone. Today, the people shipping production LLM systems are the same people who used to run Kafka at 3 a.m., reconcile a cloud bill, and write Terraform modules for VPC peering. The tools changed. The disciplines didn't — they fused.

This post walks through the six disciplines that, taken together, define AI infrastructure in 2026. It is not a survey of frameworks. It is a working engineer's map of the territory.

## The Convergence Problem

Traditional infrastructure had clean seams. A platform team owned Kubernetes. A networking team owned the load balancer. A FinOps team owned the bill. Each layer could be reasoned about independently because the workload above it was predictable: web requests, batch jobs, message processing.

LLM workloads break every one of those seams. A single inference call can:

- Trigger a **GPU node pool autoscale** that takes 6–10 minutes on most clouds ([Kubernetes Autoscaler documentation](https://github.com/kubernetes/autoscaler) calls this out explicitly).
- Cause a **token-level cost explosion** if routing sends a 7B request to a 70B model because the prefix cache is warmer there.
- Produce a **p99 latency tail** that is dominated not by compute but by queueing at the KV-cache scheduler, which is invisible to standard APM.
- Make **observability cardinality** explode, because every request now carries a `model_id`, `prompt_token_count`, and `cache_hit` label.

You cannot bolt "AI features" onto an existing platform. The seams have to be redrawn. The six disciplines below are how they are being redrawn in production shops today.

## Terraform → Declarative AI Infrastructure

Terraform was supposed to end the era of snowflake environments. For LLM systems, it finally has a workload worthy of its philosophy.

The pattern that has won is **GitOps inference stacks**: a single repository where `terraform plan` against the `prod` workspace shows you not just VPCs and IAM roles, but also which model versions are deployed, on which GPU SKUs, behind which autoscaling policies. Examples like the [OpenAI infrastructure writeup](https://openai.com/index/ai-infrastructure/) and Anthropic's public posts on their training clusters describe variants of this approach — the underlying claim is the same: the cluster is a typed object.

```hcl
resource "kubernetes_deployment" "llama_8b_inference" {
  metadata {
    name = "llama-8b-inference"
    labels = {
      model       = "llama-3.1-8b"
      workload    = "inference"
      team        = "platform-ai"
    }
  }

  spec {
    replicas = 4

    selector {
      match_labels = { workload = "inference", model = "llama-3.1-8b" }
    }

    template {
      metadata {
        annotations = {
          # Prometheus will scrape this automatically
          "prometheus.io/scrape" = "true"
          "prometheus.io/port"   = "9090"
        }
      }
      spec {
        container {
          name  = "vllm"
          image = "vllm/vllm-openai:v0.6.3.post1"

          resources {
            requests = {
              # 8B model fits on a single A10G with KV cache headroom
              "nvidia.com/gpu"  = "1"
              cpu               = "8"
              memory            = "32Gi"
            }
            limits = {
              "nvidia.com/gpu"  = "1"
              cpu               = "16"
              memory            = "64Gi"
            }
          }

          env {
            name  = "MAX_MODEL_LEN"
            value = "8192"
          }
          env {
            name  = "GPU_MEMORY_UTILIZATION"
            value = "0.92"
          }
        }
      }
    }
  }
}
```

The non-obvious part is the `labels`. Three months after a model is retired, someone will ask "why is this GPU pool always 80% full at 2 a.m.?" and the answer will be in those labels. They are the join key between Terraform state, Prometheus metrics, and the FinOps chargeback report. Treat them as a schema.

## Kubernetes → GPU Orchestration

Kubernetes was not designed for GPUs. It was retrofitted. The retrofit is now stable enough that the question is no longer "can K8s do this?" but "which scheduler extensions do you need?"

Three extensions matter:

1. **The NVIDIA device plugin** ([project page](https://github.com/NVIDIA/k8s-device-plugin)) — exposes `nvidia.com/gpu` as a schedulable resource. Without it, your pods will not see GPUs at all.
2. **KubeRay** ([KubeRay docs](https://ray-project.github.io/kubespray/)) — for teams running RLHF or distributed training, not just inference.
3. **A topology-aware scheduler** — the [GKE custom compute classes](https://cloud.google.com/kubernetes-engine/docs/concepts/compute-classes) and [EKS Karpenter GPU support](https://karpenter.sh/docs/concepts/nodepools/) handle the "I need 8 H100s on the same NVLink domain" problem. This is where most naive setups fail silently.

The production pattern that has emerged:

- **Separate node pools per GPU SKU.** Do not put A10Gs and H100s behind the same KarpenterNodePool. They have different cost curves, different autoscale slopes, and different failure modes.
- **Bin-pack by latency budget, not by utilization.** A 7B model serving 200ms-p99 traffic wants dense packing to keep tail latency low. A 70B model serving batch traffic wants spread placement for throughput. Same scheduler, different topology policies.
- **Treat the model artifact as a Kubernetes-native resource.** Tools like [KServe](https://kserve.github.io/website/latest/) make this first-class. The `InferenceService` CRD owns the model version, the canary rollout, and the autoscaler — three things that previously lived in three different tools.

> A working heuristic: if your GPU utilization dashboard does not have separate lines for "scheduling loss," "KV-cache pressure," and "model load time," you are conflating three different cost drivers.

## Load Balancing → Inference-Aware Routing

This is the section that catches every team the first time. Standard L4/L7 load balancers route on TCP connection or HTTP path. They know nothing about tokens, prefixes, or KV caches. Yet the dominant cost in a serving system is the **prefix cache hit rate**.

Consider this routing decision:

```
Request A: "Summarize the following 10,000-token contract: <doc>"
Request B: "What is the capital of France?"
```

A naive round-robin balancer will send both to the same model instance. But Request A and Request B have wildly different optimal placements:

- Request A wants the **instance that already has this contract in its KV cache** (probably a single pod that previously ingested it via the document pipeline). Routing it elsewhere costs you the entire 10K-token prefill.
- Request B wants the **least-loaded 8B instance** — it is short, latency-sensitive, and trivially cacheable.

The systems that get this right — [vLLM's prefix caching](https://blog.vllm.ai/2023/06/20/vllm.html), [SGLang's RadixAttention](https://github.com/sgl-project/sglang), [Anyscale's routing work](https://www.anyscale.com/blog/continuous-batching-llm-inference) — do not use a generic load balancer. They use an **inference gateway** that maintains a prefix-to-instance map and routes based on:

- Prefix-cache locality (hash of the first N tokens)
- Queue depth at the instance (decode steps remaining)
- Model affinity (does this instance even host the requested model?)

Tools like [LiteLLM's proxy](https://github.com/BerriAI/litellm), [OpenRouter](https://openrouter.ai/), and the emerging [Envoy AI Gateway](https://gateway.envoyproxy.io/) are early attempts at standardizing this. None are finished products. All are necessary.

```yaml
# Envoy AI Gateway-style routing config (illustrative)
listeners:
  - name: inference
    routes:
      - match:
          model: "llama-3.1-70b"
        route:
          - destination: llama-70b-pool-a
            weight: 70
          - destination: llama-70b-pool-b
            weight: 30
          routing_strategy: prefix_affinity_with_queue_cap
      - match:
          model: "llama-3.1-8b"
        route:
          - destination: llama-8b-pool
            weight: 100
          routing_strategy: least_queue_depth
```

The mental model shift: **the load balancer is now part of the model.** Routing decisions change the effective throughput of the system by 3–10x.

## SRE → AI Reliability

Traditional SRE has SLOs like "99.9% of requests return in under 500ms." AI reliability has the same shape but different semantics.

The new failure modes:

- **Cold-start latency.** A new model replica takes 60–180 seconds to load weights and warm the KV cache. During this window, requests routed to it will time out. This is a **provisioning failure mode**, not a code bug.
- **Output quality regression.** A model can be "up" (returning 200s, healthy latency) and be **degraded** (returning subtly worse answers because of a quantization glitch or a stale adapter). Standard health checks cannot detect this.
- **Token-throughput cliffs.** Adding one concurrent stream to an instance does not degrade linearly — it causes prefill queue saturation that triples p99 latency. The cliff is invisible until you step over it.
- **Prompt injection DoS.** Adversarial prompts that force a model into pathological decoding loops are now a denial-of-service vector, not just a security one.

The SLOs that have emerged in production:

| SLO | Target | Why |
|---|---|---|
| First-token latency p50 | < 200ms | User-perceived "responsiveness" |
| Inter-token latency p99 | < 50ms | Streaming feel |
| Cold-start fraction | < 0.5% of requests | Capacity planning |
| Output quality (eval-set pass rate) | > 95% of baseline | Detects silent model regressions |
| Cost per 1K output tokens | bounded by SKU mix | FinOps input |

The last one is the tell. SRE no longer owns latency and FinOps owns cost — they share an SLO. That is the convergence.

> Reliability in the LLM era is measured at the **token level**, not the request level. A 200-token request and a 2000-token request have completely different SLO implications, even at the same p99 latency.

## Observability → AI Inference Monitoring

Generic observability stacks — Datadog, Grafana, Honeycomb, OpenTelemetry — handle the transport. The work is in the **metrics that actually matter for inference**.

The minimum viable metrics set, drawn from production systems and the [OpenLLMetry](https://github.com/traceloop/openllmetry) project:

```promql
# Time to first token, in seconds
histogram_quantile(0.99,
  sum by (le, model) (
    rate(vllm_time_to_first_token_seconds_bucket[5m])
  )
)

# Inter-token latency (the streaming smoothness metric)
histogram_quantile(0.99,
  sum by (le, model) (
    rate(vllm_inter_token_latency_seconds_bucket[5m])
  )
)

# Prefill vs decode token throughput
rate(vllm_prompt_tokens_total[1m])
rate(vllm_generation_tokens_total[1m])

# KV cache utilization — the canary for capacity
vllm_gpu_cache_usage_perc

# Prefix cache hit rate — the canary for routing quality
rate(vllm_prefix_cache_hits_total[5m]) /
  rate(vllm_prefix_cache_queries_total[5m])
```

Three things to notice:

1. **Histograms are bucketed by `model`.** Cardinality will hurt you. Budget for it. Ten models × six latency histograms × standard SLO buckets is manageable. A hundred models is not.
2. **`gpu_cache_usage_perc`** is the single most important early-warning metric. When it crosses 85%, you are about to start evicting prefixes, which will cascade into prefix-cache hit rate drop, which will cascade into prefill cost spike.
3. **The prefix cache hit rate is a routing-quality metric, not a model metric.** If it drops, the inference gateway is misrouting. If it stays high but latency climbs, the issue is at the scheduler.

For traces, use [OpenLLMetry](https://github.com/traceloop/openllmetry) or [Langfuse](https://langfuse.com/) — both add LLM-specific spans (`prompt_template_render`, `model_invoke`, `tokenize`) that standard OTEL instrumentation does not capture. The trace shape for an LLM call is fundamentally different from a database call: there is a prefill phase, a streaming decode phase, and often a post-processing chain.

## FinOps → Cost and Token Optimization

This is where the convergence becomes most visible. The FinOps dashboard for an AI system in 2026 looks like this:

```
Top cost drivers (last 24h):
  1. H100 pool — $14,200 — model=gpt-eval-suite, 12M output tokens
  2. A10G pool —  $3,400 — model=llama-8b-inference, 180M output tokens
  3. Egress      —  $1,100 — cross-region model sync
```

The H100 line is the problem: 12M tokens at H100 cost is roughly 100x the unit cost of the A10G line. If you cannot explain why the eval suite needs H100s, that is a $10K/day FinOps bug, not a FinOps metric.

The optimization levers, roughly ordered by impact:

1. **Model right-sizing.** Most production traffic does not need a 70B model. A well-prompted 8B is 10x cheaper. The [Databricks "DBRX" cost analysis](https://www.databricks.com/blog/introducing-dbrx) and similar write-ups show that the gap is closing, but the right-sized model is still dramatically cheaper.
2. **Prefix-cache hit rate.** A 30% → 70% hit rate improvement halves your effective compute cost on long-context workloads. This is a routing problem, not a model problem.
3. **Spot/preemptible for batch.** Workloads like offline eval, dataset generation, and embedding recomputation should run on [preemptible H100s](https://cloud.google.com/compute/docs/instances/preemptible) or spot equivalents. Save the on-demand pool for serving.
4. **Quantization.** GPTQ/AWQ/FP8 quantization can give 30–50% throughput improvement at minimal quality cost. The trade-off is real — measure it on your eval set, not on generic benchmarks.
5. **Request batching.** Continuous batching (the [vLLM paper](https://arxiv.org/abs/2309.06180) approach) is now table stakes; the next frontier is cross-request batching that exploits structural similarity across prompts.
6. **Caching layers.** Semantic caches like [GPTCache](https://github.com/zilliztech/GPTCache) can eliminate 20–40% of repeat queries for customer-support and FAQ-style traffic. The hit rate must be measured on real traffic, not assumed.

The FinOps team must own a **token-level cost report** that joins: GPU SKU × region × model × team. Without that join, you cannot do chargeback. Without chargeback, you cannot prioritize optimization. Without prioritization, the bill grows 5x per quarter, which is the current industry baseline.

## Architecture: A Reference Stack

Pulling the six disciplines together, the reference architecture that has emerged across the companies shipping serious LLM products in 2026:

```
┌─────────────────────────────────────────────────────────────┐
│                       Inference Gateway                      │
│  - Prefix-affinity routing                                  │
│  - Rate limiting per tenant                                 │
│  - Eval-set shadow traffic                                  │
└────────────┬─────────────────────────────────────┬──────────┘
             │                                     │
     ┌───────▼────────┐                  ┌────────▼────────┐
     │  8B Serving    │                  │  70B Serving    │
     │  A10G pool     │                  │  H100 pool      │
     │  vLLM/8B       │                  │  vLLM/70B       │
     │  Continuous    │                  │  Continuous     │
     │  batching      │                  │  batching       │
     └───────┬────────┘                  └────────┬────────┘
             │                                    │
             └────────────┬───────────────────────┘
                          │
              ┌───────────▼───────────┐
              │   GPU Node Pools      │
              │   (Karpenter/         │
              │    Cluster Autoscaler)│
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │  Observability        │
              │  - OpenLLMetry traces │
              │  - vLLM metrics       │
              │  - Cost reports       │
              └───────────────────────┘

Terraform state owns:
  - VPC, IAM, node pools
  - InferenceService CRDs (model, version, autoscaling)
  - Monitoring dashboards as code
  - Eval-set CI triggers
```

Every box in this diagram is owned by someone who used to work in a different discipline. The diagram is the point: there is no longer a clean boundary.

## Key Takeaways

- **AI infrastructure is not a sub-discipline of MLOps.** It is the convergence of Terraform, Kubernetes, GPU orchestration, inference-aware routing, SRE, observability, and FinOps into one operating model.
- **Routing decisions are now model-correctness decisions.** A bad routing decision can cost 10x in compute and silently degrade user experience by missing the prefix cache.
- **GPU node pools must be SKU-segmented** and topology-aware. Mixing A10Gs and H100s in one autoscaler is the most common production mistake.
- **SLOs are measured in tokens, not requests.** First-token latency, inter-token latency, prefix-cache hit rate, and cost-per-1K-tokens are the new core metrics.
- **Observability must include KV-cache utilization and prefix hit rate** as first-class signals. Standard APM tools do not capture them; you need inference-aware instrumentation.
- **FinOps joins on GPU SKU × model × team.** Without that join, chargeback is impossible, optimization is unprioritized, and the bill grows 5x per quarter.
- **Terraform labels are the join key** across state, metrics, and cost. Design them as a schema on day one, not after the first incident.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html)
- [KubeRay Documentation](https://ray-project.github.io/kubespray/)
- [NVIDIA Kubernetes Device Plugin](https://github.com/NVIDIA/k8s-device-plugin)
- [OpenLLMetry — LLM-native OpenTelemetry instrumentation](https://github.com/traceloop/openllmetry)
- [KServe — Serverless ML inference on Kubernetes](https://kserve.github.io/website/latest/)
- [Karpenter — Just-in-time nodes for Kubernetes](https://karpenter.sh/)
- [SGLang RadixAttention paper and docs](https://github.com/sgl-project/sglang)