"""High-level EFRIS transport.

Wraps envelope construction, URA-mandated AES-ECB encryption + SHA-1/PKCS1v15
signing (per protocol spec — not a security choice), HTTP send, and decrypt.

Two entry points:

- `make_post(...)` — typed `EfrisResponse` return; preferred for new code.
- `make_post_legacy(...)` — `(success, response)` tuple; used by the
  `efris_api.make_post` shim so existing call sites don't change.

Compared to the legacy `efris_api.make_post`, this module:

- Always persists a request-log row, even when URA returns an unparseable body
  (HTML error pages, 502 gateways, decrypt failures).
- Uses a pooled `requests.Session` with timeout + 5xx retries.
- Carries a `dataExchangeId` per call for protocol-level idempotency.
- Caches the URA AES session key per (tin, device, mode) — was previously
  re-fetched on every request.
- Decrypts on partial-failure envelopes and surfaces per-row reasons via
  `EfrisResponse.partial_failures`.
"""
import base64
import json

import frappe

from uganda_compliance.efris.api_classes.encryption_utils import (
    decrypt_aes_ecb,
    encrypt_aes_ecb,
    get_AES_key,
    get_private_key,
    sign_data,
)
from uganda_compliance.efris.doctype.e_invoice_request_log.e_invoice_request_log import (
    log_request_to_efris,
)
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import (
    get_e_company_settings,
    get_mode_post_url,
    get_mode_private_key_path,
)

from . import breaker
from . import partial as partial_failures
from . import session as session_cache
from .envelope import build_envelope
from .http import post_req
from .logger import get_logger
from .result import EfrisResponse


def make_post(
    interfaceCode: str,
    content: dict | list,
    company_name: str,
    reference_doc_type: str | None = None,
    reference_document: str | None = None,
) -> EfrisResponse:
    """Send a payload to URA and return a typed result. Always logs."""
    log = get_logger()
    envelope = build_envelope()
    request_id = envelope["globalInfo"]["dataExchangeId"]
    envelope_json: str | None = None
    response_text: str | None = None

    allowed, reason = breaker.allow(company_name, interfaceCode)
    if not allowed:
        log.warning(reason)
        return _fail(
            interfaceCode,
            request_id,
            error_message=reason,
            request_full=None,
            response_full=None,
            content=content,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )

    try:
        e_settings = get_e_company_settings(company_name)
        tin = e_settings.tin
        device_no = e_settings.device_no
        brn = e_settings.brn or ""
        mode_post_url = get_mode_post_url(e_settings)
        private_key_path = get_mode_private_key_path(e_settings)
        private_key = get_private_key(private_key_path, e_settings)

        aes_key, from_cache = _get_aes_key(
            tin, device_no, private_key, mode_post_url, brn
        )
        if not aes_key:
            return _fail(
                interfaceCode,
                request_id,
                error_message="Failed to obtain AES session key from URA (T104)",
                request_full=None,
                response_full=None,
                content=content,
                reference_doc_type=reference_doc_type,
                reference_document=reference_document,
            )

        envelope_json = _encrypt_and_sign(
            content, aes_key, interfaceCode, tin, device_no, brn, private_key, envelope
        )
        if not envelope_json:
            return _fail(
                interfaceCode,
                request_id,
                error_message="Failed to encrypt and prepare data",
                request_full=None,
                response_full=None,
                content=content,
                reference_doc_type=reference_doc_type,
                reference_document=reference_document,
            )

        response_text = post_req(
            envelope_json,
            mode_post_url,
            interface_code=interfaceCode,
            request_id=request_id,
        )

        result = _parse_response(
            response_text=response_text,
            envelope_json=envelope_json,
            aes_key=aes_key,
            interfaceCode=interfaceCode,
            request_id=request_id,
            content=content,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )

        # Stale cached key → invalidate and retry once with a fresh handshake.
        if (
            not result.ok
            and from_cache
            and result.error_message
            and "decrypt" in result.error_message.lower()
        ):
            log.info(
                f"EFRIS retrying after decrypt failure (likely stale AES key) "
                f"interfaceCode={interfaceCode} dataExchangeId={request_id}"
            )
            session_cache.invalidate(tin, device_no, mode_post_url)
            return make_post(
                interfaceCode,
                content,
                company_name,
                reference_doc_type=reference_doc_type,
                reference_document=reference_document,
            )

        if result.ok:
            breaker.record_success(company_name, interfaceCode)
        else:
            breaker.record_failure(company_name, interfaceCode)
        return result

    except Exception as e:
        log.error(
            f"EFRIS transport error interfaceCode={interfaceCode} "
            f"dataExchangeId={request_id}: {e}"
        )
        frappe.log_error(
            title="EFRIS transport error",
            message=f"interfaceCode={interfaceCode} dataExchangeId={request_id}\n"
            f"{frappe.get_traceback()}",
        )
        breaker.record_failure(company_name, interfaceCode)
        return _fail(
            interfaceCode,
            request_id,
            error_message=str(e),
            request_full=envelope_json,
            response_full=response_text,
            content=content,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )


def make_post_legacy(
    interfaceCode: str,
    content: dict | list,
    company_name: str,
    reference_doc_type: str | None = None,
    reference_document: str | None = None,
):
    """Backwards-compatible wrapper returning the legacy `(success, response)` tuple.

    Partial-failure detail (when present) is appended to the error string so
    the legacy `frappe.throw(response)` call sites surface actionable info
    instead of just the bare "Partial failure!" message from URA.
    """
    resp = make_post(
        interfaceCode,
        content,
        company_name,
        reference_doc_type=reference_doc_type,
        reference_document=reference_document,
    )
    if resp.ok:
        return True, resp.data
    msg = resp.error_message or "EFRIS call failed"
    if resp.partial_failures:
        msg = f"{msg}\n{partial_failures.format_summary(resp.partial_failures)}"
    return False, msg


def _get_aes_key(tin, device_no, private_key, mode_post_url, brn):
    """Return (aes_key, from_cache). Cache miss falls through to T104 handshake."""
    cached = session_cache.get_cached(tin, device_no, mode_post_url)
    if cached:
        return cached, True
    aes_key = get_AES_key(tin, device_no, private_key, mode_post_url, brn)
    if aes_key:
        session_cache.set_cached(tin, device_no, mode_post_url, aes_key)
    return aes_key, False


def _encrypt_and_sign(
    content, aes_key, interfaceCode, tin, device_no, brn, private_key, envelope
) -> str | None:
    try:
        json_content = json.dumps(content)
        b64_ciphertext = encrypt_aes_ecb(json_content, aes_key)
        ciphertext = base64.b64decode(b64_ciphertext)
        b64_for_signing = base64.b64encode(ciphertext).decode("utf-8")

        envelope["globalInfo"]["deviceNo"] = device_no
        envelope["globalInfo"]["tin"] = tin
        envelope["globalInfo"]["brn"] = brn
        envelope["globalInfo"]["interfaceCode"] = interfaceCode
        envelope["data"]["content"] = b64_for_signing
        envelope["data"]["dataDescription"] = {"codeType": "1", "encryptCode": "2"}

        signature = sign_data(private_key, b64_for_signing.encode())
        if signature:
            envelope["data"]["signature"] = base64.b64encode(signature).decode()

        return (
            json.dumps(envelope)
            .replace("'", '"')
            .replace("\n", "")
            .replace("\r", "")
        )
    except Exception as e:
        frappe.log_error(f"EFRIS encrypt/sign failed: {e}")
        return None


def _try_decrypt(aes_key, encrypted_content):
    """Best-effort decrypt for partial-failure responses. Returns parsed dict or None."""
    if not encrypted_content:
        return None
    try:
        decrypted = decrypt_aes_ecb(aes_key, encrypted_content)
        return json.loads(decrypted)
    except Exception:
        return None


def _parse_response(
    response_text,
    envelope_json,
    aes_key,
    interfaceCode,
    request_id,
    content,
    reference_doc_type,
    reference_document,
) -> EfrisResponse:
    try:
        resp = json.loads(response_text)
    except Exception as e:
        log_request_to_efris(
            request_data=content,
            request_full=envelope_json,
            response_data={"error": f"Non-JSON response from URA: {e}"},
            response_full=response_text,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )
        return EfrisResponse(
            ok=False,
            interface_code=interfaceCode,
            request_id=request_id,
            error_message=f"Non-JSON response from URA: {e}",
        )

    return_state = resp.get("returnStateInfo") or {}
    return_code = return_state.get("returnCode")
    return_message = return_state.get("returnMessage", "")

    if return_message != "SUCCESS":
        # On partial failure, URA still encrypts per-row detail in data.content.
        # Decrypt best-effort so callers get actionable reasons.
        decoded = _try_decrypt(aes_key, (resp.get("data") or {}).get("content"))
        failures = (
            partial_failures.extract(interfaceCode, decoded)
            if partial_failures.is_partial(return_message)
            else []
        )

        log_request_to_efris(
            request_data=content,
            request_full=envelope_json,
            response_data={
                "error": return_message,
                "returnCode": return_code,
                "decoded": decoded,
                "partial_failures": failures,
            },
            response_full=resp,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )

        error_message = return_message
        if failures:
            error_message = (
                f"{return_message} ({len(failures)} row(s) failed): "
                + "; ".join(
                    f"{f.get('id') or '?'}={f.get('message') or '?'}" for f in failures[:3]
                )
            )

        return EfrisResponse(
            ok=False,
            interface_code=interfaceCode,
            request_id=request_id,
            error_code=return_code,
            error_message=error_message,
            partial_failures=failures,
        )

    try:
        encrypted_content = resp["data"]["content"]
        decrypted = decrypt_aes_ecb(aes_key, encrypted_content)
        decoded = json.loads(decrypted)
    except Exception as e:
        log_request_to_efris(
            request_data=content,
            request_full=envelope_json,
            response_data={"error": f"Decrypt/parse failed: {e}"},
            response_full=resp,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )
        return EfrisResponse(
            ok=False,
            interface_code=interfaceCode,
            request_id=request_id,
            error_message=f"Decrypt/parse failed: {e}",
        )

    log_request_to_efris(
        request_data=content,
        request_full=envelope_json,
        response_data=decoded,
        response_full=decoded,
        reference_doc_type=reference_doc_type,
        reference_document=reference_document,
    )
    return EfrisResponse(
        ok=True,
        interface_code=interfaceCode,
        request_id=request_id,
        data=decoded,
    )


def _fail(
    interfaceCode,
    request_id,
    *,
    error_message,
    request_full,
    response_full,
    content,
    reference_doc_type,
    reference_document,
) -> EfrisResponse:
    """Build a failure response and ensure a log row is written."""
    try:
        log_request_to_efris(
            request_data=content,
            request_full=request_full,
            response_data={"error": error_message},
            response_full=response_full,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
        )
    except Exception as log_err:
        get_logger().error(f"Failed to write E Invoice Request Log: {log_err}")
    return EfrisResponse(
        ok=False,
        interface_code=interfaceCode,
        request_id=request_id,
        error_message=error_message,
    )
