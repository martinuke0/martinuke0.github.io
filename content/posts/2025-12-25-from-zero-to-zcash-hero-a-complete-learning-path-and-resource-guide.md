---
title: "From Zero to Zcash Hero: A Complete Learning Path and Resource Guide"
date: "2025-12-25T14:48:43.791"
draft: false
tags: ["zcash", "cryptocurrency", "privacy", "zero-knowledge", "tutorial"]
---

Zcash is one of the most technically sophisticated cryptocurrencies in existence. It combines Bitcoin-style sound money with cutting-edge zero-knowledge cryptography to provide strong financial privacy.

But that sophistication also makes it intimidating.

This guide is a **step-by-step roadmap**—with curated resources at every level—to take you from **zero** (no prior Zcash knowledge) to **hero** (able to understand, reason about, and even build on Zcash).

You’ll learn:

- What Zcash is and why it matters
- Which prerequisites you actually need (and which you can safely skip)
- Exactly **what to study in what order**
- How to go from user to node operator to developer
- Where to find the **best, up-to-date resources** for each stage

---

## Table of Contents

1. [What Is Zcash and Why Learn It?](#what-is-zcash-and-why-learn-it)  
2. [Prerequisites and Learning Strategy](#prerequisites-and-learning-strategy)  
   2.1. [Mindset](#mindset)  
   2.2. [Background Knowledge Checklist](#background-knowledge-checklist)  
3. [Stage 1: Crypto & Blockchain Foundations](#stage-1-crypto--blockchain-foundations)  
   3.1. [Goals](#stage-1-goals)  
   3.2. [Key Concepts](#stage-1-key-concepts)  
   3.3. [Recommended Resources](#stage-1-recommended-resources)  
4. [Stage 2: Zcash at a High Level](#stage-2-zcash-at-a-high-level)  
   4.1. [Goals](#stage-2-goals)  
   4.2. [Core Zcash Concepts](#core-zcash-concepts)  
   4.3. [High-Level Zcash Resources](#high-level-zcash-resources)  
   4.4. [Hands-On: Your First Shielded Transaction](#hands-on-your-first-shielded-transaction)  
5. [Stage 3: Zero-Knowledge Proofs & zk-SNARKs Fundamentals](#stage-3-zero-knowledge-proofs--zk-snarks-fundamentals)  
   5.1. [Goals](#stage-3-goals)  
   5.2. [Conceptual Understanding of ZKPs](#conceptual-understanding-of-zkps)  
   5.3. [ZK & zk-SNARK Learning Resources](#zk--zk-snark-learning-resources)  
6. [Stage 4: Zcash Protocol & Architecture](#stage-4-zcash-protocol--architecture)  
   6.1. [Goals](#stage-4-goals)  
   6.2. [Key Protocol Concepts](#key-protocol-concepts)  
   6.3. [Core Technical Resources](#core-technical-resources)  
7. [Stage 5: Running a Zcash Node](#stage-5-running-a-zcash-node)  
   7.1. [zcashd vs Zebra](#zcashd-vs-zebra)  
   7.2. [Installing zcashd (Example: Ubuntu/Debian)](#installing-zcashd-example-ubuntudebian)  
   7.3. [Basic zcash-cli Commands](#basic-zcash-cli-commands)  
8. [Stage 6: Developing on Zcash](#stage-6-developing-on-zcash)  
   8.1. [Development Approaches](#development-approaches)  
   8.2. [Using zcashd’s JSON-RPC](#using-zcashds-json-rpc)  
   8.3. [Sample Python Script: Querying zcashd](#sample-python-script-querying-zcashd)  
   8.4. [Light Clients and lightwalletd](#light-clients-and-lightwalletd)  
   8.5. [Developer-Focused Resources](#developer-focused-resources)  
9. [Stage 7: Advanced / “Hero” Track](#stage-7-advanced--hero-track)  
   9.1. [Deep Protocol Mastery](#deep-protocol-mastery)  
   9.2. [Cryptography & Research Papers](#cryptography--research-papers)  
   9.3. [Contributing to Zcash](#contributing-to-zcash)  
10. [Sample 3–6 Month Study Plan](#sample-36-month-study-plan)  
11. [Common Pitfalls and How to Avoid Them](#common-pitfalls-and-how-to-avoid-them)  
12. [Consolidated Resource List (Annotated)](#consolidated-resource-list-annotated)  
13. [Conclusion](#conclusion)  

---

## What Is Zcash and Why Learn It?

Zcash is a decentralized cryptocurrency that offers **selective, strong privacy** using **zero-knowledge proofs (zk-SNARKs)**. It’s based on a Bitcoin-like model (UTXO, proof-of-work) but enables transactions where:

- Sender, receiver, and amount can be encrypted
- The network can still verify the transaction is valid
- No one learns the sensitive details, unless you choose to reveal them

Understanding Zcash positions you at the intersection of:

- Cryptography (zero-knowledge proofs, commitments, signatures)
- Systems engineering (distributed consensus, networking, performance)
- Policy and ethics (financial privacy, regulation, human rights)

If you want to understand **privacy-preserving cryptocurrencies, zero-knowledge tech, or production zk systems**, Zcash is one of the most valuable case studies.

---

## Prerequisites and Learning Strategy

### Mindset

Zcash is dense. You don’t need to understand everything at once.

Think in **layers**:

1. User-level: how to use Zcash safely.
2. System-level: how the protocol works conceptually.
3. Cryptography-level: how zk-SNARKs & constructions like Orchard work.
4. Developer-level: how to build tools and apps.

You can stop at any layer and still have gained valuable knowledge.

### Background Knowledge Checklist

Helpful (but not strictly required) before you go deep:

- Basic familiarity with:
  - How Bitcoin roughly works (addresses, transactions, mining)
  - Public-key cryptography (private/public keys, signatures)
  - Command-line basics (for node operations and dev work)
- For deep cryptography:
  - Algebra basics (groups, fields)
  - Probability and security definitions are a plus

If you lack some of this, Stage 1 will help.

---

## Stage 1: Crypto & Blockchain Foundations

### Stage 1: Goals

By the end of this stage, you should:

- Understand how **Bitcoin** works at a high level
- Know what a **UTXO**, **address**, **private key**, and **block** are
- Be comfortable with:
  - Reading a transaction on a block explorer
  - Basic cryptography concepts: hashing, signatures

### Stage 1: Key Concepts

Focus on:

- Digital signatures and keys
- Hash functions and Merkle trees
- UTXO model vs account model
- Mining and proof-of-work
- Blockchain as an append-only ledger

### Stage 1: Recommended Resources

#### Beginner-Friendly

- **Book:**  
  *Mastering Bitcoin* by Andreas M. Antonopoulos  
  - Website: <https://github.com/bitcoinbook/bitcoinbook> (free HTML)  
  - Focus: Chapters 1–4 (Introduction, Cryptography Basics, Bitcoin Core, Transactions)

- **Online Course (Free):**  
  *Bitcoin and Cryptocurrency Technologies* (Princeton)  
  - Coursera: <https://www.coursera.org/learn/cryptocurrency>  
  - Focus: Weeks 1–4 for foundations

- **Video Series:**  
  *Andreas Antonopoulos – Intro to Bitcoin & Blockchain*  
  - YouTube search: “Andreas Antonopoulos Introduction to Bitcoin”

#### Cryptography Basics

- **Article:**  
  “A (Relatively Easy To Understand) Primer on Elliptic Curve Cryptography”  
  - <https://blog.cloudflare.com/a-relatively-easy-to-understand-primer-on-elliptic-curve-cryptography/>

- **Interactive:**  
  Cryptopals (for hands-on crypto intuition, optional but excellent)  
  - <https://cryptopals.com/>

---

## Stage 2: Zcash at a High Level

### Stage 2: Goals

By the end of this stage, you should:

- Explain what **problem Zcash solves** (privacy vs transparency)
- Understand the difference between:
  - Transparent vs shielded addresses
  - Bitcoin vs Zcash in terms of privacy
- Know what **shielded transactions** and **zk-SNARKs** are in words

### Core Zcash Concepts

Key pieces to grasp:

- **Transparent vs shielded:**
  - Transparent (“t-addresses”): Bitcoin-like, visible on-chain
  - Shielded (“z-addresses”, now often within **Unified Addresses**)
- **Pools:**
  - Different generations: Sprout (legacy), Sapling, Orchard
- **Unified Addresses (UA):**
  - A single address encoding support for multiple pools (transparent + shielded)
  - Wallets choose the best receiver internally
- **Selective disclosure:**
  - Viewing keys to reveal details of shielded transactions when needed
- **Network upgrades:**
  - Zcash evolves via **Network Upgrades** and **ZIPs (Zcash Improvement Proposals)**
  - As of 2024, **NU5** is the latest major upgrade, introducing Orchard and Halo 2-based proofs

### High-Level Zcash Resources

#### Official & Introductory

- **Official Website:**  
  <https://z.cash/>

  Focus pages:
  - “What is Zcash?”: <https://z.cash/learn/what-is-zcash/>
  - “Privacy and Security”: <https://z.cash/learn/privacy/>

- **Zcash FAQ:**  
  <https://z.cash/faq/>

- **Zcash Foundation:**  
  <https://www.zfnd.org/>  
  - Focus: mission, network governance, grant programs

#### Overview Articles & Talks

- **Zerocash Paper (Intro Sections):**  
  *Zerocash: Decentralized Anonymous Payments from Bitcoin*  
  - PDF: <https://zerocash-project.org/media/pdf/zerocash-extended-20140518.pdf>  
  - Focus initially on introduction and high-level design, not the math

- **Talks/Interviews:**
  - Search YouTube for:
    - “Zooko Wilcox Zcash introduction”
    - “Why Zcash? Electric Coin Company”

### Hands-On: Your First Shielded Transaction

You don’t need deep theory to start *using* Zcash.

#### Step 1: Pick a Wallet with Shielded Support

As of 2024, look for wallets that:

- Support **Orchard** shielded addresses
- Support **Unified Addresses**
- Are actively maintained

Examples (always verify current status and security yourself):

- **YWallet** – open-source, multi-platform  
  <https://ywallet.app/>
- **Zashi** – by Electric Coin Company (mobile, shielded-focused)  
  <https://z.cash/wallets/> (check for latest links)
- **Zingo!** – community-developed wallet  
  <https://github.com/zingolabs/zingo-mobile>

> **Note:** Always download from official sites or verified repositories. Beware fake apps.

#### Step 2: Get a Small Amount of ZEC

- Use a centralized exchange that supports ZEC, or
- Use a peer-to-peer platform or friend

Send only a **tiny** amount initially—enough for test transactions.

#### Step 3: Make a Shielded Transaction

1. In your wallet, generate a **Unified Address (UA)** or shielded address.
2. Fund it from your exchange or another wallet.
3. Send a small amount from your own shielded address to another shielded address (could be another wallet you control).
4. Observe:
   - On a block explorer (e.g., <https://zcashblockexplorer.com/> or similar; search “Zcash explorer”)  
   - You’ll see the transaction exists but not the sender/recipient/amount for shielded parts.

This concrete experience will anchor everything you learn later.

---

## Stage 3: Zero-Knowledge Proofs & zk-SNARKs Fundamentals

### Stage 3: Goals

By the end of this stage, you should:

- Explain **what a zero-knowledge proof is** (conceptually)
- Understand what zk-SNARKs are and why they’re special
- Recognize why they’re useful for Zcash

You **do not** need to fully understand the algebra yet.

### Conceptual Understanding of ZKPs

A zero-knowledge proof (ZKP) lets a **prover** convince a **verifier** that:

- A statement is true  
- Without revealing *why* it’s true (no extra information leaks)

In Zcash, the statement is roughly:

> “I know a secret spending key for some coins, those coins exist and haven’t been spent, and the transaction balances, **without telling you which coins they are or how much they’re worth**.”

zk-SNARKs are a particular kind of ZKP that are:

- **Succinct** – proofs are small and fast to verify
- **Non-interactive** – no back-and-forth; a single proof string suffices
- **Argument of Knowledge** – strongly tied to actual possession of a witness (like a key)

### ZK & zk-SNARK Learning Resources

#### Visual & Intuitive

- **Article (Highly Recommended):**  
  “An Illustrated Primer on Zero-Knowledge Proofs”  
  - Search: “Zero Knowledge Proofs: An illustrated primer” (many mirrors; look for reputable host like Medium or personal blogs)
  - Uses analogies like “Where’s Waldo”

- **Article:**  
  “Explaining SNARKs” by Vitalik Buterin  
  - <https://vitalik.ca/general/2021/01/26/snarks.html>

- **Video:**  
  Talks from the **ZK Summit** series  
  - <https://zksummit.com/> (archive with recordings)

#### Slightly More Technical (But Still Accessible)

- **Blog Series:**  
  Zcash-centric blog posts by Electric Coin Company (ECC) about Sapling and Orchard  
  - <https://electriccoin.co/blog/>  
  - Recommended search topics on the blog:
    - “Sapling”
    - “Orchard”
    - “Halo 2”
    - “Zero-knowledge proofs”

- **Guide:**  
  *The zk-SNARKs for Dummies* (several blog posts use this title)  
  - Search exact phrase and choose a reputable source (e.g., Hackernoon, personal crypto blogs)

> **Tip:** At this stage, focus on *why* zk-SNARKs are powerful and what properties they provide, not on the underlying polynomials and pairings.

---

## Stage 4: Zcash Protocol & Architecture

### Stage 4: Goals

By the end of this stage, you should:

- Understand at a conceptual level:
  - How Zcash transactions are structured
  - The roles of **transparent**, **Sapling**, and **Orchard** components
- Be able to read parts of the **Zcash protocol specification**
- Know what ZIPs are and how network upgrades are defined

### Key Protocol Concepts

#### 1. UTXO + Shielded Notes

- Transparent side: Similar to Bitcoin, with **UTXOs**.
- Shielded side: Coins are represented as **notes**, with committed values and owners.
- Notes are:
  - Created and destroyed using zk-SNARK proofs
  - Recorded in a **Merkle tree** (commitment tree) to support privacy

#### 2. Address Types (Historical & Current)

- **Transparent (t-addrs):**
  - Public, like Bitcoin addresses
  - Use for compatibility, but not recommended for privacy

- **Sprout (legacy shielded):**
  - First generation, now deprecated for most use cases

- **Sapling (z-addrs):**
  - More efficient, widely deployed shielded pool

- **Orchard:**
  - Current-generation shielded pool (NU5)
  - Uses Halo 2-based zk-SNARKs without a trusted setup

- **Unified Addresses (UA):**
  - Encapsulate multiple receiver types (transparent, Sapling, Orchard)
  - Default in modern wallets

#### 3. Viewing Keys

- **Full viewing keys (FVK):**
  - Let you see incoming and outgoing shielded transactions
  - Do not let you spend

- **Incoming viewing keys (IVK) / related constructs:**
  - Let you see only incoming transactions (exact structure depends on pool)

These enable **audits and compliance** without sacrificing user privacy globally.

#### 4. Transaction Structure

A modern Zcash transaction (post-NU5) can contain:

- Transparent inputs/outputs
- Sapling shielded actions
- Orchard shielded actions
- A **transaction digest** and **signature**
- zk-SNARK proofs for the shielded parts

### Core Technical Resources

#### Protocol Specification

- **Zcash Protocol Specification (NU5)**  
  - PDF: <https://zips.z.cash/protocol/nu5.pdf>  
  - HTML (if available): <https://zips.z.cash/protocol/protocol.pdf> or via index at <https://zips.z.cash/>

Start with:

1. Introduction and Notation (skim)
2. High-level protocol overview
3. Sections on Sapling & Orchard concepts (read conceptually first)

> **Reading strategy:**  
> Don’t try to understand every formula at once. First get the *shape* of the protocol: what components exist and how they interact.

#### ZIPs (Zcash Improvement Proposals)

- Index: <https://zips.z.cash/zip-0000>

Important ZIPs to at least skim:

- **ZIP 0000:** ZIP process overview  
- **ZIP 224:** Orchard shielded protocol  
- **ZIP 244:** Transaction identifier and sighash for NU5  
- ZIPs related to network upgrades (NU5 and earlier)

#### Implementation Repositories

- **zcashd (C++ reference node):**  
  <https://github.com/zcash/zcash>

- **Zebra (Rust node by Zcash Foundation):**  
  <https://github.com/ZcashFoundation/zebra>

- **Halo 2 (proof system):**  
  <https://github.com/zcash/halo2>

These are your reference points for “how it actually works in code”.

---

## Stage 5: Running a Zcash Node

Running your own node is how you move from theory to **trust-minimized practice**.

### zcashd vs Zebra

- **zcashd**  
  - C++  
  - Maintained by Electric Coin Company  
  - Historically the “reference” implementation  
  - Offers a well-documented JSON-RPC interface

- **Zebra (zebrad)**  
  - Rust  
  - Maintained by Zcash Foundation  
  - Aiming for specification compliance, robustness, and diversity  
  - Node implementation only (no built-in wallet like zcashd)

For learning and development, **zcashd** is a good starting point because of:

- Extensive docs
- Built-in wallet (for simple experiments)
- Mature RPC interface

### Installing zcashd (Example: Ubuntu/Debian)

> **Note:** Always confirm latest installation instructions from:  
> <https://zcash.readthedocs.io/> or linked docs from <https://z.cash/>

#### 1. Install Dependencies

```bash
sudo apt update
sudo apt install -y build-essential pkg-config libc6-dev m4 \
    g++-multilib autoconf libtool ncurses-dev unzip git \
    python3-zmq zlib1g-dev sudo curl
```

(Exact dependencies may vary slightly by version.)

#### 2. Clone and Build zcashd

```bash
git clone https://github.com/zcash/zcash.git
cd zcash

# Check out a tagged release (recommended)
git checkout v5.8.0   # Example; use latest stable release tag

./zcutil/fetch-params.sh   # Downloads zk-SNARK parameters (big files)
./zcutil/build.sh -j$(nproc)
```

This will take some time.

#### 3. Create Configuration

Create a config file at `~/.zcash/zcash.conf`:

```ini
rpcuser=zcashrpc
rpcpassword=change_this_to_a_strong_password
rpcallowip=127.0.0.1
listen=1
server=1
txindex=1
addnode=mainnet.z.cash
```

> **Security note:**  
> Never expose `rpcuser`/`rpcpassword` or RPC port to the internet directly.

#### 4. Start zcashd

```bash
./src/zcashd -daemon
```

Check status:

```bash
./src/zcash-cli getblockchaininfo
```

Wait while it downloads the blockchain.

### Basic zcash-cli Commands

From the zcash source directory (or add to PATH):

```bash
# Check blockchain sync status
zcash-cli getblockchaininfo

# Get node info
zcash-cli getnetworkinfo

# Generate a new unified address (if supported by your version)
zcash-cli z_getnewaccount
zcash-cli z_listaccounts

# Example: get a unified address for an account
zcash-cli z_getaddressforaccount 0
```

To view your addresses and balances:

```bash
# List transparent and shielded addresses
zcash-cli listaddresses

# Check balances
zcash-cli z_gettotalbalance
```

To send a shielded transaction (simplified example):

```bash
zcash-cli z_sendmany \
  "YOUR_SENDER_ADDRESS" \
  '[{"address": "RECIPIENT_ADDRESS", "amount": 0.1}]'
```

The command returns an operation ID; you can check its status:

```bash
zcash-cli z_getoperationresult
```

> **Tip:** Use the official docs for the exact RPC calls and parameters matching your zcashd version.

---

## Stage 6: Developing on Zcash

Once you’re comfortable running a node, you can start **building tools**.

### Development Approaches

1. **Node-Centric (zcashd JSON-RPC):**
   - Run your own full node
   - Talk to it via JSON-RPC over HTTP
   - Best for backends, explorers, admin tools

2. **Light Client / Wallet-Centric (lightwalletd):**
   - Use **lightwalletd** and light client libraries
   - Ideal for mobile wallets and user-facing apps

3. **Direct Integration with Crypto Libraries:**
   - Use Rust crates like `librustzcash`, `orchard`, `halo2`
   - For low-level protocol work and research

### Using zcashd’s JSON-RPC

The RPC interface is documented at:

- <https://zcash.readthedocs.io/en/latest/rtd_pages/json_rpc_api.html>  
  (URL may change; search “Zcash JSON RPC API” if needed.)

You can call it with `curl`:

```bash
curl --user zcashrpc:YOUR_PASSWORD \
  --data-binary '{
    "jsonrpc": "1.0",
    "id": "curltest",
    "method": "getblockchaininfo",
    "params": []
  }' \
  -H 'content-type: text/plain;' \
  http://127.0.0.1:8232/
```

Example response (simplified):

```json
{
  "result": {
    "chain": "main",
    "blocks": 2260000,
    "headers": 2260000,
    "verificationprogress": 0.9999,
    "pruned": false
  },
  "error": null,
  "id": "curltest"
}
```

### Sample Python Script: Querying zcashd

Here is a minimal Python example using `requests`:

```python
import requests
from requests.auth import HTTPBasicAuth

RPC_USER = "zcashrpc"
RPC_PASSWORD = "change_this_to_a_strong_password"
RPC_URL = "http://127.0.0.1:8232/"

def rpc_call(method, params=None):
    if params is None:
        params = []
    payload = {
        "jsonrpc": "1.0",
        "id": "python-client",
        "method": method,
        "params": params
    }
    response = requests.post(
        RPC_URL,
        json=payload,
        auth=HTTPBasicAuth(RPC_USER, RPC_PASSWORD)
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise Exception(data["error"])
    return data["result"]

if __name__ == "__main__":
    info = rpc_call("getblockchaininfo")
    print("Chain:", info["chain"])
    print("Blocks:", info["blocks"])

    balance = rpc_call("z_gettotalbalance")
    print("Total balance:", balance)
```

You can extend this to:

- List recent transactions
- Monitor incoming payments to a shielded address
- Build a simple dashboard

### Light Clients and lightwalletd

For wallets and user-facing apps, you usually **don’t want** to bundle a full node.

Instead, you can:

- Use **lightwalletd**, a service that:
  - Indexes Zcash blockchain data
  - Exposes it via gRPC to light clients
- Use or study light client implementations for:
  - Synchronizing note commitment trees
  - Scanning for your notes with viewing keys
  - Constructing and sending shielded transactions

Key resources:

- **lightwalletd GitHub:**  
  <https://github.com/zcash/lightwalletd>

- Explore implementations used by:
  - YWallet
  - Zingo!
  - Zashi  
  (Check their GitHub repos for protocol usage and APIs.)

### Developer-Focused Resources

- **zcashd RPC Docs:**  
  <https://zcash.readthedocs.io/en/latest/rtd_pages/json_rpc_api.html>

- **Zebra (for Rust devs):**  
  <https://github.com/ZcashFoundation/zebra>

- **Rust crypto crates (for deep devs):**
  - `librustzcash`: <https://github.com/zcash/librustzcash>
  - `halo2`: <https://github.com/zcash/halo2>
  - `orchard`: Often found under ECC repos or as part of `librustzcash` modules

---

## Stage 7: Advanced / “Hero” Track

At this level, you’re aiming to:

- Understand **protocol internals** deeply
- Read and reason about **cryptographic constructions and proofs**
- Potentially **contribute to Zcash** itself

### Deep Protocol Mastery

1. **Read the Zcash Protocol Specification Carefully**

   - Work through the NU5 spec:
     - Addressing schemes and encoding
     - Note commitments and nullifiers
     - Merkle trees and note commitment trees
     - Transaction structure and serialization

2. **Compare Spec vs Implementations**

   - Correlate sections of the spec with code in:
     - `zcashd` (C++)
     - `librustzcash` (Rust)
   - Techniques:
     - Search for function names that mirror spec terms
     - Look for tests named after ZIPs or protocol components

3. **Understand Orchard and Halo 2**

   - Focus on:
     - How Orchard circuits enforce balance and non-double-spend
     - How Halo 2 avoids trusted setup (proof recursion, etc.)

### Cryptography & Research Papers

Key papers and references:

- **Zerocash Paper:**  
  *Zerocash: Decentralized Anonymous Payments from Bitcoin*  
  - <https://zerocash-project.org/media/pdf/zerocash-extended-20140518.pdf>

- **Original zk-SNARK / Pinocchio-related Papers**  
  - For foundations on SNARK constructions (search: “Pinocchio: nearly practical verifiable computation”)

- **Halo Papers (for Halo 2 context):**
  - *Halo: Recursive Proof Composition without a Trusted Setup*  
    - Search for authors Sean Bowe, Jack Grigg, Daira Hopwood
  - Follow-on material for Halo 2 (ECC blog and GitHub issues)

- **Security & Privacy Analyses:**
  - Academic papers analyzing Zcash privacy in practice  
    - Search: “empirical analysis of Zcash privacy”

### Contributing to Zcash

Ways to get involved:

1. **Code Contributions**

   - `zcashd`: <https://github.com/zcash/zcash/issues>
   - `zebra`: <https://github.com/ZcashFoundation/zebra/issues>
   - `librustzcash` and related libraries

   Look for:
   - “good first issue” tags
   - Documentation or test improvements

2. **ZIPs and Specifications**

   - Read existing ZIP