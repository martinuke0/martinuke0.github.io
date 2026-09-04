---
title: "Distributed Tracing Across Kafka and gRPC With OpenTelemetry Context Propagation"
date: "2026-09-04T13:00:29.382"
draft: false
tags: ["opentelemetry", "distributed-tracing", "kafka", "grpc", "observability"]
description: "How to propagate OpenTelemetry context across Kafka and gRPC in production: W3C Trace Context, headers, and the gotchas that break traces."
summary: "A field guide to implementing distributed tracing with OpenTelemetry across Kafka message boundaries and gRPC calls, including header propagation, instrumented producers and consumers, and the failure modes that leave orphaned spans."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-distributed-tracing-across-kafka-and-grpc-with-opentelemetry-context-propagation.svg"
  alt: "Diagram of a trace spanning a Kafka producer, broker, consumer, and downstream gRPC service."
  caption: ""
  relative: false
---

> **TL;DR** — OpenTelemetry's W3C Trace Context propagates cleanly over gRPC out of the box, but Kafka is just bytes on a wire, so you must manually inject and extract the `traceparent` header on `ProducerRecord` and `ConsumerRecord`. Get this right once in a shared interceptor/filter, and you get continuous traces from HTTP ingress through Kafka to a downstream worker — even when consumers process in batches or reprocess after a rebalance.

## Why Kafka Breaks Most Traces

If you have ever stared at a tracing UI and seen a beautiful waterfall that suddenly forks into a dozen disconnected root spans the moment work lands on a message queue, you have hit this exact problem. gRPC and HTTP/2-based protocols carry `traceparent` headers natively because they were designed by the same generation of engineers who lost sleep over correlation. Kafka is a different beast: a `ProducerRecord` is a bag of bytes, and nothing about the wire protocol cares whether your payload is JSON, Avro, or a postcard from your grandmother.

The result is that the [W3C Trace Context](https://www.w3.org/TR/trace-context/) — the `traceparent` and `tracestate` headers that link spans together — has to be carried by your application code, either as message headers on the record or, more commonly, embedded inside the payload envelope. Forget this once, and you have orphan spans. Forget it in two services, and your trace graph looks like a bowl of spaghetti.

This post walks through how to do it right: a producer-side injector, a consumer-side extractor, and the gRPC plumbing that connects it all into a single trace. We will anchor everything in real OpenTelemetry SDK calls rather than hand-wavy "configure your tracer" prose.

## The Architecture We Are Wiring Up

Before any code, here is the topology. This matters because every hop is a propagation boundary, and getting the boundaries right is half the battle.

```
   [API Gateway] --HTTP--> [Order Service] --gRPC--> [Pricing Service]
                                            \
                                             --Kafka produce--> [orders.events]
                                                                       |
                                                                       v
                                                              [Fulfillment Worker]
                                                                       |
                                                                       --gRPC--> [Inventory Service]
```

Five hops, three protocols, two queue boundaries. The trace we want to see in Jaeger or Tempo spans all five. The two interesting boundaries are:

1. **Order Service → Kafka broker**: the producer must inject the active context into the record headers before `send()`.
2. **Kafka broker → Fulfillment Worker**: the consumer must extract that context at the top of `poll()`, before any business logic, and use it as the parent for the new "consume" span.

The gRPC hops in between are largely automatic, as long as you have installed the OpenTelemetry gRPC instrumentation package. We will cover both ends.

## Propagation Primitives: `traceparent` and `tracestate`

OpenTelemetry's default propagator is the [W3C Trace Context propagator](https://opentelemetry.io/docs/concepts/context-propagation/). It serializes the current span's trace identity into two headers:

- `traceparent`: `00-<trace-id 32 hex>-<span-id 16 hex>-<flags 2 hex>`. Example: `00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01`.
- `tracestate`: vendor-specific key/value pairs (e.g., `vendor1=foo,vendor2=bar`). Optional and rarely needed unless you are running multiple tracing vendors.

The Java SDK exposes these through the `TextMapPropagator` interface. Two methods matter:

```java
TextMapPropagator.inject(Context context, C carrier, Setter<C>);
TextMapPropagator.extract(Context context, C carrier, Getter<C>);
```

For Kafka records the carrier is a `ProducerRecord` (inject) or `ConsumerRecord` (extract). The setter writes headers; the getter reads them. You never see `traceparent` as a string you build by hand — the propagator does it for you, which is exactly the point.

## Producer Side: Inject on Send

The pattern is to wrap the `KafkaProducer.send()` call so that the moment a record is about to leave your process, the active context is captured and stuffed into the record's headers. A clean way to do this in Java is an `Interceptor` on the producer config:

```java
public class TracingProducerInterceptor implements ProducerInterceptor<String, byte[]> {

    private static final TextMapPropagator PROPAGATOR =
        OpenTelemetry.getPropagators().getTextMapPropagator();

    @Override
    public ProducerRecord<String, byte[]> onSend(ProducerRecord<String, byte[]> record) {
        Headers headers = record.headers();
        PROPAGATOR.inject(Context.current(), headers,
            (carrier, key, value) -> {
                if (carrier instanceof Headers h) {
                    h.add(key, value == null ? null : value.getBytes(StandardCharsets.UTF_8));
                }
            });
        return record;
    }
}
```

Register it via the producer config:

```text
interceptor.classes=com.example.TracingProducerInterceptor
```

That is the entire producer-side story. Every record that leaves the JVM carries a fresh `traceparent` derived from whatever span is active at the moment of `send()`. If the calling code has a span open for "process order," that span becomes the parent of whatever the consumer eventually does.

Two production notes worth flagging:

- **Send asynchronously?** That is fine. The context is captured synchronously at `onSend()` time; the actual network write can happen whenever Kafka's I/O thread gets to it.
- **Headers vs payload?** Keep `traceparent` in headers, not in the message body. Headers survive schema evolution, payload serializers don't need to know about tracing, and Avro/Protobuf users don't have to graft metadata onto their `.avsc` files.

## Consumer Side: Extract on Poll

The consumer is where most teams get it wrong. The temptation is to extract the context inside the message handler, after deserialization. By then you have already done work that isn't part of any span, and if deserialization itself fails or takes a long time, that latency never appears in your trace.

Extract at the top of `poll()`, in a wrapper around the consumer, or — if you must — at the first line of your message handler. The wrapper approach is cleaner:

```java
public class TracingConsumerInterceptor<K, V> implements ConsumerInterceptor<K, V> {

    private static final TextMapPropagator PROPAGATOR =
        OpenTelemetry.getPropagators().getTextMapPropagator();

    @Override
    public ConsumerRecord<K, V> onConsume(ConsumerRecords<K, V> records) {
        for (ConsumerRecord<K, V> record : records) {
            Context extracted = PROPAGAGTOR.extract(Context.current(), record.headers(),
                (carrier, key) -> {
                    if (carrier instanceof Headers h) {
                        ByteBuffer buf = h.lastHeader(key) == null ? null : ByteBuffer.wrap(h.lastHeader(key).value());
                        return buf == null ? null : new String(buf.array(), StandardCharsets.UTF_8);
                    }
                    return null;
                });
            // Stash extracted context on the record for the handler to pick up.
            // (ConsumerInterceptor can't pass it through directly; use a ThreadLocal
            // or a record wrapper as shown below.)
            record.headers().add("__extracted_ctx__",
                extracted.toString().getBytes(StandardCharsets.UTF_8));
        }
        return records;
    }
}
```

In practice the interceptor pattern is awkward because the extracted `Context` is not a natural part of `ConsumerRecord`. Most production codebases do the extract inside the handler, but on the very first line:

```java
@KafkaListener(topics = "orders.events")
public void onOrderEvent(ConsumerRecord<String, OrderEvent> record) {
    Context parent = PROPAGATOR.extract(Context.current(), record.headers(), KafkaHeadersGetter.INSTANCE);

    Span span = tracer.spanBuilder("orders.fulfillment.consume")
        .setSpanKind(SpanKind.CONSUMER)
        .setParent(parent)
        .startSpan();

    try (Scope scope = span.makeCurrent()) {
        OrderEvent event = deserialize(record.value());
        inventoryService.reserve(event); // gRPC call inherits the span as parent
        shipmentService.schedule(event);
    } catch (Exception e) {
        span.recordException(e);
        span.setStatus(StatusCode.ERROR);
        throw e;
    } finally {
        span.end();
    }
}
```

That span now sits in the same trace as the original "process order" span from the API gateway, several minutes and a Kafka rebalance later. Same trace ID, same root.

## gRPC: The Easy Part

gRPC is well-behaved because metadata is a first-class concept and OpenTelemetry ships an official instrumentation module. In Java you add the dependency and register it on both the client and server:

```java
// On the client channel builder
ManagedChannel channel = NettyChannelBuilder.forAddress("pricing", 9090)
    .intercept(GrpcTelemetry.create(openTelemetry).newClientInterceptor())
    .build();

// On the server
Server server = ServerBuilder.forPort(9090)
    .addService(ServerInterceptors.intercept(
        new PricingServiceImpl(),
        GrpcTelemetry.create(openTelemetry).newServerInterceptor()))
    .build();
```

For Go, the equivalent is two lines with `otelgrpc`:

```go
conn, _ := grpc.Dial("pricing:9090",
    grpc.WithUnaryInterceptor(otelgrpc.UnaryClientInterceptor()))
server := grpc.NewServer(grpc.UnaryInterceptor(otelgrpc.UnaryServerInterceptor()))
```

What you get for free:

- An outbound CLIENT span per RPC, with the `traceparent` injected into the gRPC metadata.
- An inbound SERVER span on the receiving side, with that metadata extracted and used as the parent.
- Standard attributes populated: `rpc.system=grpc`, `rpc.service=PricingService`, `rpc.method=GetQuote`, `rpc.grpc.status_code`, and so on.

Because gRPC propagates the W3C headers natively, the trace stays continuous when the Fulfillment Worker makes its downstream `InventoryService.Reserve` call. No glue code required.

## Patterns in Production

Once you have the baseline, three patterns come up in nearly every real deployment.

### Pattern 1: Spans Around the Batch, Not the Record

Kafka consumers usually process records in batches. If you create one span per record you get a useful but visually noisy trace with 200 sibling consumer spans. Two practical alternatives:

- **Parent batch span, child record spans.** Wrap `poll()` in a CONSUMER span named `orders.fulfillment.batch` keyed on `kafka.batch.size`, then open one short INTERNAL span per record. This is what the [Kafka client instrumentation](https://github.com/open-telemetry/opentelemetry-java-instrumentation) does automatically if you opt in.
- **Sample at the batch.** If volume is high, sample 1% of records but always keep the batch span. Most of your latency signal lives in the batch span anyway.

### Pattern 2: Manual Links for Reprocessing

Sometimes a consumer fails and the message is requeued, or a worker retries by re-producing to a different topic. This is not a parent/child relationship — it is a causal link across time. OpenTelemetry supports this with span links:

```java
Span reprocessSpan = tracer.spanBuilder("orders.fulfillment.reprocess")
    .addLink(originalSpanContext)
    .startSpan();
```

You can carry the original span context in a Kafka header (`x-original-traceparent`) or embed it in the message envelope. This produces a trace view that says "this work was caused by that earlier failed attempt," which is enormously helpful when triaging retry storms.

### Pattern 3: Producer Span as the Source of Truth

Some teams argue about whether the producer's `send()` call deserves its own span. The OpenTelemetry semantic conventions say yes: it should be a PRODUCER-kind span with low-level Kafka attributes (`messaging.system=kafka`, `messaging.destination.name=orders.events`, `messaging.kafka.message.offset`, etc.). This lets you see producer-side latency separately from consumer-side latency, which matters when brokers are slow but consumers are fast, or vice versa.

The Java auto-instrumentation does this for `kafka-clients` ≥ 3.0 if you enable it. If you write your own interceptor, you control the attribute set, which is occasionally useful for stripping high-cardinality fields like client IDs.

## Gotchas That Will Bite You

A non-exhaustive list of things that have bitten production teams:

1. **Header name collisions.** Kafka headers are byte-keyed and case-sensitive. `traceparent` is correct; `Traceparent` is not. Make sure your serializer doesn't mangle case.
2. **Consumer group rebalances.** During a rebalance, records from the same partition can be processed twice by different consumers. If you extract context inside the handler and the handler crashes mid-flight, the retry happens with the same parent context but a new span — exactly what you want.
3. **Async producers and context capture.** If you wrap `producer.send()` in a `CompletableFuture` chain and the callback runs on a different thread, the active context is gone by the time the callback fires. Inject synchronously at `onSend()` and you avoid this entirely.
4. **Multiple propagators.** If your service receives traffic from both an OpenTelemetry-instrumented service and a Zipkin-instrumented legacy service, configure the `TextMapPropagator` with both. The default W3C-only setup will silently drop Zipkin's `X-B3-TraceId` headers and you'll get orphan spans on the legacy side.
5. **Compression.** Some Kafka clients compress headers transparently in newer versions (KIP-110). The propagator works on the logical Headers object, so this is invisible to you, but worth knowing if you ever inspect raw bytes.
6. **Schema registry payloads.** If you use Confluent's Avro/Protobuf serializer, the schema ID is stored in a magic-byte header, not in your payload. Do **not** try to put `traceparent` in the schema payload; the serializer will overwrite it. Headers are safe; payload bytes are not.

## Key Takeaways

- Kafka does not propagate trace context natively. Inject `traceparent` into record headers on the producer side with a `ProducerInterceptor`, and extract it on the consumer side before any work happens.
- gRPC propagation is essentially free if you install the official OpenTelemetry gRPC instrumentation and register it on both client and server.
- Keep context in headers, not in message payloads. Headers survive schema evolution and serializer swaps.
- Create a CONSUMER span around the batch, with optional per-record child spans, so traces remain readable under high throughput.
- Use span links when a message is reprocessed or routed to a new topic — it expresses causality without faking a parent/child relationship.
- Watch out for case sensitivity, async send chains, multi-propagator setups, and schema-registry payload encodings. Each one is a different way traces silently fragment.

## Further Reading

- [OpenTelemetry Context Propagation Concepts](https://opentelemetry.io/docs/concepts/context-propagation/)
- [W3C Trace Context Recommendation](https://www.w3.org/TR/trace-context/)
- [OpenTelemetry Semantic Conventions: Messaging Systems](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/)
- [OpenTelemetry Java Instrumentation: kafka-clients](https://github.com/open-telemetry/opentelemetry-java-instrumentation/tree/main/instrumentation/kafka-clients)
- [OpenTelemetry Go: otelgrpc package](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc)
- [Jaeger: Kafka instrumentation guide](https://www.jaegertracing.io/docs/1.50/client_libraries/)