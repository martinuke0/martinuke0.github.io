---
title: "How Lock‑Free Queues Handle Memory Reclamation via Hazard Pointers"
date: "2026-05-15T19:01:03.855"
draft: false
tags: ["concurrency","lock-free","memory-management","hazard-pointers","data-structures"]
description: "Explore how hazard pointers enable safe memory reclamation in lock‑free queues, covering core concepts, integration steps, performance trade‑offs, and practical C++ examples."
summary: "A deep dive into hazard pointers for lock‑free queues, showing why they matter, how they work, and when to use them over alternative reclamation schemes."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-how-lockfree-queues-handle-memory-reclamation-via-hazard-pointers.svg"
  alt: "Illustration of a concurrent queue with colored hazard pointers."
  caption: ""
  relative: false
---

> **TL;DR** — Hazard pointers give lock‑free queues a deterministic way to know when a node is no longer reachable, allowing safe reclamation without global pauses. By marking the nodes a thread might still access, they prevent use‑after‑free bugs while keeping the queue’s throughput comparable to other lock‑free techniques.

Lock‑free data structures promise progress without the bottlenecks of mutexes, but they introduce a subtle problem: when a thread removes a node, other threads might still hold a reference to it. Traditional garbage collection either pauses the world (stop‑the‑world collectors) or incurs heavy reference‑counting overhead, both of which clash with the low‑latency goals of lock‑free programming. Hazard pointers, introduced by Maged M. Michael in 2004, provide a lightweight, explicit mechanism for a thread to announce which nodes it might still touch, letting the system safely recycle memory once no hazard remains. This article walks through the problem, the hazard‑pointer solution, and a concrete integration with the classic Michael‑Scott lock‑free queue.

## The Challenge of Memory Reclamation in Lock‑Free Queues

### Why Traditional Garbage Collection Falls Short

A lock‑free queue typically consists of a linked list of nodes where `enqueue` appends at the tail and `dequeue` removes from the head. Both operations use atomic `compare_and_swap` (CAS) to swing pointers. When `dequeue` succeeds, it logically removes a node, but the physical memory cannot be freed immediately because another thread might have read the pointer before the CAS and still be about to dereference it.

In a managed language like Java or C#, the runtime’s garbage collector eventually discovers that the node is unreachable and reclaims it. However, in C or C++ (the lingua franca of high‑performance systems), we must manage memory manually. Two naïve approaches are:

1. **Immediate `delete`** – leads to use‑after‑free bugs, as other threads may still hold the stale pointer.
2. **Reference counting** – adds an atomic increment/decrement on every pointer read/write, which dramatically reduces the throughput that lock‑free structures aim to deliver.

Both approaches either break correctness or destroy performance, prompting the need for a reclamation scheme that respects the lock‑free contract: *no thread should ever block another thread’s progress*.

### The Core Requirement

A reclamation algorithm for lock‑free structures must answer a single question safely:

> *When is it guaranteed that no thread can possibly dereference a given node?*

Only then can the node be reclaimed (e.g., `delete`d). Hazard pointers answer this by letting each thread publish the exact set of nodes it may still access.

## Hazard Pointers: Core Concept

Hazard pointers are essentially per‑thread slots that hold raw pointers to *dangerous* nodes. The algorithm works in three phases:

1. **Acquire a hazard pointer** – before dereferencing a node, a thread stores the node’s address in one of its hazard slots.
2. **Validate** – after publishing the hazard, the thread re‑reads the shared pointer it intends to use. If the shared pointer still points to the same node, the hazard is valid; otherwise, the node may have been reclaimed and the thread must retry.
3. **Retire and reclaim** – when a thread removes a node, it places the node on a *retirement list*. Periodically, it scans all hazard pointers; any retired node not present in any hazard slot is safe to `delete`.

The crucial property is that hazard pointers are **read‑only for other threads**: a thread never clears another thread’s hazard slots. Therefore, the only way a node can be reclaimed is if *every* thread has either cleared its own hazard slot or never set it to that node.

### How Hazard Pointers Prevent Premature Reclamation

Consider two threads, T1 and T2, operating on a shared queue:

1. T1 reads `head` → points to node `N`.
2. Before T1 dereferences `N`, it stores `N` in its hazard slot `HP[0]`.
3. T2 successfully dequeues `N` and places `N` on its retirement list.
4. T2 scans hazard slots. It sees `HP[0]` holds `N`, so it cannot delete `N` yet.
5. Later, T1 finishes processing `N`, clears its hazard slot, and T2’s next scan will finally delete `N`.

Thus, the node lives exactly as long as any thread might still be using it—no more, no less.

## Integrating Hazard Pointers into a Queue Algorithm

### Example: Michael‑Scott Queue with Hazard Pointers

The Michael‑Scott (MS) queue is the canonical lock‑free FIFO. Below is a compact C++11 implementation that adds hazard‑pointer support. The code focuses on the `dequeue` path, where reclamation is critical.

```cpp
// hazard_ptr.h – minimal hazard‑pointer API
#include <atomic>
#include <vector>
#include <thread>

constexpr int HAZARD_SLOTS = 2;          // per‑thread hazard slots
constexpr int RETIRE_THRESHOLD = 40;    // when to scan for reclamation

struct HazardRecord {
    std::atomic<void*> hp[HAZARD_SLOTS];
    HazardRecord* next;
};

class HazardManager {
    std::atomic<HazardRecord*> head_;
    static thread_local HazardRecord* local_;
public:
    HazardManager() : head_(nullptr) {}
    HazardRecord* acquire() {
        if (!local_) {
            local_ = new HazardRecord{};
            for (int i = 0; i < HAZARD_SLOTS; ++i) local_->hp[i].store(nullptr);
            // push onto global list
            HazardRecord* old = head_.load(std::memory_order_relaxed);
            do { local_->next = old; } while (!head_.compare_exchange_weak(old, local_));
        }
        return local_;
    }
    void set(int idx, void* p) { acquire()->hp[idx].store(p, std::memory_order_seq_cst); }
    void clear(int idx) { acquire()->hp[idx].store(nullptr, std::memory_order_seq_cst); }

    // Scan all hazard slots
    std::vector<void*> snapshot() {
        std::vector<void*> hp;
        for (HazardRecord* r = head_.load(); r; r = r->next)
            for (int i = 0; i < HAZARD_SLOTS; ++i) {
                void* p = r->hp[i].load(std::memory_order_seq_cst);
                if (p) hp.push_back(p);
            }
        return hp;
    }
};

thread_local HazardRecord* HazardManager::local_ = nullptr;

// ------------------------------------------------------------
// ms_queue.h – Michael‑Scott queue with hazard pointers
template<typename T>
class MSQueue {
    struct Node {
        std::atomic<Node*> next;
        T* data;               // nullptr for dummy node
        Node(T* d = nullptr) : next(nullptr), data(d) {}
    };

    std::atomic<Node*> head_;
    std::atomic<Node*> tail_;
    HazardManager hp_;
    thread_local static std::vector<Node*> retireList;

    void retire(Node* n) {
        retireList.push_back(n);
        if (retireList.size() >= RETIRE_THRESHOLD) scan();
    }

    void scan() {
        // collect all hazard pointers
        auto hazards = hp_.snapshot();
        std::unordered_set<Node*> hazardSet(hazards.begin(), hazards.end());

        // reclaim nodes not protected
        auto it = retireList.begin();
        while (it != retireList.end()) {
            if (hazardSet.find(*it) == hazardSet.end()) {
                delete *it;
                it = retireList.erase(it);
            } else ++it;
        }
    }

public:
    MSQueue() {
        Node* dummy = new Node();
        head_.store(dummy);
        tail_.store(dummy);
    }

    ~MSQueue() {
        // simple destructor: walk list and delete
        Node* cur = head_.load();
        while (cur) {
            Node* nxt = cur->next.load();
            delete cur;
            cur = nxt;
        }
    }

    void enqueue(T* value) {
        Node* n = new Node(value);
        Node* t;
        while (true) {
            t = tail_.load(std::memory_order_acquire);
            Node* nxt = t->next.load(std::memory_order_acquire);
            if (nxt) {
                // tail is falling behind; try to swing it forward
                tail_.compare_exchange_weak(t, nxt);
                continue;
            }
            if (t->next.compare_exchange_weak(nxt, n)) {
                // swing tail to new node
                tail_.compare_exchange_weak(t, n);
                return;
            }
        }
    }

    // Returns nullptr if queue empty
    T* dequeue() {
        Node* h;
        while (true) {
            h = head_.load(std::memory_order_acquire);
            hp_.set(0, h);                     // protect head
            if (h != head_.load(std::memory_order_acquire)) { hp_.clear(0); continue; }

            Node* t = tail_.load(std::memory_order_acquire);
            Node* first = h->next.load(std::memory_order_acquire);
            hp_.set(1, first);                 // protect first node
            if (h != head_.load(std::memory_order_acquire)) { hp_.clear(1); continue; }

            if (first == nullptr) {            // empty queue
                hp_.clear(0); hp_.clear(1);
                return nullptr;
            }
            if (h == t) {
                // tail is lagging; try to advance it
                tail_.compare_exchange_weak(t, first);
                continue;
            }
            T* value = first->data;
            // try to swing head forward
            if (head_.compare_exchange_weak(h, first)) {
                hp_.clear(0); hp_.clear(1);
                retire(h);                     // old dummy node can be reclaimed later
                return value;
            }
            // CAS failed – retry
            hp_.clear(0); hp_.clear(1);
        }
    }
};

template<typename T>
thread_local std::vector<typename MSQueue<T>::Node*> MSQueue<T>::retireList;
```

**Explanation of key hazard‑pointer interactions**

1. **Publishing hazards** – before reading `head` and `first`, the thread stores them in `hp_[0]` and `hp_[1]`. This guarantees that any other thread that later retires those nodes will see the hazard.
2. **Validation step** – after setting a hazard, the thread re‑loads the shared pointer (`head_` or `first`) to verify that it still points to the same node. If it changed, the hazard is stale and the loop restarts.
3. **Retirement** – the old dummy node (`h`) is placed on a per‑thread retirement list. When the list reaches `RETIRE_THRESHOLD`, the thread scans all hazard slots (`hp_.snapshot()`) and deletes any node not present.

The code remains lock‑free: no thread ever blocks another; reclamation work is performed locally by each thread during its own operations.

## Performance Considerations and Trade‑offs

### When to Prefer Hazard Pointers over Epoch‑Based Reclamation

| Aspect                | Hazard Pointers                                 | Epoch‑Based Reclamation (EBR)               |
|-----------------------|--------------------------------------------------|--------------------------------------------|
| **Memory overhead**   | One hazard slot per thread per structure (tiny) | Global epoch counter + per‑thread lists   |
| **Reclamation latency** | Immediate once all hazards cleared            | Bounded by epoch advancement (may delay) |
| **Complexity**        | Requires careful hazard management per access   | Simpler per‑operation, but needs epoch sync |
| **Scalability**        | Scales well with many threads; hazard scans are O(N) where N = #threads | Scales well; epoch advancement can become a bottleneck under high contention |
| **Best use‑case**      | Fine‑grained structures where prompt reclamation matters (e.g., lock‑free stacks, queues) | Bulk‑oriented structures where occasional delayed reclamation is acceptable |

Hazard pointers excel when reclamation latency directly impacts performance (e.g., when a node holds a large buffer that must be freed quickly). Epoch‑based schemes are easier to implement for data structures that already batch operations, but they may keep memory alive longer than necessary.

### Cost of Scanning Hazard Slots

Each scan touches every thread’s hazard slots, which is an O(T) operation (`T` = number of threads). In practice, the scan is triggered only after a thread accumulates `RETIRE_THRESHOLD` retired nodes, amortizing the cost. Empirical studies (see Michael’s original paper) show that with a threshold of 40‑100, the overhead is less than 2 % of total operation time on modern multicore CPUs.

### Memory Footprint

A hazard‑pointer system reserves `HAZARD_SLOTS * sizeof(void*)` per thread. For a typical 8‑slot configuration on a 64‑bit machine, that’s merely 64 bytes per thread—negligible compared to the cache lines used by the queue itself.

## Key Takeaways

- **Hazard pointers let each thread explicitly announce which nodes it may still dereference**, preventing premature reclamation without global pauses.
- **The three‑step pattern (publish, validate, retire)** guarantees safety while preserving lock‑free progress.
- **Integration into a classic lock‑free queue** involves protecting the head and first node during `dequeue`, then retiring the old dummy node once hazards are cleared.
- **Performance impact is modest**: scans are infrequent and O(number of threads), while memory overhead is tiny.
- **Choose hazard pointers when reclamation latency matters**; otherwise, epoch‑based reclamation may be simpler for bulk‑oriented workloads.

## Further Reading

- [Original Hazard Pointers paper by Maged M. Michael (2004)](https://dl.acm.org/doi/10.1145/1028976.1029025)  
- [Microsoft Research technical report on Hazard Pointers](https://www.microsoft.com/en-us/research/publication/hazard-pointers/)  
- [Michael‑Scott lock‑free queue description (1996)](https://doi.org/10.1145/248052.248106)  
- [Boost.Lockfree library reference – includes hazard‑pointer support](https://www.boost.org/doc/libs/release/doc/html/boost_lockfree.html)  
- [C++ Concurrency in Action, 2nd Edition – Chapter on lock‑free data structures](https://www.manning.com/books/c-plus-plus-concurrency-in-action-second-edition)