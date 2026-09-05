import frappe
import json
import base64
from .encryption_utils import encrypt_aes_ecb, decrypt_aes_ecb, get_AES_key, get_private_key, sign_data, _gunzip_if_needed
from .request_utils import fetch_data, post_req
from uganda_compliance.efris.doctype.e_invoice_request_log.e_invoice_request_log import log_request_to_efris
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings, get_mode_private_key_path,get_mode_post_url

def make_post(interfaceCode, content, company_name, reference_doc_type=None, reference_document=None, encrypt=True):
    try:
        # Fetch company settings
        e_settings = get_e_company_settings(company_name)
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

        encrypted_data = encrypt_and_prepare_data(content, aes_key, interfaceCode, tin, device_no, brn, private_key, data, encrypt=encrypt)
        if not encrypted_data:
            return False, "Failed to encrypt and prepare data"

        # Send the request and handle the response      
       
        response = send_request_and_handle_response(encrypted_data, aes_key, mode_post_url, content, reference_doc_type, reference_document, encrypted=encrypt)
        return response

    except Exception as e:
        frappe.log_error(f"An error occurred while making post request: {e}")
        return False, str(e)

def encrypt_and_prepare_data(content, aes_key, interfaceCode, tin, device_no, brn, private_key, data, encrypt=True):
    try:
        json_content = json.dumps(content)

        if encrypt:
            isAESEncrypted = encrypt_aes_ecb(json_content, aes_key)
            isAESEncrypted = base64.b64decode(isAESEncrypted)
        else:
            # interfaces marked "Request Encrypted: N" (T123/T124 commodity
            # categories, T115 dictionary): content is still base64 ("regardless
            # of encryption" per the spec) but codeType 0 = plain text
            isAESEncrypted = json_content.encode("utf-8")
        newEncrypteddata = base64.b64encode(isAESEncrypted).decode("utf-8")

        if isAESEncrypted:
            data["globalInfo"]["deviceNo"] = device_no
            data["globalInfo"]["tin"] = tin
            data["globalInfo"]["brn"] = brn
            data["globalInfo"]["interfaceCode"] = interfaceCode
            data["data"]["content"] = base64.b64encode(isAESEncrypted).decode("utf-8")
            data["data"]["dataDescription"] = ({"codeType": "1", "encryptCode": "2"} if encrypt
                                               else {"codeType": "0", "encryptCode": "0", "zipCode": "0"})

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

def send_request_and_handle_response(data_json, aes_key, mode_post_url, content, reference_doc_type, reference_document, encrypted=True):
    try:
        json_resp = post_req(data_json, mode_post_url)
        resp = json.loads(json_resp)

        errorMsg = resp["returnStateInfo"]["returnMessage"]
        if errorMsg != "SUCCESS":
            log_request_to_efris(
                request_data=content,
                request_full=data_json,
                response_data={"error": errorMsg},
                response_full=resp,
                reference_doc_type=reference_doc_type,
                reference_document=reference_document
            )
            return False, errorMsg

        # Decrypt the response content
        respcontent = resp["data"]["content"]
        if encrypted and resp["data"].get("dataDescription", {}).get("codeType") != "0":
            efris_response = decrypt_aes_ecb(aes_key, respcontent)
        else:
            # plain responses may still arrive gzip-compressed (zipCode 1)
            efris_response = _gunzip_if_needed(base64.b64decode(respcontent)).decode("utf-8")

        resp_json = json.loads(efris_response)

        # Log the request and response
        log_request_to_efris(
            request_data=content,
            request_full=data_json,
            response_data=json.loads(efris_response),
            response_full=resp_json,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document
        )
        return True, resp_json
    except Exception as e:
        frappe.log_error(f"An error occurred while sending request and handling response: {e}")
        return False, str(e)
