# Idempotent Background Transaction Processing Service
### Practical FDE L2 Assessment Implementation

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Test Suite](https://img.shields.io/badge/pytest-9%20passed-success.svg)](https://docs.pytest.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> A production-aware background transaction processing engine engineered for **strict idempotency**, **causal sequence reordering**, **isolated failure tolerance**, and **resilient retries**.

---

## 🌟 Interactive Live Demo
A visual simulation of this architecture can be opened locally at [`docs/index.html`](docs/index.html) or viewed directly on **GitHub Pages** when hosted!
* **Visualizes:** Real-time Account Balances, the Out-of-Order "Waiting Room" Buffer, and the Live Lifecycle Audit Ledger.

---

## 🏗 System Architecture

```
                  ┌────────────────────────────────────────┐
                  │        Input Ingestion Sources         │
                  │  (JSON File, CSV File, Mock Queue)     │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │        Transaction Validator           │
                  │ (Mandatory Fields, Schema, Validation) │
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
                                                                                                                        [ Drain Waiting Buffer ]
                                                                                                                        Cascading unblock of seqs!
```

---

## 📋 Functional Requirements Coverage

| ID | Assessment Requirement | Implementation Component | Status |
|---|---|---|:---:|
| **L2-FR-01** | Replaceable input source (JSON/CSV/Queue) | `src/adapters/` (JSON, CSV, MockQueue) | ✅ Verified |
| **L2-FR-02** | Validate mandatory fields & reject malformed | `src/engine/validator.py` | ✅ Verified |
| **L2-FR-03** | Maintain transaction state | `src/storage/sqlite_store.py` | ✅ Verified |
| **L2-FR-04** | Status lifecycle (RECEIVED, PENDING, PROCESSED, DUPLICATE, FAILED, RETRY_PENDING) | `src/models.py` | ✅ Verified |
| **L2-FR-05** | Exactly-once business transaction execution | `src/engine/idempotency_manager.py` | ✅ Verified |
| **L2-FR-06** | Duplicate detection across the entire batch | `src/engine/idempotency_manager.py` | ✅ Verified |
| **L2-FR-07** | Out-of-order sequence resolution strategy | `src/engine/sequence_buffer.py` | ✅ Verified |
| **L2-FR-08** | Transient failure simulation | `src/engine/retry_handler.py` | ✅ Verified |
| **L2-FR-09** | Safe retries without duplicate effects | `src/engine/processor.py` | ✅ Verified |
| **L2-FR-10** | Decoupled business logic from input adapters | Modular ports & adapters | ✅ Verified |
| **L2-FR-11** | Processing summary report with status counts | `src/main.py` & JSON report | ✅ Verified |
| **L2-FR-12** | Comprehensive automated unit test suite | `tests/` (9 test suites) | ✅ Verified |

---

## 🚀 Quickstart & Execution Instructions

### 1. Prerequisites
* Python 3.10 or higher.

### 2. Setup Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run Sample Ingestions (Step 2 & 3)

#### Run with JSON Input:
```bash
python src/main.py --format json
```

#### Run with CSV Input:
```bash
python src/main.py --format csv
```

#### Run with Custom Input File:
```bash
python src/main.py --file path/to/your_file.json
```

---

## 🧪 Running Automated Tests (Step 4)

Execute the full automated test suite covering idempotency, ordering, resilience, and validation:

```bash
pytest -v
```

Expected output:
```text
tests/test_idempotency.py::test_idempotent_duplicate_request_id PASSED               [ 11%]
tests/test_idempotency.py::test_idempotent_duplicate_transaction_id_different_request_id PASSED [ 22%]
tests/test_ordering.py::test_out_of_order_buffering_and_cascading_drain PASSED      [ 33%]
tests/test_resilience.py::test_simulated_transient_failure_and_successful_retry PASSED [ 44%]
tests/test_resilience.py::test_retry_exhaustion_leads_to_terminal_failed_state PASSED [ 55%]
tests/test_validation.py::test_reject_negative_amount PASSED                         [ 66%]
tests/test_validation.py::test_reject_zero_amount PASSED                             [ 77%]
tests/test_validation.py::test_reject_invalid_sequence_number PASSED                 [ 88%]
tests/test_validation.py::test_validation_isolation_does_not_block_subsequent_valid_records PASSED [100%]

============================== 9 passed in 0.08s ===============================
```

---

## 📊 Test Verification (Table 4 Walkthrough)

Running the assessment dataset (`data/sample_transactions.json`) produces the following verified execution:

| Step | Transaction ID | Sequence | Account | Type | Amount | Outcome | System Action |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| **1** | `TXN-2002` | 2 | ACC-201 | DEBIT | $40.00 | **PENDING** | Arrived early; parked in buffer waiting for Seq 1 |
| **2** | `TXN-2001` | 1 | ACC-201 | CREDIT | $100.00 | **PROCESSED** | Matched Seq 1; processed and unblocked Seq 2 from buffer |
| **3** | `TXN-2002` | 2 | ACC-201 | DEBIT | $40.00 | **DUPLICATE** | Caught by idempotency key; 0 ledger effect |
| **4** | `TXN-2003` | 3 | ACC-201 | CREDIT | $25.00 | **PROCESSED** | Matches Seq 3; balance becomes $85.00 |
| **5** | `TXN-2004` | 4 | ACC-202 | DEBIT | -$10.00 | **FAILED** | Negative amount rejected; isolated from batch |
| **6** | `TXN-2005` | 5 | ACC-203 | CREDIT | $500.00 | **PROCESSED** | Transient error simulated; retried once and succeeded |

Final Ledger Balances:
* **`ACC-201`:** `$85.00` (Credit 100 - Debit 40 + Credit 25)
* **`ACC-203`:** `$500.00` (Credit 500)

---

## 📁 Repository Structure

```
├── DESIGN.md                   # Detailed Architectural Design Note (FDE L2)
├── README.md                   # System documentation & setup guide
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Pytest configuration
├── data/
│   ├── sample_transactions.json # Assessment sample JSON
│   └── sample_transactions.csv  # Assessment sample CSV
├── src/
│   ├── models.py               # Pydantic data models & status enums
│   ├── main.py                 # CLI execution entrypoint
│   ├── adapters/               # Ingestion adapters (JSON, CSV, MockQueue)
│   ├── engine/                 # Core processing, idempotency, sequence buffer, retry handler
│   └── storage/                # ACID SQLite relational store
├── tests/                      # Automated pytest suite
└── docs/
    └── index.html              # Standalone interactive browser simulation for GitHub Pages
```

---

## 📄 Architectural Design Note
For a comprehensive analysis of the idempotency design, sequence buffer trade-offs, resilience model, and production hardening recommendations, please refer to [`DESIGN.md`](DESIGN.md).

