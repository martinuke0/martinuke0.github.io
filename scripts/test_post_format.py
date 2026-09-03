#!/usr/bin/env python3
"""Self-check for clean_hook — run: python scripts/test_post_format.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from post_to_linkedin import clean_hook

# real hook strings observed in the queue
cases = [
    ("> TL;DR — BBR models the network as a (bandwidth, RTT) pair rather than reacting to packet loss.",
     "BBR models the network as a (bandwidth, RTT) pair rather than reacting to packet loss."),
    ("> **TL;DR** — QUIC runs many independent byte streams over a single UDP connection.",
     "QUIC runs many independent byte streams over a single UDP connection."),
    ("A clean hook with no markdown at all.",
     "A clean hook with no markdown at all."),
]
for raw, expected in cases:
    got = clean_hook(raw)
    assert got == expected, f"\n  raw:      {raw!r}\n  got:      {got!r}\n  expected: {expected!r}"

# must not start with markdown noise
assert not clean_hook("> **TL;DR** — x").startswith((">", "*", "#")), "leading markdown leaked"
print("clean_hook self-check passed")
