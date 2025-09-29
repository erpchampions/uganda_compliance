# uganda_compliance/uganda_compliance/pos_send_efris.py

import frappe
from frappe import _
from uganda_compliance.efris.api_classes.pos_einvoice  import send_to_efris 

# @frappe.whitelist()
# def pos_invoice_flags(docname):
#     """Check if POS Invoice is eligible for EFRIS submission"""
#     try:
#         # Clean the docname (remove any extra whitespace/characters)
#         docname = str(docname).strip()
        
#         # First try to get the document
#         if not frappe.db.exists("POS Invoice", docname):
#             # Try to find similar documents if exact match fails
#             similar_docs = frappe.db.sql("""
#                 SELECT name 
#                 FROM `tabPOS Invoice` 
#                 WHERE name LIKE %s 
#                 ORDER BY creation DESC 
#                 LIMIT 5
#             """, f"%{docname.split('-')[-1]}%", as_dict=True)
            
#             if similar_docs:
#                 frappe.log_error(
#                     f"POS Invoice {docname} not found. Similar documents: {[d.name for d in similar_docs]}",
#                     "EFRIS Docname Resolution"
#                 )
            
#             return {
#                 "error": f"POS Invoice {docname} not found",
#                 "similar_docs": [d.name for d in similar_docs] if similar_docs else []
#             }
        
#         doc = frappe.get_doc("POS Invoice", docname)
        
#         return {
#             "efris_invoice": doc.get("efris_invoice", False),
#             "efris_posted": doc.get("efris_posted", False),
#             "status": doc.get("docstatus", 0),
#             "docname": doc.name,  # Return the actual docname found
#             "success": True
#         }
        
#     except frappe.DoesNotExistError:
#         # Log the error for debugging
#         frappe.log_error(f"DoesNotExistError: POS Invoice {docname} not found", "EFRIS Docname Error")
#         return {"error": f"POS Invoice {docname} not found"}
        
#     except Exception as e:
#         # Log unexpected errors
#         frappe.log_error(f"Error checking invoice flags for {docname}: {str(e)}", "EFRIS Flags Error")
#         return {"error": f"Error checking invoice flags: {str(e)}"}

@frappe.whitelist()
def pos_invoice_flags(docname):
    """Check if POS Invoice is eligible for EFRIS submission"""
    try:
        docname = str(docname).strip()
        
        if not frappe.db.exists("POS Invoice", docname):
            similar_docs = frappe.db.sql("""
                SELECT name 
                FROM `tabPOS Invoice` 
                WHERE name LIKE %s 
                ORDER BY creation DESC 
                LIMIT 5
            """, f"%{docname.split('-')[-1]}%", as_dict=True)
            
            if similar_docs:
                frappe.log_error(
                    f"POS Invoice {docname} not found. Similar documents: {[d.name for d in similar_docs]}",
                    "EFRIS Docname Resolution"
                )
            
            return {"eligible": False, "error": f"POS Invoice {docname} not found"}
        
        doc = frappe.get_doc("POS Invoice", docname)
        
        # Define eligibility criteria
        is_eligible = (
            doc.get("efris_invoice", False) and  # Must be marked for EFRIS
            not doc.get("efris_posted", False) and  # Must not already be posted
            doc.docstatus == 1  # Must be submitted
        )
        
        return {
            "eligible": is_eligible,
            "efris_invoice": doc.get("efris_invoice", False),
            "efris_posted": doc.get("efris_posted", False),
            "status": doc.docstatus,
            "docname": doc.name,
            "success": True
        }
        
    except frappe.DoesNotExistError:
        frappe.log_error(f"DoesNotExistError: POS Invoice {docname} not found", "EFRIS Docname Error")
        return {"eligible": False, "error": f"POS Invoice {docname} not found"}
        
    except Exception as e:
        frappe.log_error(f"Error checking invoice flags for {docname}: {str(e)}", "EFRIS Flags Error")
        return {"eligible": False, "error": f"Error checking invoice flags: {str(e)}"}

@frappe.whitelist()
def send_pos_to_efris(docname):
    """Send POS Invoice to EFRIS"""
    try:
        docname = str(docname).strip()
        
        if not frappe.db.exists("POS Invoice", docname):
            return {"status": "error", "error": f"POS Invoice {docname} not found"}
            
        doc = frappe.get_doc("POS Invoice", docname)
        
        # Check eligibility
        if not doc.get("efris_invoice"):
            return {"status": "error", "error": "Invoice not marked for EFRIS"}
            
        if doc.get("efris_posted"):
            return {"status": "already_posted", "message": "Invoice already posted to EFRIS"}
        
        # Check if invoice is submitted
        if doc.docstatus != 1:
            return {"status": "error", "error": "Invoice must be submitted before sending to EFRIS"}
        
        send_to_efris(doc)        
        
        # For now, simulate successful submission
        frappe.log_error(f"EFRIS submission simulated for {docname}", "EFRIS Simulation")
        
       
        
        return {
            "status": "success", 
            "message": "Successfully sent to EFRIS (simulated)",
            "docname": doc.name
        }
        
    except Exception as e:
        frappe.log_error(f"EFRIS Submission Error for {docname}: {str(e)}", "EFRIS Submission")
        return {"status": "error", "error": str(e)}

