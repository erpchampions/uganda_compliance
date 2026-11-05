import frappe
import json
import base64
import zlib
from .encryption_utils import encrypt_aes_ecb, decrypt_aes_ecb, get_AES_key, get_private_key, sign_data
from .request_utils import decode_plain_content, fetch_data, post_req
from uganda_compliance.efris.doctype.e_invoice_request_log.e_invoice_request_log import log_request_to_efris
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import (
    get_e_company_settings,
    get_enabler_access_token,
    get_mode_private_key_path,
    get_mode_post_url,
    is_offline_enabler,
)
from ..utils.utils import efris_log_error

RETURN_CODE_SUCCESS = "00"
# URA/enabler: an invoice with this Seller Reference No. was already uploaded under the TIN
RETURN_CODE_ALREADY_UPLOADED = "2253"


class EfrisRejection(str):
    """URA's (or the enabler's) returnMessage, as make_post has always returned it, carrying
    returnCode too so callers can branch on the code instead of parsing the message."""

    def __new__(cls, message, return_code=None):
        obj = super().__new__(cls, message or "")
        obj.return_code = str(return_code or "").strip()
        return obj


class EfrisAlreadyUploaded(frappe.ValidationError):
    """T109 refused with 2253: the seller reference is taken at URA (maybe by our own lost attempt)."""


def is_already_uploaded(response):
    return getattr(response, "return_code", None) == RETURN_CODE_ALREADY_UPLOADED


def with_rejection_details(message, data, aes_key=None):
    """URA's top-level message for a rejected batch call (T130 "Partial failure!") hides the
    reason: it is per row, inside ``data.content``. Append each failed row's returnMessage.
    ``content`` is AES-encrypted when dataDescription.encryptCode is "2" (Online), else plain."""
    content = (data or {}).get("content")
    if not content:
        return message
    try:
        if aes_key and str((data.get("dataDescription") or {}).get("encryptCode")) == "2":
            decoded = json.loads(decrypt_aes_ecb(aes_key, content))
        else:
            decoded = decode_plain_content(data)
    except (ValueError, TypeError, IndexError, zlib.error):
        # unreadable content: URA's own message is all we have
        return message
    rows = decoded if isinstance(decoded, list) else [decoded]
    reasons = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("returnCode") or "").strip()
        reason = row.get("returnMessage")
        if reason and reason != "SUCCESS" and code != RETURN_CODE_SUCCESS:
            label = row.get("goodsCode") or row.get("referenceNo")
            reasons.append(f"{label}: {reason}" if label else reason)
    return f"{message} {'; '.join(reasons)}" if reasons else message


def make_post(interfaceCode, content, company_name, reference_doc_type=None, reference_document=None):
    try:
        # Fetch company settings
        e_settings = get_e_company_settings(company_name)
        if is_offline_enabler(e_settings):
            # The enabler holds the key: no T104, no AES, no signing, private key never loaded.
            return post_plain(interfaceCode, content, e_settings, reference_doc_type, reference_document)

        tin, device_no, private_key_path, sandbox_mode, brn,mode_post_url = (
            e_settings.tin,
            e_settings.device_no,
            get_mode_private_key_path(e_settings),
            e_settings.sandbox_mode,
            e_settings.brn,
            get_mode_post_url(e_settings)
        )
        brn = brn if brn else ""
    
        data = fetch_data()

        private_key = get_private_key(private_key_path, e_settings)

        aes_key = get_AES_key(tin, device_no, private_key, mode_post_url, brn)
        if not aes_key:
            msg = (
                f"Failed to obtain the EFRIS AES key for company '{company_name}' "
                f"(TIN {tin}, device {device_no}). See the 'efris_log_error' Error Log "
                f"for the underlying cause (EFRIS rejection, empty T104 response, or key mismatch)."
            )
            frappe.log_error(msg, "EFRIS get_AES_key failed")
            return False, msg

        encrypted_data = encrypt_and_prepare_data(content, aes_key, interfaceCode, tin, device_no, brn, private_key, data)
        if not encrypted_data:
            return False, "Failed to encrypt and prepare data"

        # Send the request and handle the response      
       
        response = send_request_and_handle_response(encrypted_data, aes_key, mode_post_url, content, reference_doc_type, reference_document, interfaceCode)
        return response

    except Exception as e:
        efris_log_error(f"An error occurred while making post request: {e}")
        return False, str(e)

def encrypt_and_prepare_data(content, aes_key, interfaceCode, tin, device_no, brn, private_key, data):
    try:
        json_content = json.dumps(content)

        isAESEncrypted = encrypt_aes_ecb(json_content, aes_key)

        isAESEncrypted = base64.b64decode(isAESEncrypted)
        newEncrypteddata = base64.b64encode(isAESEncrypted).decode("utf-8")

        if isAESEncrypted:
            data["globalInfo"]["deviceNo"] = device_no
            data["globalInfo"]["tin"] = tin
            data["globalInfo"]["brn"] = brn
            data["globalInfo"]["interfaceCode"] = interfaceCode
            data["data"]["content"] = base64.b64encode(isAESEncrypted).decode("utf-8")
            data["data"]["dataDescription"] = {"codeType": "1", "encryptCode": "2"}

            # Sign the data
            signature = sign_data(private_key, newEncrypteddata.encode())

            if signature:
                b4signature = base64.b64encode(signature).decode()
                data["data"]["signature"] = b4signature

            # Convert the final data to JSON
            data_json = json.dumps(data).replace("'", '"').replace("\n", "").replace("\r", "")
            
            return data_json
        return None
    except Exception as e:
        frappe.log_error(f"An error occurred while encrypting and preparing data: {e}")
        return None

def send_request_and_handle_response(data_json, aes_key, mode_post_url, content, reference_doc_type, reference_document, interface_code=None):
    try:
        json_resp = post_req(data_json, mode_post_url)
        resp = json.loads(json_resp)

        errorMsg = resp["returnStateInfo"]["returnMessage"]
        if errorMsg != "SUCCESS":
            errorMsg = with_rejection_details(errorMsg, resp.get("data"), aes_key)
            log_request_to_efris(
                request_data=content,
                request_full=data_json,
                response_data={"error": errorMsg},
                response_full=resp,
                reference_doc_type=reference_doc_type,
                reference_document=reference_document,
                status="Failed",
                interface_code=interface_code,
                error_message=errorMsg,
            )
            return False, EfrisRejection(errorMsg, resp["returnStateInfo"].get("returnCode"))

        # Decrypt the response content
        respcontent = resp["data"]["content"]
        efris_response = decrypt_aes_ecb(aes_key, respcontent)

        resp_json = json.loads(efris_response)

        # Log the request and response
        log_request_to_efris(
            request_data=content,
            request_full=data_json,
            response_data=json.loads(efris_response),
            response_full=resp_json,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document,
            status="Success",
            interface_code=interface_code,
        )
        return True, resp_json
    except Exception as e:
        frappe.log_error(f"An error occurred while sending request and handling response: {e}")
        return False, str(e)


def post_plain(interface_code, content, e_settings, reference_doc_type=None, reference_document=None):
    """Unencrypted envelope: content = base64(JSON), no signature. Used for every call to the
    Offline Enabler and for T101 (server time) in both modes. Returns (ok, response dict | message)."""
    data = fetch_data()
    data["globalInfo"].update(
        {
            "interfaceCode": interface_code,
            "tin": e_settings.tin,
            "deviceNo": e_settings.device_no,
            "brn": e_settings.brn or "",
        }
    )
    data["data"]["content"] = (
        base64.b64encode(json.dumps(content).encode("utf-8")).decode("ascii") if content is not None else ""
    )
    data_json = json.dumps(data)

    headers = {}
    if is_offline_enabler(e_settings):
        token = get_enabler_access_token(e_settings)
        if token:
            headers["Authorization"] = f"Bearer {token}"

    try:
        resp = json.loads(post_req(data_json, get_mode_post_url(e_settings), headers=headers))
        return_info = resp.get("returnStateInfo") or {}
        return_code = str(return_info.get("returnCode") or "").strip()
        message = return_info.get("returnMessage") or ""
        if return_code != RETURN_CODE_SUCCESS and message != "SUCCESS":
            message = with_rejection_details(
                message or f"EFRIS return code {return_code or '(none)'}", resp.get("data")
            )
            log_request_to_efris(
                request_data=content,
                request_full=data_json,
                response_data={"error": message, "returnCode": return_code},
                response_full=resp,
                reference_doc_type=reference_doc_type,
                reference_document=reference_document,
                status="Failed",
                interface_code=interface_code,
                error_message=message,
            )
            return False, EfrisRejection(message, return_code)
        response = decode_plain_content(resp.get("data"))
    except Exception as e:
        # transport errors, non-JSON bodies, bad base64/gzip: the caller retries (queue)
        efris_log_error(f"EFRIS {interface_code} via {e_settings.get('connection_mode') or 'Online (URA)'} failed: {e}")
        return False, str(e)

    log_request_to_efris(
        request_data=content,
        request_full=data_json,
        response_data=response,
        response_full=resp,
        reference_doc_type=reference_doc_type,
        reference_document=reference_document,
        status="Success",
        interface_code=interface_code,
    )
    return True, response


def get_server_time(company_name):
    """T101 through the company's connection mode (no key needed in either mode)."""
    return post_plain("T101", None, get_e_company_settings(company_name), "E Invoicing Settings", None)
