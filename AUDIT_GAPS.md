# BEAM Subnet 105 — Documentation & Code Audit Gaps

*Audit Date: 2026-04-22*
*Repo: /home/picklesii/.openclaw/workspace/beam-sn105*
*Docs Compared: RESEARCH.md, VALIDATOR_SETUP_PLAN.md, ORCHESTRATOR_SETUP_PLAN.md, CHEAT_SHEET.md*

---

## 1. Files Not Documented

These Python files exist in the repo but are **not mentioned or covered** in any of the four existing docs.

### Orchestrator Side

| File | What It Does | Doc Gap |
|------|--------------|---------|
| `neurons/orchestrator/clients/subnet_core_client.py` | ~2,235-line BeamCore API/WebSocket client for orchestrators. Handles auth, PoB submission, worker registration, payment recording, retry logic, WebSocket fallbacks. | **Not mentioned anywhere.** Setup plans show curl examples but never reference this client. |
| `neurons/orchestrator/db/database.py` | SQLAlchemy database init/connection. Legacy path, being replaced by BeamCore API. | Not mentioned in setup or architecture docs. |
| `neurons/orchestrator/db/models.py` | SQLAlchemy models for `worker_payments`, `payment_proofs`, `epoch_summaries`. | Not mentioned. Setup plans show no DB schema info. |
| `neurons/orchestrator/db/merkle.py` | Merkle tree helpers for payment proofs. | Not mentioned. CHEAT_SHEET only mentions merkle roots in passing. |
| `neurons/orchestrator/middleware/metrics.py` | Prometheus metrics middleware (appears stubbed/incomplete). | No monitoring setup docs. |
| `neurons/orchestrator/middleware/rate_limiting.py` | Rate limiting middleware for orchestrator API. | No rate limiting docs. |
| `neurons/orchestrator/routes/health.py` | Health check route module. | Not mentioned. |
| `neurons/orchestrator/routes/orchestrators.py` | Orchestrator registration/heartbeat routes. | Not mentioned. |
| `neurons/orchestrator/services/__init__.py` | Empty init — placeholder for future services. | Not mentioned. |
| `neurons/orchestrator/core/proof_aggregator.py` | Aggregates PoB proofs into batches/merkle trees for epoch submission. | RESEARCH.md lists it but setup plans never describe how to configure or monitor it. |
| `neurons/orchestrator/core/worker_manager.py` | Manages worker registrations, health checks, worker pool. | RESEARCH.md lists it but no setup config for it. |
| `neurons/orchestrator/__init__.py` | Empty package init. | N/A |
| `neurons/orchestrator/core/__init__.py` | Empty package init. | N/A |
| `neurons/orchestrator/clients/__init__.py` | Empty package init. | N/A |
| `neurons/orchestrator/db/__init__.py` | Empty package init. | N/A |
| `neurons/orchestrator/middleware/__init__.py` | Empty package init. | N/A |
| `neurons/orchestrator/routes/__init__.py` | Empty package init. | N/A |

### Validator Side

| File | What It Does | Doc Gap |
|------|--------------|---------|
| `neurons/validator/clients/subnet_core_client.py` | BeamCore API client for validators. Score submission, proof fetching, audit responses. | **Not mentioned anywhere.** Validators need this to submit scores but setup plan doesn't reference it. |
| `neurons/validator/core/_beam_stubs.py` | ~860-line stub module replacing removed `beam.*` library. Contains critical stubbed crypto and scoring functions. | **Not mentioned.** Contains `verify_hotkey_signature` that always returns `True`. Critical security gap. |
| `neurons/validator/core/redundancy.py` | Validator HA: checkpointing, health monitoring, failover, recovery. | **Not mentioned anywhere.** No docs on how to run redundant validators or recover from crashes. |
| `neurons/validator/chain/fiber_chain.py` | Bittensor chain integration via Fiber. Weight setting, node discovery, commit-reveal. | RESEARCH.md mentions it but setup plan doesn't explain Fiber setup or commit-reveal mechanics. |
| `neurons/validator/chain/tx_verifier.py` | On-chain ALPHA payment verification (`transfer_stake` + `remark_with_event`). | CHEAT_SHEET describes the concept but no validator setup doc references this file. |
| `neurons/validator/chain/__init__.py` | Empty package init. | N/A |
| `neurons/validator/services/__init__.py` | Empty package init. | N/A |
| `neurons/validator/__init__.py` | Empty package init. | N/A |
| `neurons/validator/core/__init__.py` | Empty package init. | N/A |

### Shared / Other

| File | What It Does | Doc Gap |
|------|--------------|---------|
| `beam/__init__.py` | Package init for `beam` shared library. | Not mentioned. |
| `neurons/shared/merkle.py` | Shared merkle tree operations. | RESEARCH.md lists it but no usage docs. |
| `neurons/shared/__init__.py` | Empty package init. | N/A |
| `neurons/worker/__init__.py` | Empty package init. | N/A |

---

## 2. Missing Configuration Parameters

These config parameters exist in code but are **not documented** in any setup plan or cheat sheet.

### Orchestrator Config (`neurons/orchestrator/core/config.py`)

| Parameter | Default | In Code | In Docs? | Risk/Note |
|-----------|---------|---------|----------|-----------|
| `LOCAL_MODE` | `false` | Yes | **No** | Skips wallet/subtensor init. Critical for dev but undocumented. |
| `LOCAL_ORCHESTRATOR_HOTKEY` | `local-dev-hotkey` | Yes | **No** | Only used in local mode. |
| `ADD_MOCK_WORKER` | `false` | Yes | **No** | Adds fake worker for testing. Could leak to production. |
| `MOCK_WORKER_HOTKEY` | `None` | Yes | **No** | Hotkey for mock worker. |
| `CLUSTER_ENABLED` | `false` | Yes | **No** | Enables 192-node federated cluster mode. Major architecture difference. |
| `NODE_ID` | `standalone` | Yes | **No** | Cluster node identity. |
| `REGION` | `US` | Yes | **No** | Orchestrator region for routing. |
| `CLUSTER_UIDS` | `""` | Yes | **No** | Comma-separated UIDs this cluster node handles. |
| `REDIS_CLUSTER_URL` | `None` | Yes | **No** | Redis cluster for shared state. |
| `HEARTBEAT_INTERVAL` | `30` | Yes | **No** | Cluster heartbeat interval. |
| `REBALANCE_THRESHOLD` | `0.3` | Yes | **No** | Cluster rebalancing threshold. |
| `ENABLE_GEO_VERIFICATION` | `true` | Yes | **No** | Anti-fraud geo check. |
| `ENABLE_LATENCY_VERIFICATION` | `true` | Yes | **No** | Anti-fraud latency check. |
| `MAX_SUSPICIOUS_SCORE` | `0.3` | Yes | **No** | Fraud detection threshold. |
| `BLIND_MODE_ENABLED` | `false` | Yes | **No** | Anonymous worker orchestration. Security implications undocumented. |
| `BLIND_CORE_URL` | `None` | Yes | **No** | Blind mode identity broker URL. |
| `BLIND_TRUST_SYNC_INTERVAL` | `60` | Yes | **No** | Blind mode trust score refresh. |
| `BLIND_SUBMIT_TRUST_REPORTS` | `true` | Yes | **No** | Auto-submit trust reports in blind mode. |
| `BLIND_PAYMENT_ROUTING` | `true` | Yes | **No** | Route blind worker payments through Core. |
| `DB_POOL_SIZE` | `10` | Yes | **No** | DB connection pool size. |
| `DB_MAX_OVERFLOW` | `20` | Yes | **No** | DB pool overflow. |
| `WEIGHT_TRUST` / `WEIGHT_LATENCY` / `WEIGHT_LOAD` / `WEIGHT_BANDWIDTH` / `WEIGHT_SUCCESS` | Various | Yes | **No** | Worker selection scoring weights. Tuning these affects worker pool quality. |
| `REWARD_WEIGHT_BYTES` / `REWARD_WEIGHT_SUCCESS_RATE` / `REWARD_WEIGHT_LATENCY` / `REWARD_WEIGHT_TRUST` | Various | Yes | **No** | Epoch-end reward distribution weights. |
| `CLIENT_AUTH_ENABLED` | `true` | Yes | **Partial** | Mentioned in config snippet but no security docs. |
| `CLIENT_WHITELIST_ONLY` | `false` | Yes | **No** | If true, only whitelisted clients can register. |
| `CLIENT_STAKE_GATED_ENABLED` | `true` | Yes | **No** | Self-registration gated by stake. |
| `CLIENT_PRE_APPROVED_HOTKEYS` | `None` | Yes | **No** | Pre-approved client SS58 addresses. |
| `CLIENT_ADMIN_HOTKEYS` | `None` | Yes | **No** | Admin hotkeys for client management. |
| `CLIENT_SIGNATURE_MAX_AGE_SECONDS` | `300` | Yes | **No** | Max age of signed auth challenges. 5-minute replay window. |
| `SUBNET_AUTH_ENABLED` | `true` | Yes | **No** | Auth for validators/workers. |
| `SUBNET_AUTH_REQUIRE_METAGRAPH` | `true` | Yes | **No** | Require metagraph registration for auth. |
| `SUBNET_AUTH_MIN_VALIDATOR_STAKE` | `100.0` | Yes | **No** | Minimum validator stake for auth. |
| `SUBNET_AUTH_MIN_WORKER_STAKE` | `0.0` | Yes | **No** | Minimum worker stake for auth. |
| `SUBNET_AUTH_WHITELIST` | `None` | Yes | **No** | Hotkeys that bypass metagraph check. **Security concern.** |
| `SUBNET_PARTNER_ENABLED` | `true` | Yes | **No** | Free access for other Bittensor subnets. |
| `CLIENT_TIER_BASIC_STAKE` | `10 dTAO` | Yes | **No** | Stake tier thresholds. |
| `CLIENT_TIER_STANDARD_STAKE` | `100 dTAO` | Yes | **No** | Stake tier thresholds. |
| `CLIENT_TIER_PREMIUM_STAKE` | `1000 dTAO` | Yes | **No** | Stake tier thresholds. |
| `AUDIT_ENABLED` | `true` | Yes | **No** | Publish audit events to BeamCore. |
| `AUDIT_REDIS_URL` | `None` | Yes | **No** | Redis for audit event queue. |
| `AUDIT_STREAM` | `audit:events` | Yes | **No** | Redis stream name. |
| `AUDIT_SOURCE` | `datapipe_subnet` | Yes | **No** | Audit source identifier. |

### Validator Config (`neurons/validator/core/config.py`)

| Parameter | Default | In Code | In Docs? | Risk/Note |
|-----------|---------|---------|----------|-----------|
| `WALLET_PATH` | `~/.bittensor/wallets` | Yes | **No** | Wallet directory path. |
| `EXTERNAL_IP` | `None` | Yes | **Partial** | Mentioned in .env snippet but not explained. |
| `EXTERNAL_URL` | `None` | Yes | **Partial** | Mentioned but not explained (used for validator identity). |
| `ORCHESTRATOR_URL` | `http://localhost:8000` | Yes | **No** | Default orchestrator endpoint for v2 validator. |
| `SYNC_INTERVAL` | `12` | Yes | **No** | Metagraph sync interval (blocks). |
| `JOB_TIMEOUT_SECONDS` | `60` | Yes | **No** | Task completion timeout. |
| `DEBUG` | `false` | Yes | **No** | Debug mode flag. |

---

## 3. TODOs and Stubs

### TODO Comments in Code

| Location | Line | TODO Text | Severity |
|----------|------|-----------|----------|
| `neurons/validator/core/validator.py` | ~1071 | `# TODO: Make signatures required once orchestrator signing is implemented` | **HIGH** — PoB signatures are currently optional |
| `neurons/validator/core/validator.py` | ~1191 | `# TODO: Get orchestrator coldkey from metagraph or payment record` | **HIGH** — Payment verification may use wrong coldkey |
| `neurons/orchestrator/core/epoch_manager.py` | ~219 | `# Update BeamCore again with actual merkle root (if different from placeholder)` | **MEDIUM** — Placeholder merkle root may be submitted |

### Stubbed / Placeholder Implementations

| File | Stub | Impact |
|------|------|--------|
| `neurons/validator/core/_beam_stubs.py` | `verify_hotkey_signature()` always returns `True` | **CRITICAL** — All hotkey signatures are accepted without verification. Major security vulnerability. |
| `neurons/validator/core/_beam_stubs.py` | `SLAScorer`, `SLAMetrics`, `SLAScore` are dataclass shells | Validator scoring logic may not match BeamCore exactly. |
| `neurons/validator/core/_beam_stubs.py` | `SybilDetector` is a minimal stub | Sybil detection may not work correctly in validator. |
| `neurons/orchestrator/middleware/metrics.py` | Appears to have placeholder/stub metrics collection | Monitoring may be incomplete. |
| `neurons/orchestrator/middleware/rate_limiting.py` | Rate limiter implementation may be incomplete | DDoS risk if middleware doesn't enforce limits properly. |
| `neurons/orchestrator/core/reward_manager.py` | Payment retry queue logic appears to have stubbed on-chain submission paths | Payment system may fail silently (matches CHEAT_SHEET findings). |
| `neurons/orchestrator/core/task_scheduler.py` | `_save_task_to_core()` has error-swallowing `except Exception` | Task persistence failures are silently logged. |

### Incomplete Implementations

- **Cross-verification service** (`neurons/validator/services/cross_verification.py`) — Referenced in validator main.py endpoints but not fully described in docs. The endpoints return "not available" if the service isn't initialized.
- **Payment verification service** — Referenced in validator main.py but docs don't explain how to enable or configure it.
- **Weight calculator** (`neurons/validator/services/weight_calculator.py`) — Has `_OUTFLOW_ENABLED_DEFAULT` and related params that are declared but not used in the formula shown in docs.

---

## 4. Deployment Gaps

| Gap | Details | Severity |
|-----|---------|----------|
| **No Docker files** | No `Dockerfile`, `docker-compose.yml`, or `.dockerignore` found in repo. | **HIGH** — Manual deployment is error-prone. |
| **No Kubernetes manifests** | No Helm charts, k8s YAML, or deployment configs. | **MEDIUM** — Production orchestration not documented. |
| **No reverse proxy docs for validator** | Orchestrator setup plan includes Nginx config. Validator setup plan does not. | **MEDIUM** — Validator also exposes HTTP API. |
| **No Redis setup in orchestrator docs** | Orchestrator config references `REDIS_URL` and `REDIS_CLUSTER_URL`. Setup plan only covers Redis for validator. | **MEDIUM** — Orchestrator uses Redis for rate limiting, audit queue, and cluster state. |
| **No database setup docs** | Orchestrator has `DATABASE_URL` config and SQLAlchemy models. Setup plan says "legacy, being replaced" but doesn't explain migration path. | **MEDIUM** — Operators may be confused about whether DB is needed. |
| **No log rotation docs** | Both orchestrator and validator log to `/tmp/` directories with no rotation policy. | **MEDIUM** — Disk fill risk on long-running nodes. |
| **No monitoring/alerting setup** | Prometheus metrics middleware exists but no docs on scraping, dashboards, or alerts. | **MEDIUM** — Operators fly blind in production. |
| **CI references non-existent tests** | `.github/workflows/ci.yml` runs `pytest tests/` but `tests/` directory does not exist. | **LOW** — CI will always report test step as passing (continue-on-error) but this masks the fact that tests are missing. |
| **No secrets management** | Wallet paths and API keys are passed via environment variables. No docs on secret management best practices. | **MEDIUM** — Risk of credential leakage in shell history, process lists. |
| **No firewall rules for validator** | Orchestrator plan includes UFW rules. Validator plan only mentions port 8093. No mention of restricting access to validator API. | **MEDIUM** — Validator API may be exposed unnecessarily. |
| **pyproject.toml dev deps** | References `[dev]` extras with pytest/black/ruff/mypy. Setup plans install packages manually instead of using `pip install -e ".[dev]"`. | **LOW** — Inconsistent installation instructions. |

---

## 5. Security Gaps

| Gap | Details | Severity |
|-----|---------|----------|
| **`verify_hotkey_signature` always returns True** | `neurons/validator/core/_beam_stubs.py:35` — `return True` with comment "Actual signature verification is done by BeamCore". This means the validator's own API endpoints (`/pob/submit`, `/orchestrator/report`, `/payment-proof/submit`) do **not** verify signatures locally. | **CRITICAL** |
| **CORS defaults to empty origins** | `cors_allowed_origins` defaults to `""` (disabled). If an operator sets it to `"*"` without understanding the risk, the API is wide open. No security warning in docs. | **HIGH** |
| **Signature max age = 300s** | `client_signature_max_age_seconds = 300` gives a 5-minute replay window. No docs explain this or recommend shorter windows for production. | **MEDIUM** |
| **`subnet_auth_whitelist` bypasses metagraph** | Any SS58 address in this env var bypasses the metagraph registration check. No docs warn about this. | **HIGH** |
| **Blind mode security implications** | Blind worker mode (`BLIND_MODE_ENABLED`) routes payments through Core and anonymizes workers. No security analysis in docs about trust model changes. | **MEDIUM** |
| **No HTTPS enforcement** | Both orchestrator and validator default to `http://`. Docs don't mention TLS/SSL requirements. | **MEDIUM** |
| **Mock worker in production** | `ADD_MOCK_WORKER` could be accidentally enabled, injecting fake workers into the real pool. | **MEDIUM** |
| **Local mode bypasses auth** | `LOCAL_MODE=true` skips wallet/subtensor initialization. No warning that this disables on-chain security entirely. | **MEDIUM** |
| **No input validation docs** | PoB submissions, orchestrator reports, and payment proofs accept complex payloads. No docs describe validation rules or sanitization. | **MEDIUM** |
| **Wallet hotkey in logs** | `main.py` logs `hotkey` and API keys (truncated). No docs on log sanitization or PII handling. | **LOW** |
| **Audit events enabled by default** | `AUDIT_ENABLED=true` publishes events to a Redis stream. No docs on who consumes this stream or data retention policies. | **LOW** |

---

## 6. Testing Gaps

| Gap | Details | Severity |
|-----|---------|----------|
| **No `tests/` directory exists** | CI workflow runs `pytest tests/` but the directory is missing. | **CRITICAL** |
| **No unit tests for payment system** | `reward_manager.py` and `epoch_manager.py` handle on-chain payments. No tests for retry logic, merkle root generation, or batch call construction. | **HIGH** |
| **No tests for weight calculation** | `weight_calculator.py` implements the emission formula. No tests to verify it matches BeamCore's params_hash. | **HIGH** |
| **No integration tests for BeamCore API** | `subnet_core_client.py` on both sides has no tests for auth, retry, WebSocket fallback, or error handling. | **HIGH** |
| **No tests for SLA scoring** | `redundancy.py`, `_beam_stubs.py` scoring logic has no test coverage. | **MEDIUM** |
| **No tests for cross-verification** | `cross_verification.py` referenced but not tested. | **MEDIUM** |
| **No tests for transaction verification** | `tx_verifier.py` has no tests for ALPHA payment verification. | **MEDIUM** |
| **No tests for worker transfers** | `worker.py` has no test coverage for fetch/send chunk logic, retry behavior, or deadline handling. | **MEDIUM** |
| **CI has `continue-on-error: true`** | Test and type-check steps always pass even if broken. This masks real problems. | **MEDIUM** |
| **No performance/benchmark tests** | No load tests for orchestrator API or validator weight calculation at scale. | **LOW** |

---

## 7. Recommendations

### Priority 1 — Critical (Fix Before Mainnet)

1. **Fix `_beam_stubs.py` signature verification** — `verify_hotkey_signature()` must actually verify signatures using `pynacl` or `bittensor` crypto, not return `True`. Without this, the validator API accepts forged submissions.
2. **Add real tests** — Create a `tests/` directory with unit tests for payment system, weight calculation, and API client retry logic. Remove `continue-on-error: true` from CI or fix the underlying issues.
3. **Document all config parameters** — Both orchestrator and validator configs have ~50+ undocumented parameters. Create a comprehensive `CONFIG_REFERENCE.md`.
4. **Add Docker/deployment configs** — Create `Dockerfile`, `docker-compose.yml`, and sample Kubernetes manifests. Document log rotation and secrets management.

### Priority 2 — High (Fix Before Production)

5. **Document the `subnet_core_client.py` modules** — Both orchestrator and validator have large API clients that are central to operation but completely undocumented.
6. **Document security model** — Explain CORS risks, signature replay windows, blind mode trust model, and `subnet_auth_whitelist` bypass behavior.
7. **Fix TODOs in validator** — Make signatures required and resolve orchestrator coldkey lookup.
8. **Add monitoring/alerting docs** — Explain Prometheus metrics, recommend Grafana dashboards, and provide alert rules for critical conditions (payment failures, compliance drops, WebSocket disconnects).
9. **Document validator redundancy** — `redundancy.py` provides checkpointing and failover but no setup docs exist. Explain how to run redundant validators and recover from checkpoints.

### Priority 3 — Medium (Improve Reliability)

10. **Document tier system and client auth** — The orchestrator has a full stake-based tier system (`basic`/`standard`/`premium`) with rate limits. This is not mentioned in any setup doc.
11. **Add database setup/migration docs** — Even if legacy, operators may need to understand the DB schema for debugging.
12. **Document cluster mode** — `CLUSTER_ENABLED`, `CLUSTER_UIDS`, and `REDIS_CLUSTER_URL` suggest a federated deployment model that is completely undocumented.
13. **Add input validation documentation** — Describe expected payload formats, size limits, and sanitization rules for all public API endpoints.
14. **Document `pyproject.toml` based installation** — Setup plans show manual `pip install` of individual packages. Standardize on `pip install -e ".[validator,dev]"`.

---

*End of Audit*
