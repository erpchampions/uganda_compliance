# EFRIS Integration — Refactor Plan

## Current state — observations from the code

The integration is functional but has accumulated significant technical debt.

- **`efris_api.py`** is the only transport, but `make_post` does too much: settings lookup, key load, AES-key handshake, encrypt, sign, send, decrypt, log. Returns a `(bool, str|dict)` tuple — the entire codebase pattern-matches on this everywhere with `if success:` / `frappe.throw(response)`.
- **`get_AES_key`** is called *on every single request* — an extra round-trip + an RSA decrypt per `make_post`. URA's session key is reusable for the device session.
- **Doctype hooks do real network I/O synchronously inside `before_save` / `on_submit`** (e.g. `before_save_item` posts T130 to URA). A network failure rolls back the user's UI save — that's why "Failed to upload item to EFRIS" surfaces as a `ValidationError`. EFRIS is an *external* system; coupling user transactions to URA latency is the root architectural issue.
- **Print statements + `frappe.log` for diagnostics** (`Mode post URl is ...`) — these go to stdout and pollute the bench logs. Should be `efris_log_info`.
- **No timeout on `requests.post`** in `request_utils.py` — a stalled URA can hang the worker indefinitely.
- **Two near-identical `e_invoicing_settings` imports** at the top of `efris_api.py` and `request_utils.py`.
- **`fetch_data()` builds a global request envelope as a fresh dict each call**, but it hardcodes `dataExchangeId="9230489223014123"`, `tin="1017460267"`, `deviceNo="1017460267_01"` etc. — values are then overwritten in `encrypt_and_prepare_data`. Defaults are misleading and look like a real customer's TIN.
- **Encryption uses AES-ECB and SHA-1 with PKCS1v15** — URA's spec, not a choice, but worth wrapping with comments noting it's protocol-mandated.
- **`e_invoice.py` is 1,522 lines** mixing transport calls, ERPNext doc orchestration, validation, and credit-note logic. Obvious extraction target.
- **`(success, response)` tuple convention is leaky** — every call site re-formats the error and `frappe.throw(response)`. The transport already knows it failed; error handling is duplicated 30+ times.
- **No retry / idempotency layer.** `scheduler_events` re-runs T109 retries, but there's no `dataExchangeId` deduplication — a network blip mid-response can result in URA accepting a duplicate FDN.
- **`E Invoice Request Log` is the only audit trail and writes from inside `make_post`.** It's only written *after* a parse — if `resp["returnStateInfo"]["returnMessage"]` raises a `KeyError` (HTML 502 page from URA), nothing gets logged.

## Refactor plan

### Phase 1 — Foundations (no behavior change)

1. **Create `uganda_compliance/efris/client/`** as the new home for transport. Move:
   - `efris_api.py` → `client/transport.py`
   - `encryption_utils.py` → `client/crypto.py`
   - `request_utils.py` → `client/envelope.py` (request envelope) + `client/http.py` (just `post_req`).
   - `api_classes/` becomes `services/` (business flows only — no crypto, no HTTP).

2. **Introduce a typed result object** to replace `(bool, str|dict)`:
   ```python
   @dataclass
   class EfrisResponse:
       ok: bool
       interface_code: str
       data: dict | None
       error_code: str | None
       error_message: str | None
       request_id: str  # dataExchangeId
       log_name: str    # E Invoice Request Log name
   ```
   Callers stop re-throwing strings; they call `response.raise_for_error()` which raises a typed `EfrisError(interface_code, return_code, message, log_name)`.

3. **Always log, even on parse failure.** Wrap `send_request_and_handle_response` so the request envelope, raw response text, and any exception are persisted to `E Invoice Request Log` *before* parsing. Today a 502 from URA produces no log row.

4. **Set `requests` timeout + retry policy.** Use a `requests.Session` with `urllib3.util.Retry` (idempotent retries on 502/503/504 only), and a configurable timeout (default 30s connect, 60s read) read from `E Invoicing Settings`.

5. **Replace `print` / `frappe.log("Mode post URl ...")` with structured logging.** Use a single namespaced logger (`frappe.logger("efris", file_count=5)`); add `interfaceCode` + `dataExchangeId` to every record.

### Phase 2 — Transport correctness

6. **Cache the AES session key** per `(company, mode)` in `frappe.cache()` with TTL = URA's session lifetime (typically 8h; expose as setting). Today every `make_post` does a T104 handshake first. This will cut ~50% of round-trips.

7. **Generate a fresh `dataExchangeId` per call** and persist it on the log row *before* sending. On retry, re-use the same `dataExchangeId` so URA can dedupe — that's how the protocol is supposed to work. Today it's a hardcoded constant in `fetch_data`.

8. **Centralize "is URA happy?"** — one function reads `returnStateInfo.returnCode` + `returnMessage` and the per-interface `partialSuccess` array. EFRIS T130/T109 batch endpoints return `Partial failure!` with per-row reasons buried in `data.content` — surface those in `EfrisError.partial_failures` so callers can show the *actual* reason ("commodityCategoryId not found") instead of `Partial failure!`.

9. **Move all `make_post` calls behind a per-interface client**:
   ```python
   client = EfrisClient(company)
   client.upload_goods(items)            # T130
   client.query_goods(item_code)         # T144
   client.submit_invoice(invoice_dict)   # T109
   client.cancel_invoice(fdn)            # T110
   client.upload_stock_in(entries)       # T131
   ```
   Each method takes typed input, returns typed output, and knows its `interfaceCode`. The string codes stop leaking into business logic.

### Phase 3 — Decouple from doc events (the biggest win)

10. **Stop blocking user saves on URA round-trips.** Currently `before_save_item` synchronously posts T130; if URA is slow/down, the user can't save an Item. Move all outbound EFRIS calls to **background jobs** (`frappe.enqueue`) with status fields on the source doc:
    - `efris_sync_status`: `Pending` → `In Progress` → `Synced` / `Failed`
    - `efris_last_error`, `efris_last_attempt`, `efris_attempts`
    - The existing scheduler retry logic (`efris_invoice_sync`, `efris_synchronization_center`) becomes the *primary* path, not the retry path.
    - For Sales Invoice submission specifically, EFRIS pre-submit may still be required by business rules — keep that one synchronous but with a circuit breaker (see #12).

11. **Idempotency keys on every business doc.** Items get a stable `efris_dedup_key`; invoices already have a unique `name`. Background workers always re-query (T144 / EFRIS invoice query) before posting, so a retry after a partial failure doesn't double-create. Right now `query_item_before_post` is best-effort and only sometimes called.

12. **Circuit breaker.** If URA returns 5 consecutive `returnCode != "00"` for a given `interfaceCode` within a window, short-circuit and queue everything. Resets on first success. Prevents cascading user-facing errors during URA outages.

### Phase 4 — Code organization

13. **Split `e_invoice.py` (1,522 lines).** Suggested split:
    - `services/sales_invoice/build.py` — payload construction (current `prepare_*` functions).
    - `services/sales_invoice/submit.py` — T109 orchestration.
    - `services/sales_invoice/cancel.py` — T110 / cancellation confirmation.
    - `services/sales_invoice/credit_note.py` — credit note application.
    - `services/sales_invoice/hooks.py` — the thin `on_submit_sales_invoice` etc. wrappers registered in `hooks.py`.
    - Same treatment for `e_goods_services.py` and `stock_in.py`.

14. **Extract `e_invoicing_settings` resolver into a context object.** Today every function calls `get_e_company_settings(company)` and then unpacks 6 fields. Replace with `EfrisCompanyContext(company)` that lazy-loads + caches per-request, exposes typed properties, and is the single place that knows about sandbox vs production switching.

15. **Remove dead/duplicate code.** `stock_entry_detail.json` and `stock_entry_details.json` both exist in `efris/custom/` — one is unused. `pyproject.toml`'s Python version vs README. The hardcoded test TIN in `fetch_data`. Audit `# F401, F841` ruff ignores — investigate rather than silence.

### Phase 5 — Testing & observability

16. **Add a `tests/transport/` suite with a recorded-response fixture** (vcrpy or hand-crafted JSON). Today `tests/` has integration tests that require a real bench but no transport-layer unit tests. The crypto round-trip + envelope construction can be tested without URA.

17. **Add a contract test per `interfaceCode`** that pins the JSON shape of request payloads (so changing `prepare_goods_upload` doesn't silently break URA submission).

18. **Expose an admin page** ("EFRIS Diagnostics") that lists: last 50 logs grouped by interfaceCode, success rate per company, current circuit breaker state, AES-key expiry. Today operators have to read raw `E Invoice Request Log` rows.

## Critical files

- `efris/api_classes/efris_api.py` — split into `client/transport.py` + typed result.
- `efris/api_classes/encryption_utils.py` — move to `client/crypto.py`, no behavior change but document URA-mandated AES-ECB / SHA-1 / PKCS1v15.
- `efris/api_classes/request_utils.py` — split envelope from HTTP; add timeout & retry.
- `efris/api_classes/e_invoice.py` — 1,522-line split into 5 modules.
- `efris/api_classes/e_goods_services.py` — extract `before_save_item` flow into a queued job; the synchronous path is the source of the current user-visible failure.
- `hooks.py` — the `doc_events` handlers should become 3-line wrappers that enqueue jobs, not run them.

## Architectural trade-offs

- **Async-by-default has a UX cost**: users no longer get immediate feedback that "Item registered with EFRIS." Mitigation: show a status badge on the form + a "Retry now" button. URA's reliability does not justify coupling it to user transactions.
- **Typed exceptions vs tuple returns** is a breaking internal API change — every call site needs updating. Worth doing in one PR with `git grep "make_post"` (~30 sites) so the codebase is uniform.
- **Caching the AES key** introduces a state failure mode (stale key → 401). Mitigation: on first decrypt failure, invalidate cache and retry once with a fresh handshake.
- **Phase 3 (queue everything) is the biggest behavior change** and requires coordinating with finance ops — they need to know that "Sales Invoice submitted ≠ FDN issued." Recommend doing Phases 1–2 first as a non-breaking refactor, then proposing Phase 3 with stakeholders.

## Suggested rollout

1. **PR 1 (Phase 1, ~500 LOC change, no behavior diff):** folder restructure, typed `EfrisResponse`, always-log, timeout/retry. Ship behind no flag — pure refactor.
2. **PR 2 (Phase 2):** AES key cache, `dataExchangeId` per call, partial-failure surfacing. The "Partial failure!" item-upload bug becomes "Item X: commodityCategoryId 30101 not registered for TIN Y" — fixes the current bug as a side effect.
3. **PR 3 (Phase 4):** split `e_invoice.py`. Pure mechanical extraction.
4. **PR 4 (Phase 3):** introduce queues + status fields behind a per-company toggle (`async_mode` on E Invoicing Settings); migrate companies one at a time.
5. **PR 5 (Phase 5):** tests + diagnostics page.
