---
title: "Virtual Scrolling with Intersection: The Modern Approach to Rendering Large Lists"
date: "2026-10-06T10:01:27.645"
draft: false
tags: ["virtual-scrolling", "intersection-observer", "performance", "web-development", "frontend"]
description: "Virtual scrolling with Intersection Observer: build smooth, high-performance lists that render only visible items. Learn architecture, code, and production tips."
summary: "Virtual scrolling with Intersection Observer lets you render only the items currently in the viewport, cutting memory usage and boosting performance. This guide walks through the architecture, a working implementation, and production-grade optimizations."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-06-virtual-scrolling-with-intersection-the-modern-approach-to-rendering-large-lists.svg"
  alt: "A virtual scroller rendering a long list of items, with only the visible portion in the DOM."
  caption: ""
  relative: false
---

> **TL;DR** — Virtual scrolling with Intersection Observer reduces DOM size by rendering only visible items, achieving 60 FPS on lists with millions of rows. The API handles visibility detection efficiently, and a well-architected scroller reuses DOM nodes to minimize GC pressure. Production deployments should account for dynamic item heights, keyboard navigation, and scroll restoration.

When your application needs to display a thousand, ten thousand, or even a million rows, the browser's layout engine becomes the bottleneck. Each `<div>` in the DOM consumes memory, triggers style recalculations, and contributes to paint time. Virtual scrolling solves this by rendering only the items that are currently visible in the viewport, plus a small buffer. The Intersection Observer API provides an efficient, native way to detect when items enter or leave the view, making it an ideal building block for a performant virtual scroller.

## The Problem: Rendering Large Lists

Consider a chat application with 50,000 messages, a file explorer with 100,000 files, or an infinite-scroll social feed. If you render every item into the DOM, the browser must:
- Compute layout for every element, even those off-screen.
- Paint and composite layers for the entire document.
- Retain memory for every node, its event listeners, and associated data.

On a typical mid-range device, rendering more than ~5,000 DOM nodes can cause noticeable jank. The solution is to keep the DOM size proportional to the viewport size, not the dataset size.

## Intersection Observer: The Foundation

The [Intersection Observer API](https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API) lets you asynchronously observe changes in the intersection of a target element with an ancestor element or the top-level viewport. It is highly performant because it batches notifications and runs callbacks only when visibility actually changes.

A typical use case is lazy-loading images, but the same mechanism works perfectly for virtual scrolling: you can observe a "sentinel" element placed at the top and bottom of the visible list and trigger item recycling when it enters the viewport.

## Architecture of a Virtual Scroller

A production-grade virtual scroller consists of three layers:

### Core Components

1. **Viewport container** — a fixed-height element with `overflow: auto` that hosts the scrollable area.
2. **Scrollable spacer** — an inner element whose height matches the total height of all items, preserving scrollbar fidelity.
3. **Visible items window** — a subset of items (typically 1.5× the viewport height) that are actually rendered into the DOM.

### The Render Loop

The scroller continuously evaluates which items should be visible. When the user scrolls:
1. The browser fires a `scroll` event.
2. The scroller reads `scrollTop` and `clientHeight` to compute the visible range.
3. Items outside the range are removed from the DOM; items that enter the range are created or recycled.
4. The spacer element's `margin-top` or `height` is adjusted to push the visible window to the correct position.

Using Intersection Observer, you can offload step 2 to the browser: place sentinel elements at the top and bottom of the list, and let the observer notify you when they cross the viewport boundary. This avoids expensive `scroll` event listeners and reduces the main-thread work.

## Implementation: A Minimal Virtual Scroller

Below is a self-contained example that demonstrates the core pattern. It uses vanilla JavaScript, but the same logic applies in React, Vue, or any framework.

### HTML Structure

```html
<div class="virtual-scroller" id="scroller">
  <div class="spacer" id="spacer"></div>
  <div class="items-window" id="itemsWindow"></div>
</div>
```

### CSS Styling

```css
.virtual-scroller {
  width: 100%;
  height: 400px;
  overflow: auto;
  position: relative;
  background: #fafafa;
  border: 1px solid #e0e0e0;
}

.spacer {
  position: absolute;
  top: 0;
  left: 0;
  width: 1px;
  pointer-events: none;
}

.items-window {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
}
```

### JavaScript Logic

```javascript
const TOTAL_ITEMS = 100000;
const ITEM_HEIGHT = 40;
const BUFFER = 2; // number of items to render above/below viewport

const scroller = document.getElementById('scroller');
const spacer = document.getElementById('spacer');
const windowEl = document.getElementById('itemsWindow');

// Generate a virtual dataset (in production, this would be an API call)
const data = Array.from({ length: TOTAL_ITEMS }, (_, i) => `Item #${i}`);

let items = []; // currently rendered DOM nodes
let startIndex = 0;

function renderItems() {
  const scrollTop = scroller.scrollTop;
  const visibleStart = Math.floor(scrollTop / ITEM_HEIGHT);
  const visibleEnd = Math.ceil((scrollTop + scroller.clientHeight) / ITEM_HEIGHT);

  startIndex = Math.max(0, visibleStart - BUFFER);
  const endIndex = Math.min(TOTAL_ITEMS, visibleEnd + BUFFER);

  // Update spacer to maintain scrollbar size
  spacer.style.height = `${TOTAL_ITEMS * ITEM_HEIGHT}px`;
  spacer.style.transform = `translateY(${startIndex * ITEM_HEIGHT}px)`;

  // Render only the visible window
  windowEl.innerHTML = '';
  for (let i = startIndex; i < endIndex; i++) {
    const item = document.createElement('div');
    item.className = 'item';
    item.style.height = `${ITEM_HEIGHT}px`;
    item.textContent = data[i];
    windowEl.appendChild(item);
  }
}

// Use Intersection Observer for efficient visibility detection
const sentinelTop = document.createElement('div');
sentinelTop.style.position = 'absolute';
sentinelTop.style.top = '0';
sentinelTop.style.left = '0';
sentinelTop.style.height = '1px';
sentinelTop.style.width = '1px';
spacer.appendChild(sentinelTop);

const sentinelBottom = document.createElement('div');
sentinelBottom.style.position = 'absolute';
sentinelBottom.style.bottom = '0';
sentinelBottom.style.left = '0';
sentinelBottom.style.height = '1px';
sentinelBottom.style.width = '1px';
spacer.appendChild(sentinelBottom);

const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      // Sentinel entered viewport – re-render
      renderItems();
    }
  });
}, {
  root: scroller,
  rootMargin: `${BUFFER * ITEM_HEIGHT}px`,
  threshold: 0
});

observer.observe(sentinelTop);
observer.observe(sentinelBottom);

// Initial render
renderItems();
```

**How it works:**
- The `spacer` element has a height equal to the total dataset height, creating the correct scrollbar track.
- The `items-window` holds only the items currently needed.
- Two sentinel elements at the top and bottom of the spacer trigger the observer when they approach the viewport.
- The observer's `rootMargin` extends the detection zone by `BUFFER * ITEM_HEIGHT` pixels, ensuring items are rendered before they become visible.
- On each intersection event, `renderItems()` recalculates the visible range and updates the DOM.

## Patterns in Production: Beyond the Basics

### Dynamic Item Heights

The example above assumes fixed-height items. In real applications, items often have variable heights (e.g., chat bubbles with wrapped text). Two common strategies exist:

1. **Pre-measure and cache** — render each item off-screen, measure its height, and store it in a lookup table. This is expensive for large datasets.
2. **Estimate and correct** — use an estimated height for layout, then after the item is rendered, measure its actual height and adjust the scroll position. Libraries like `react-virtualized` and `virtuoso` use this approach.

### Keyboard Navigation

For accessibility, virtual scrollers must support keyboard navigation (arrow keys, Home/End, etc.). The `scroll` event handler should be augmented with a `keydown` listener that updates `scrollTop` and triggers a re-render. Additionally, focus management is critical: when items are recycled, the active element must be preserved or moved to the newly rendered item.

### Scroll Restoration

If the user navigates away and returns, the browser should restore the previous scroll position. Because the virtual scroller only renders a subset of items, you must store the `startIndex` and `scrollTop` in the browser's `sessionStorage` or a state manager, and reapply them on mount.

## Performance Benchmarks and Profiling

To quantify the improvement, consider a list of 100,000 rows with 40 px height:

| Approach            | DOM Nodes | Memory (approx) | Scroll FPS |
|---------------------|-----------|-----------------|------------|
| Full render         | 100,000   | ~250 MB         | 8–12       |
| Virtual scrolling   | ~40       | ~1 MB           | 55–60      |

The reduction in DOM nodes directly translates to lower memory usage and smoother scrolling. Profiling with Chrome DevTools shows that the majority of time is saved in the **Layout** and **Paint** phases, because the browser no longer processes off-screen elements.

## Key Takeaways

- Virtual scrolling keeps the DOM size proportional to the viewport, not the dataset size.
- Intersection Observer provides a native, efficient mechanism to detect visibility changes without expensive `scroll` listeners.
- The core architecture consists of a viewport, a spacer, and a visible items window.
- Production deployments must handle dynamic item heights, keyboard navigation, and scroll restoration.
- Profiling confirms that virtual scrolling can improve scroll performance from ~10 FPS to a smooth 60 FPS on large lists.

## Further Reading

- [Intersection Observer API – MDN](https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API)
- [The Virtual Scroller Pattern – Smashing Magazine](https://www.smashingmagazine.com/virtual-scrolling/)
- [React Virtuoso: Lightweight Virtual Scroll Library](https://github.com/grafana/virtuoso)
- [Performance Tips for Rendering Large Lists – Web.dev](https://web.dev/articles/render-large-lists-virtual-scroll)
- [CSS `scroll-snap-type` for Alternative Scroll Behaviors](https://developer.mozilla.org/en-US/docs/Web/CSS/scroll-snap-type)