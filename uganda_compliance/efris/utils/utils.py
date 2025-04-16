
import json
import frappe
from frappe import _
from frappe.utils import get_bench_path
import logging
import frappe
from base64 import b64encode
from io import BytesIO
import qrcode
from frappe import _
from PIL import Image
import numpy as np
import base64


class HandledException(frappe.ValidationError): pass

bench_path = get_bench_path()

#Lets handle the logging using 
# log_folder_path = os.path.join(bench_path, 'logs')

# os.makedirs(log_folder_path, exist_ok=True)

# log_file_path = os.path.join(log_folder_path, 'efris_logfile.log')


# Configure logging
logger = logging.getLogger(__name__)
# if not logger.hasHandlers():
#     handler = logging.FileHandler(log_file_path)
#     formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     handler.setFormatter(formatter)
#     logger.addHandler(handler)
#     logger.setLevel(logging.DEBUG)

def safe_load_json(message):
    try:
        json_message = json.loads(message)
    except Exception:
        json_message = message

    return json_message

def efris_log_info(message):
    frappe.logger().info(message)
    

def efris_log_warning(message):
    frappe.msgprint(_("Warning: ") + message, alert=True, indicator='orange')

def efris_log_error(message):
    frappe.log_error("efris_log_error", message)

def format_amount(amount):
    amt_float = float(amount)    
    amt_string = "{:.2f}"
    return amt_string.format(amt_float)

def test_job():
    print("Test job executed!")
    
@frappe.whitelist()
def get_qr_code(data: str) -> str:
    """Generate QR Code data

    Args:
        data (str): The information used to generate the QR Code

    Returns:
        str: The QR Code.
    """
    qr_code_bytes = get_qr_code_bytes(data)
    base_64_string = bytes_to_base64_string(qr_code_bytes)

    return add_file_info(base_64_string)

def add_file_info(data: str) -> str:
    """Add info about the file type and encoding."""
    return f"data:image/png;base64, {data}"

def get_qr_code_bytes(data: bytes | str) -> bytes:
    """Create a QR code and return the bytes without using BytesIO."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_array = np.array(img)
    
    img_pil = Image.fromarray(img_array)
    
    bytes_list = []
    img_pil.save(BytesArrayEncoder(bytes_list), format='PNG')
    
    return b''.join(bytes_list)

def bytes_to_base64_string(data: bytes) -> str:
    """Convert bytes to a base64 encoded string."""
    return base64.b64encode(data).decode("utf-8")

class BytesArrayEncoder:
    def __init__(self, byte_list):
        self.byte_list = byte_list
        
    def write(self, b):
        self.byte_list.append(b)
        
# @frappe.whitelist()
# def get_qr_code(data: str) -> str:
#     """Generate QR Code data

#     Args:
#         data (str): The information used to generate the QR Code

#     Returns:
#         str: The QR Code.
#     """
#     qr_code_bytes = get_qr_code_bytes(data, format="PNG")
#     base_64_string = bytes_to_base64_string(qr_code_bytes)

#     return add_file_info(base_64_string)


# def add_file_info(data: str) -> str:
#     """Add info about the file type and encoding.

#     This is required so the browser can make sense of the data."""
#     return f"data:image/png;base64, {data}"

# def get_qr_code_bytes(data: bytes | str, format: str = "PNG") -> bytes:
#     """Create a QR code and return the bytes."""
#     img = qrcode.make(data)

#     buffered = BytesIO()
#     img.save(buffered, format=format)

#     return buffered.getvalue()


# def bytes_to_base64_string(data: bytes) -> str:
#     """Convert bytes to a base64 encoded string."""
#     return b64encode(data).decode("utf-8")
