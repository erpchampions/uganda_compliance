# `tillking-v15` branch: EFRIS for Till King POS tenants

Frappe v15.108 / ERPNext v15.108.3. This branch is the pinned `uganda_compliance` line for the
Till King tenant bench. Do not merge it into `develop`, `version-15` or `master` without review
by the EFRIS owner.

## 1. Branch decision (28 Sep 2026)

| Branch | Tip | Relation to `develop` | What it adds | Verdict |
|---|---|---|---|---|
| `develop` | 2026-09-22 `cc4f451` (ERP Champions) | — | Newest SI fixes: UoM/commodity codes, export invoicing, multi-tax category, credit-note auto-submit off, `efris_flag` on all-EFRIS items. **HEAD is uninstallable** (`dit[project]` in `pyproject.toml`). | **Base** |
| `pos_invoice` (underscore) | 2026-05-18 `511cfc4` (Mugula Abbey) | forked from `develop@c5edc51`, 9 ahead / 1 behind | POS Invoice path through the shared `E Invoice` (`source_doctype`), POS custom fields, `send_pos_invoice_to_efris`, discount-percentage sync, request/encryption refactor | **Merged** (clean merge). This is what FB-Fashions ran (sandbox/UAT only). |
| `pos-invoice` (hyphen) | 2026-06-30 `27bf2be` (erpchampions) | forked 2025-07-23, 6 ahead / 16 behind | Separate `POS E Invoice` doctype family + POS page button (`pos_send_efris.js`). Installed at MOGAS for the SI path. | Not merged: parallel design, far behind. Ported only the consolidated-invoice guard from `27bf2be`. |
| `version-15` | 2025-07-23 | 12 merge commits, 16 behind | Release snapshot of develop (what `bench-ecl-v15` runs) | Superseded by develop |
| `erpchamps` | 2025-01-29 | 3 ahead / 134 behind | Early UoM/commodity work | Obsolete |
| `efris-import` | 2026-07-04 | unrelated history | Ignite Digital `efris` app for v16 / Python 3.14 | Reference only (third-party) |
| `version-16` | 2026-06-17 | 55 ahead / 16 behind | v16 port (`requires-python >=3.14`, frappe 16) | Not for v15 |

Most recent production use: the Sales Invoice path of `develop`/`pos-invoice` (MOGAS, Medequip).
The POS path has only run against the URA sandbox (FB-Fashions UAT, 17 POS e-invoices, May–Jun 2026).

## 2. What this branch changes

* **Background submission with retry** (`efris/efris_queue.py`). POS Invoice (always) and Sales
  Invoice (setting *Sales Invoice EFRIS Submission* = Background, default) are flagged
  `efris_status = Pending` on submit and sent by a `default`-queue job
  (`job_id` per invoice, `deduplicate`, `enqueue_after_commit`). The sale never waits for URA.
  * Failure: `efris_status = Failed`, `efris_attempts`, `efris_last_error`, `efris_next_retry`
    (15 min doubling, max 12 h) and an `E Invoice Request Log` with `status = Failed`.
  * Hourly `retry_pending_efris_submissions` re-queues due Failed and stale Pending invoices until
    *Max EFRIS Submission Attempts* (default 8). "Send to EFRIS"/"Retry EFRIS" still works after that.
  * Idempotency: the job claims the invoice (§5), skips invoices that already have an FDN (or, for a
    return, a credit note application); on a retry it first looks the invoice up at URA (T106 by
    seller reference = invoice name, T108 for details) and adopts that FDN instead of sending again.
* **POS returns / cancel.** A submitted POS return sends the T110 credit note application (same code
  as Sales Invoice credit notes, now source-doctype aware) and waits if the original is not fiscalised
  yet. The hourly `check_credit_note_approval_status` (was daily and broken) polls T111 for Sales and
  POS returns; approval stores the credit-note FDN and marks the original *EFRIS Cancelled* when fully
  reversed; rejection flags the return (`EFRIS Credit Note Rejected`, `efris_status = Failed`).
  Cancelling a fiscalised invoice is blocked (`before_cancel`): make a Return instead.
* **Endpoints** `send_to_efris`, `send_pos_invoice_to_efris`, `generate_irn`, `cancel_irn`,
  `confirm_irn_cancellation`: check permission, then load the invoice by name (a client-sent doc is
  reduced to its name), POST only, rate limited. `get_e_company_settings` is no longer whitelisted;
  forms use `get_e_company_client_settings` (flags only, Company read permission).
* **80 mm receipt** `EFRIS POS Receipt 80mm` (POS Invoice): FDN, verification code, QR, device no,
  original FDN on credit notes, and clear *EFRIS PENDING* / *CREDIT NOTE PENDING URA APPROVAL* /
  *SANDBOX* states. Data comes from the Jinja method `efris_receipt_data(doc)`.
* **Provisioning** `uganda_compliance.tillking.configure_efris / set_efris_mode / get_efris_config`.
* Sandbox-run fixes: request logs are written after commit (they were lost for new items/invoices,
  which breaks credit notes), `efris_registered` is persisted (every item save re-uploaded it),
  UGX documents no longer call T121, no bogus `''` key-password default, and every HTTP call to URA
  is logged as `EFRIS POST <interface> -> <url>` in `logs/uganda_compliance.efris_http.log`.
* Fixes: `pyproject.toml` parse error and pins below Frappe 15.108's Pillow/pyOpenSSL; FB-Fashions
  fields removed from the POS fixture; form JS via `doctype_js`; per-request settings cache (the old
  per-process cache kept sandbox settings after a mode switch); `efris_log_info` writes to
  `logs/uganda_compliance.log` instead of creating an Error Log per call.

## 3. Provisioning

```bash
# sandbox at provisioning (EFRIS stays disabled until ops upload the key + password)
bench --site <tenant> execute uganda_compliance.tillking.configure_efris \
  --kwargs "{'company': '<Company>', 'tin': '<TIN>', 'device_no': '<TIN>_01', 'output_vat_account': '<VAT account>'}"
# go-live (requires live key + password; runs a T119 TIN lookup; raises and keeps sandbox on failure)
bench --site <tenant> execute uganda_compliance.tillking.set_efris_mode \
  --kwargs "{'company': '<Company>', 'mode': 'Production'}"
bench --site <tenant> execute uganda_compliance.tillking.get_efris_config --kwargs "{'company': '<Company>'}"
```

Keys/passwords are uploaded in *E Invoicing Settings* by ops; they are never command-line arguments.

## 4. Known gaps

* URA sandbox run (28 Sep 2026, see `artifacts/tillking/efris-sandbox/RESULT.md`): T109, T110, T111,
  T106 and T108 field names used by the code were confirmed against the real sandbox. Credit-note
  *approval* (T111 `approveStatus` 101 → T108 of the credit note) was not exercised: the sandbox
  application stays at 102 until approved on the URA portal.
* URA rejects a Seller Reference No. already used under the TIN ("Invoice(s)/receipt(s) (...) with the
  same Seller's Reference Number have already been issued"), including references issued by other
  systems on the same TIN. References are therefore `<seller_reference_prefix>-<invoice name>`
  (prefix generated per E Invoicing Settings) and fixed on the invoice before the first attempt.
  A tenant migrating from another EFRIS system on the same TIN keeps the generated prefix.
* The Point-of-Sale page (Past Orders) has no EFRIS button/badge yet; the retail pack should call
  `send_pos_invoice_to_efris(name=...)` / `get_efris_status`.
* Pre-existing, not changed here: `uganda_compliance/patches.txt` is empty, so
  `set_source_doctype_on_einvoices` (listed only in the repo-root `patches.txt`) never runs; the
  Company and Customer custom fields files carry `custom_perms` that replace ERPNext's role
  permissions on those doctypes (Sales User loses Company read); private `.p12` keys are committed
  under `uganda_compliance/tests/test_keys` and `tests/test-keys`.

## 5. Changes on `chore/p2p3-ci` (28 Sep 2026)

* **No row lock during the URA call.** The job claims the invoice (`efris_status = Submitting`,
  `efris_attempts + 1`, lease in `efris_next_retry` = job timeout + 60 s) and commits; the E Invoice
  is committed before the call; the result is recorded afterwards. A second job or a manual resend
  sees a live claim and returns `in_progress`; an expired claim (worker killed) is re-queued by the
  hourly sweep and starts with a T106 lookup, so an invoice is never fiscalised twice. Cancelling an
  invoice while it is `Submitting` is refused. A failed attempt leaves a draft E Invoice, reused by
  the next attempt.
* **Permission checks:** `get_e_tax_template` (Company read + read on the template;
  *Purchase Tax* now reads the Purchase template), `check_efris_flag_for_sales_invoice` (Sales
  Invoice read; `is_return="0"` is false). `create_item_tax_templates` and the
  `e_invoicing_settings.before_save` wrapper are no longer whitelisted; the wrapper and its duplicate
  doc_event are removed (E Invoicing Settings' own `before_save` runs once per save).
* **One Failed request log per rejected invoice** (was two: `make_post`'s and the queue's). The queue
  still logs failures that never reached URA (transport errors, original not fiscalised yet).
* **Tax Category belongs to ERPNext again.** The app shipped an identical copy of ERPNext's DocType
  under module EFRIS, so the DocType record pointed at this app: `bench uninstall-app
  uganda_compliance` would have deleted ERPNext's Tax Category DocType and table (links from Customer,
  Supplier, Address, Tax Rule, Item Tax), module profiles blocking EFRIS hid it, and every migrate
  re-imported both copies. The copy is removed; the pre-model-sync patch
  `restore_erpnext_tax_category` sets the module back to Accounts and reloads ERPNext's definition
  (records are untouched). The fixture now ships only the `Default` and `Foreign` categories used by
  export invoicing (not a customer's `fixed Assest`).
* **CI** `.github/workflows/tillking-ci.yml` (push to `tillking-v15` / `chore/p2p3-ci`, PRs into
  `tillking-v15`): ruff 0.8.1 lint + format check on Python files changed against the base (new
  files and files that were clean must pass; legacy files that already failed must not get more
  lint errors), then tests on Frappe v15.108.0 + ERPNext v15.108.3. The legacy `ci.yml` (develop,
  unpinned Frappe, no ERPNext) no longer runs for PRs into `tillking-v15`.

