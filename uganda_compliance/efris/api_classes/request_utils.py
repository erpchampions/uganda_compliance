import requests
import uuid
from datetime import datetime
import pytz
import frappe
from frappe.model.document import Document
from frappe import _
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error

from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings, get_mode_private_key_path,get_mode_post_url

def fetch_data():
    now = get_ug_time_str()
    return {
        "data": {
            "content": "",
            "signature": "",
            "dataDescription": {
                "codeType": "0",
                "encryptCode": "1",
                "zipCode": "0"
            }
        },
        "globalInfo": {
            "appId": "AP04",
            "version": "1.1.20191201",
            "dataExchangeId": "9230489223014123",
            "interfaceCode": "T101",
            "requestTime": now,
            "requestCode": "TP",
            "responseCode": "TA",
            "userName": "admin",
            "deviceMAC": "FFFFFFFFFFFF",
            "deviceNo": "1017460267_01",
            "tin": "1017460267",
            "brn": "",
            "taxpayerID": "1",
            "longitude": "116.397128",
            "latitude": "39.916527",
            "extendField": {
                "responseDateFormat": "dd/MM/yyyy",
                "responseTimeFormat": "dd/MM/yyyy HH:mm:ss"
            }
        },
        "returnStateInfo": {
            "returnCode": "",
            "returnMessage": ""
        }
    }

def guidv4():
    my_uuid = uuid.uuid4()
    my_uuid_str = str(my_uuid)
    my_uuid_str_32 = my_uuid_str.replace("-", "")
    return my_uuid_str_32

def post_req(data, mode_post_url): 
    frappe.log(f"Mode post URl is {mode_post_url}")   
    if mode_post_url:
        url = mode_post_url    

    headers = {"Content-Type": "application/json"}
    response = requests.post(url, data=data, headers=headers)
    return response.text

def get_ug_time_str():
    ug_time_zone = "Africa/Kampala"
    now = datetime.now()
    uganda_time = now.astimezone(pytz.timezone(ug_time_zone))
    uganda_time_str = uganda_time.strftime("%Y-%m-%d %H:%M:%S")
    return uganda_time_str
