import json
import requests
import uuid
from datetime import datetime
import pytz
from uganda_compliance.efris.utils.utils import efris_log_info

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

def post_req(data, sandbox_mode):
    efris_log_info(f"post_req()...starting, sandbox_mode:{sandbox_mode}")
    
    if sandbox_mode:
        url = "https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation"
    else:
        url = "https://efris.ura.go.ug/efrisws/ws/taapp/getInformation"

    headers = {"Content-Type": "application/json"}
    response = requests.post(url, data=data, headers=headers)
    print(response.text)
    efris_log_info("post_req()...done, response:" + response.text)
    return response.text

def get_ug_time_str():
    ug_time_zone = "Africa/Kampala"
    now = datetime.now()
    uganda_time = now.astimezone(pytz.timezone(ug_time_zone))
    uganda_time_str = uganda_time.strftime("%Y-%m-%d %H:%M:%S")
    return uganda_time_str
