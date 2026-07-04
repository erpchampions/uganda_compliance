# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this app is

`efris` is a Frappe Framework v16 app for integrating ERPNext with Uganda Revenue Authority's EFRIS (Electronic Fiscal Receipting and Invoicing System) e-invoicing platform.

`efris_erpnext_integration_guide.md` is the technical spec for the integration: EFRIS API protocol (T-codes like T109/T110/T130), the AES/RSA encryption envelope, and how it maps onto ERPNext Sales/Purchase Invoices. Treat it as the source of truth for intended architecture. Note the guide uses the app name `erpnext_efris`; this repo's actual app is `efris`, so import paths are `efris.efris.*`.

### What exists

- `efris/efris/api/crypto.py` — AES-256-ECB encrypt/decrypt, RSA-SHA256 signing, RSA key unwrap (for T104).
- `efris/efris/api/client.py` — `EFRISClient` builds the signed/encrypted envelope, POSTs to URA, validates return codes, decrypts responses. `EFRISError` carries the return code; `IDEMPOTENT_CODES` (1040/306) are treated as success.
- `efris/efris/api/interfaces.py` — typed wrappers per T-code. Simple interfaces (T101/T104/T115/T119/T121/T127/T138) build their own payloads; document-driven ones (T109/T110/T130/T131/T139) take a prebuilt payload.
- `efris/efris/doctype/efris_settings/` — `EFRIS Settings` DocType, one record **per Company** (autonamed by company): credentials, RSA/AES keys, environment, server URL. `test_connection()` (T101) and `fetch_symmetric_key()` (T104) are whitelisted controller methods. Use `get_efris_settings(company)` to resolve a record (defaults to the user/global default company), and `EFRISClient(company=...)` / the `company=` arg on interface wrappers to target a company.

### Not yet built

`overrides/` (Sales Invoice / Item / Stock Entry / Customer doc-event handlers that assemble payloads), `tasks.py` (scheduled syncs + retry queue), `EFRIS Log` DocType, custom fields, and the `hooks.py` wiring. The `aes_key` is obtained at runtime via T104, not stored statically — run `fetch_symmetric_key` before making encrypted calls.

## Working in a Frappe app

This app lives inside a bench at `/Users/admin/frappe/version-16/ignite`. All commands run from the bench directory (`apps/efris` is not standalone — Frappe, the DB, and the test runner are bench-managed).

```bash
# from the bench root: /Users/admin/frappe/version-16/ignite
bench --site <site> install-app efris
bench --site <site> migrate                  # apply schema changes / patches.txt
bench --site <site> console                  # interactive python REPL with frappe loaded
bench --site <site> run-tests --app efris     # run all app tests
bench --site <site> run-tests --module efris.<module>.test_<x>   # single module
bench --site <site> run-tests --doctype "<DocType Name>"         # single doctype
bench build --app efris                       # build public/ JS+CSS assets
```

Architecture conventions when adding code:
- DocTypes go under `efris/efris/doctype/<doctype>/` (module dir is `efris/efris/`, registered in `efris/modules.txt`).
- Wire framework integration points (`doc_events`, `scheduler_events`, `override_whitelisted_methods`, `app_include_js`, etc.) by uncommenting/editing `efris/hooks.py` — the EFRIS submit trigger belongs in `doc_events` on Sales/Purchase Invoice.
- Data-migration scripts go in `efris/patches/` and must be listed in `efris/patches.txt`.
- The EFRIS API client, encryption layer, and retry/queue logic described in the guide are not yet created — place them as new modules under `efris/`.

## Lint & format

Pre-commit runs ruff, eslint, prettier, and pyupgrade. Install once with `pre-commit install` (from `apps/efris`).

- Python: ruff, `target-version = py314`, line length 110, **tabs** for indentation, double-quote strings (see `pyproject.toml`).
- Requires Python >= 3.14.