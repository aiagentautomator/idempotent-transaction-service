# Architecture & Design Note
## Forward Deployed Engineer (FDE L2) Practical Assessment
### System: Idempotent Background Transaction Processing Service

---

## 1. Executive Summary & Objective

In enterprise integration and financial systems, background transaction services regularly consume events from asynchronous producers (webhooks, message queues, CSV file ingestions, retrying microservices). These events arrive **out of order**, contain **duplicate payloads**, and suffer **transient network faults**.

This design note documents the implementation of an **Idempotent Background Transaction Processing Service** built to satisfy the FDE L2 assessment criteria:
1. **Strict Idempotency:** Guaranteeing exactly-once business effects across duplicates, replays, and retries.
2. **Causal Ordering Resolution:** Handling out-of-order sequence arrival via non-blocking account-level priority staging.
3. **Resilience & Transient Recovery:** Managing retry budgets and isolated failure containment without cascading batch corruption.
4. **Auditability & Observability:** Providing lifecycle state tracking, structured logs, and operational summary metrics.

---

## 2. High-Level Architecture & Component Decomposition

The service is decoupled into four distinct layers following Clean Architecture / Ports and Adapters:

```
                      ┌────────────────────────────────────────┐
                      │        Input Ingestion Sources         │
                      │  (JSON File, CSV File, Mock Queue)     │
                      └───────────────────┬────────────────────┘
                                          │
                                          ▼
                      ┌────────────────────────────────────────┐
                      │        Transaction Validator           │
                      │ (Schema, Positive Amount, Sequence)    │
                      └───────────────────┬────────────────────┘
                                          │
                        ┌─────────────────┴─────────────────┐
                        ▼                                   ▼
              [ Validation Fails ]                [ Validation Passes ]
                        │                                   │
                        ▼                                   ▼
              Mark Status: FAILED                 ┌─────────────────────────────┐
              Record Isolation (No crash)         │    Idempotency Manager      │
                                                  │ (Check Request & Txn Store) │
                                                  └──────────────┬──────────────┘
                                                                 │
                                          ┌──────────────────────┴──────────────────────┐
                                          ▼                                             ▼
                                  [ Is Duplicate ]                             [ Is Unique ]
                                          │                                             │
                                          ▼                                             ▼
                                 Mark Status: DUPLICATE                        Register IN_FLIGHT
                                 Return Cached Response                        ┌──────────────────────────────┐
                                                                               │    Sequence Ordering Engine   │
                                                                               │    (Seq == Expected + 1 ?)    │
                                                                               └──────────────┬───────────────┘
                                                                                              │
                                                       ┌──────────────────────────────────────┴──────────────────────────────────────┐
                                                       ▼                                                                             ▼
                                              [ Seq > Expected ]                                                            [ Seq == Expected ]
                                                       │                                                                             │
                                                       ▼                                                                             ▼
                                              Status: PENDING                                                               Execute Ledger Update
                                              Hold in Waiting Buffer                                                        Advance Last Processed Seq
                                                                                                                                     │
                                                                                                                                     ▼
                                                                                                                            [ Check Waiting Buffer ]
                                                                                                                            Drain consecutive seqs!
```

### Component Breakdown
1. **Ingestion Adapters (`src/adapters/`):** Polymorphic readers (`JsonIngestionAdapter`, `CsvIngestionAdapter`, `MockQueueAdapter`) implementing `BaseIngestionAdapter`. Ingestion is agnostic of business logic (L2-FR-10).
2. **Transaction Validator (`src/engine/validator.py`):** Enforces mandatory schema presence, positive currency amounts, and positive sequences (L2-FR-02).
3. **Idempotency Manager (`src/engine/idempotency_manager.py`):** Protects against duplicate executions at both the **network/transport level** (`requestId`) and **business entity level** (`transactionId`) (L2-FR-05, L2-FR-06).
4. **Sequence Buffer (`src/engine/sequence_buffer.py`):** Holds premature records in memory or persistent staging until antecedent sequence numbers arrive (L2-FR-07).
5. **Retry Handler (`src/engine/retry_handler.py`):** Simulates transient network partitions, coordinates retries up to `maxRetries`, and escalates exhausted records to `FAILED` (L2-FR-08, L2-FR-09).
6. **Persistence Store (`src/storage/sqlite_store.py`):** ACID-compliant open-source relational store implementing `BaseStorage` for zero-configuration, cross-platform reproducibility.

---

## 3. Idempotency & Duplicate Detection Strategy

Duplicate requests typically arise from two primary scenarios in enterprise pipelines:
1. **At-Least-Once Delivery Replay:** A message broker (e.g. SQS, Kafka) re-delivers message `REQ-2` due to an unacknowledged timeout.
2. **Client Retries:** A client timeout triggers a resend with the same business `transactionId`.

### Two-Tier Deduplication Mechanism
* **Tier 1: Request Idempotency Key (`requestId`)**
  * When a request arrives, the `idempotency_keys` table is queried.
  * If found with status `COMPLETED`, the previous response payload is returned immediately with status `DUPLICATE`. The ledger balance and sequence counter are **never touched**.
* **Tier 2: Business Identifier (`transactionId`)**
  * Even if an upstream system generates a new `requestId` (e.g. `REQ-2-DUP`), the underlying business transaction `TXN-2002` is validated against the transaction store.
  * If `TXN-2002` already exists in `PROCESSED` or `PENDING` status, the second event is tagged `DUPLICATE` and safely rejected.

---

## 4. Out-of-Order Handling Strategy (Sequence Buffer)

### Chosen Strategy: Option A (Sequence-Based Processing)
As outlined in Section 9.5 of the assessment specification, Option A provides deterministic consistency for accounting ledgers.

### The Algorithm:
1. Every account maintains an atomic pointer: `lastProcessedSequence`.
2. The expected sequence is deterministically defined as:
   $$\text{Expected Next Sequence} = \text{lastProcessedSequence} + 1$$
3. When event with sequence $N$ arrives:
   * **If $N == \text{Expected}$:** The transaction is processed immediately. `lastProcessedSequence` is incremented.
   * **If $N > \text{Expected}$:** A sequence gap exists (e.g. Seq 2 arrived before Seq 1). The transaction is transitioned to **`PENDING`** and parked in the account's pending buffer.
   * **If $N \le \text{lastProcessedSequence}$:** The event is stale or already applied; marked `DUPLICATE`.
4. **Cascading Drain:** Immediately following any successful execution of sequence $E$, the engine checks whether sequence $E+1$ is waiting in the buffer. If present, it pops the record, executes it, and recursively drains the queue until the next gap is reached.

---

## 5. Resilience, Failure Handling & Retries

### Transient vs. Permanent Failures
* **Permanent Failures (e.g. Negative Amount, Malformed JSON):**
  * Immediately tagged **`FAILED`** (L2-FR-02).
  * Isolated: They do **not** abort the batch or corrupt adjacent records (L2-FR-12).
* **Transient Failures (e.g. Network Timeout, Lock Contention):**
  * Flagged for simulated fault testing (`simulateTransientError=True`).
  * Transitioned to **`RETRY_PENDING`** (L2-FR-04).
  * Retried with state tracked via `retryCount` (L2-FR-08).
  * When retry succeeds, it completes without duplicate balance side-effects (L2-FR-09).
  * If `retryCount >= maxRetries`, the status permanently locks to **`FAILED`** (Dead Letter Queue candidate).

---

## 6. Observability & Operational Reporting

Operational visibility is mandatory for enterprise customer-facing engineers (L2-FR-11):
1. **Status Lifecycle:** Every record moves strictly through documented states:
   $$\text{RECEIVED} \longrightarrow \text{PENDING} \longrightarrow \text{PROCESSING} \longrightarrow \text{PROCESSED} \;\Big|\; \text{DUPLICATE} \;\Big|\; \text{RETRY\_PENDING} \;\Big|\; \text{FAILED}$$
2. **Structured Logging:** Standard logging format captures timestamp, log level, transaction ID, sequence number, and balance delta.
3. **Execution Summary Report:** Outputs an operational scorecard detailing total throughput, status counts, final account ledger balances, and audit reasons (`processing_summary_report.json`).

---

## 7. AI-Assisted Development Reflection

In alignment with FDE core principles, AI was leveraged as an accelerator rather than an unquestioned authority:
* **Scaffolding & Spec Translation:** AI assisted in rapidly generating initial boilerplate, Pydantic type definitions, and test fixtures from the requirements document.
* **Critical Review & Verification:** AI-generated suggestions were audited to verify that:
  * Global vs. Account-level sequence partitioning was explicitly addressed (ensuring test data from Table 4 matched while maintaining modular account partitioning).
  * SQLite schema utilized proper `UNIQUE` constraints and atomic transactions (`BEGIN TRANSACTION ... COMMIT`).
  * Idempotency was validated at both `requestId` and `transactionId` layers.

---

## 8. Production Hardening Recommendations (Next Steps)

For deployment in a distributed cloud environment (e.g. Kubernetes, AWS, GCP), the following enhancements would be applied:
1. **Distributed Idempotency & Locking:** Replace single-process locks with Redis Redlock or database row locks (`SELECT ... FOR UPDATE`) per `accountId` to permit multi-node concurrent consumers.
2. **Message Broker Partitioning:** Configure Kafka or AWS Kinesis to partition messages by `accountId`. This ensures all events for a given account naturally hit the same consumer partition in chronological order, reducing buffer pressure.
3. **Buffer Timeouts & Dead Letter Queues (DLQ):** Implement a TTL on `PENDING` buffer items (e.g., 5 minutes). If a missing sequence never arrives, alert operational teams and dump the orphan record to a DLQ for manual reconciliation.
4. **Outbox Pattern:** Publish ledger events downstream via a transactional outbox table to guarantee dual-write consistency across microservices.

