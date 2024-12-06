import frappe
import json
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
from json import loads, dumps, JSONDecodeError
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings

@frappe.whitelist()
def check_efris_item_for_purchase_receipt(accept_warehouse, item_code):
    # Fetch the `is_efris_warehouse` flag from Warehouse
    is_efris_warehouse = frappe.db.get_value('Warehouse', accept_warehouse, 'is_efris_warehouse')

    # Fetch the `is_efris_item` flag from the Item master doctype
    is_efris_item = frappe.db.get_value('Item', item_code, 'is_efris_item')

    # Determine the final value of `is_efris`
    is_efris = bool(is_efris_warehouse and is_efris_item)

    return {'is_efris': is_efris}

def before_save_item(doc, method):
    efris_log_info(f"The Created Item is: {doc}")
    is_import = frappe.flags.in_import
    is_registered_item = doc.get("is_efris_registered", 0)
    if is_import and is_registered_item == 1:
        efris_log_info(f"Excludes EFRIS registered Item {doc.get('item_code')}")        
        return

    is_efris_item = doc.get('is_efris_item')
    if not is_efris_item:
        efris_log_info("Non-Efris item, skipping item registration with EFRIS")
        return

    is_registered_item = doc.get("is_efris_registered", 0)
    efris_log_info(f"The Item's Registration state is: {is_registered_item}")

    has_opening_stock = doc.get("opening_stock",0)
    efris_log_info(f"The Opening Stock Quantity is {has_opening_stock}")
    if has_opening_stock:
        frappe.throw("You Should Not ADD Opening Stock, Opening Stock is Stocked-In to EFRIS Via Stock Reconciliation")

    e_company = doc.get('e_company', '')
    if not is_registered_item:
        query_result = query_item_before_post(doc)
        efris_log_info(f"The Response is :{query_result}")
        if query_result:
            # Item exists in EFRIS, perform update
            efris_log_info("Item found in EFRIS, proceeding with update.")
            update_existing_item(doc, method, e_company)
        else:
            # Item does not exist in EFRIS, perform create
            efris_log_info("Item not found in EFRIS, proceeding with creation.")
            upload_new_item(doc, method, e_company)
    else:
        # If item is registered in ERPNext, it should already be in EFRIS, so update
        update_existing_item(doc, method, e_company)

def query_item_before_post(doc):
    e_company = doc.get('e_company', '')
    item_code = ""
    item_code = doc.get('item_code', '')
    efris_log_info(f"Item Code :{item_code}") 
    goodsCode = frappe.db.get_value("Item",{"item_code":item_code},"efris_product_code")
    efris_log_info(f"EFRIS Product Code is {goodsCode}")
    if goodsCode:
        item_code = goodsCode
    dn_batch_query_goods_T144 = {
        "goodsCode": item_code,
        "tin": get_e_company_settings(e_company).tin
    }
    efris_log_info(f"Querying EFRIS with: {dn_batch_query_goods_T144}")
    success, response = make_post(interfaceCode="T144", content=dn_batch_query_goods_T144, company_name=e_company, reference_doc_type=doc.doctype, reference_document=doc.name)
    
    if success and response:
        efris_log_info(f"Query successful, response: {response}")
        return response  # Assuming response contains information if item exists
    else:
        efris_log_info("Item not found in EFRIS.")
        return None

def upload_new_item(doc, method, e_company):
    prepare_and_upload_item(doc, method, operation_type="101", e_company=e_company)  # 101 for new item

def update_existing_item(doc, method, e_company):
    prepare_and_upload_item(doc, method, operation_type="102", e_company=e_company)  # 102 for update item

def prepare_and_upload_item(doc, method, operation_type, e_company):
    is_efris_item = doc.get('is_efris_item',0)
    goodsCode = ""
    item_code = ""
    if not is_efris_item:
        efris_log_info(f"Item Is Non Efris {is_efris_item}")
        return
    goodsName = doc.get('item_name', '')    
    item_code = doc.get('item_code', '')
    efris_log_info(f"Item Code :{item_code}") 
    goodsCode = doc.get('efris_product_code')
   
    efris_log_info(f"EFRIS Product Code is {goodsCode}")
    if goodsCode and  len(goodsCode) > 50:
        frappe.throw(f"The EFRIS Product Code cannot exceeds 50 characters.")
    if goodsCode:
        item_code = goodsCode
    hasOtherUnits = doc.get('has_multiple_uom', 0)
    efris_log_info(f"The Item Has Multiple UOM flag is set to: {hasOtherUnits}") 
    item_currency = doc.get('efris_currency','')
    efris_log_info(f"The Item Currency is {item_currency} ")
    if item_currency:
        currency = frappe.db.get_value('Currency',{'currency_name':item_currency},'efris_currency_code')
        efris_log_info(f"Efris Currency Code is {currency}")
     # Fetch the default unit price
    if item_currency == 'UGX':
        unitPrice = str(doc.get('standard_rate'))
        if unitPrice == '0.0':
            frappe.throw("Standard Rate cannot be zero")
    else:
        unitPrice = str(doc.get('uoms', [])[0].get('efris_unit_price', 0))
        efris_log_info(f"The Unit Price is {unitPrice}")
        

    # Fetch the default UOM (measureUnit)
    uom = doc.get('stock_uom', '')
    measureUnit = frappe.db.get_value('UOM', {'uom_name': uom}, 'efris_uom_code') or ''
    
    if measureUnit == '':
        frappe.throw(f"EFRIS UOM code must not be empty on Default UOM: {uom}")
    
    commodityCategoryId = doc.get('efris_commodity_code', '')
    efris_log_info(f"The Company Name is: {e_company}")

    goodsOtherUnit = []  # This will store non-default, non-piece UOMs
    pieceMeasureUnit = ''  # Piece unit measure
    pieceUnitPrice = ''    # Piece unit price
    pieceScaledValue = ''  # Piece unit conversion factor
    havePieceUnit = "102"  # Default to no piece unit
    if hasOtherUnits:
        for item_uom in doc.get('uoms', []):
            # Extract the necessary flags
            custom_efris_package_unit = item_uom.get('custom_efris_package_unit', 0)
            is_efris_uom = item_uom.get('is_efris_uom', 0)
            is_piece_unit = item_uom.get('is_piece_unit', 0)
            uom_new = item_uom.get('uom')
            efris_unit_price = item_uom.get('efris_unit_price', 0.0)
            uom_value = frappe.db.get_value('UOM', {'uom_name': uom_new}, 'efris_uom_code') or ''
            
            efris_log_info(f"Processing UOM: {uom_new}, Is EFRIS UOM: {is_efris_uom}, Is Piece Unit: {is_piece_unit}, Is Default UOM: {custom_efris_package_unit}")
           
            # If it's not an EFRIS UOM, skip it
            if not is_efris_uom:
                efris_log_info(f"Skipping {uom_new} as it is not flagged as an EFRIS UOM")
                continue

            # Ensure the UOM code exists
            if uom_value == '':
                frappe.throw(f"EFRIS UOM code is empty for UOM: {uom_new}")

            # Handle the default UOM separately (custom_efris_package_unit == 1)
            if custom_efris_package_unit == 1:
                efris_log_info(f"Skipping {uom_new} as it is the default package unit.")
                packageUnit = item_uom.get('uom')
                measureUnit =  frappe.db.get_value('UOM', {'uom_name': packageUnit}, 'efris_uom_code') or ''
                unitPrice = str(item_uom.get('efris_unit_price', 0.0))
                continue

            # Handle piece unit separately (is_piece_unit == 1)
            if is_piece_unit == 1:
                pieceMeasureUnit = uom_value
                pieceUnitPrice = efris_unit_price
                pieceScaledValue = str(item_uom.get('custom_package_scale_value', 1))
                havePieceUnit = "101"  # Indicate that a piece unit exists
                efris_log_info(f"Piece unit found: {uom_new} with price {pieceUnitPrice} and scaled value {pieceScaledValue}")
                continue
            
            # For other UOMs, add them to goodsOtherUnit[]
            conversion_factor = item_uom.get('conversion_factor', '1')
            custom_package_scale_value = item_uom.get('custom_package_scale_value', '1')
            goodsOtherUnit.append({
                "otherUnit": uom_value,
                "otherPrice": efris_unit_price,
                "otherScaled": str(custom_package_scale_value),
                'packageScaled': "1"
            })
            efris_log_info(f"Added {uom_new} to goodsOtherUnit with price {efris_unit_price} and scaled value {custom_package_scale_value}")

    # Prepare goodsUpload array for uploading to EFRIS
    goodsUpload = [{
        "operationType": operation_type,
        "goodsName": goodsName,
        "goodsCode": item_code,
        "measureUnit": measureUnit,
        "unitPrice": unitPrice,
        "currency": currency,
        "commodityCategoryId": commodityCategoryId if measureUnit else "",
        "haveExciseTax": "102",
        "stockPrewarning": "0",
        "havePieceUnit": havePieceUnit,  # Whether or not there's a piece unit
        "pieceMeasureUnit": pieceMeasureUnit,  # Piece unit UOM
        "pieceUnitPrice": pieceUnitPrice,      # Price for the piece unit
        "packageScaledValue": "1" if havePieceUnit == "101" else "",  # Piece unit scaling
        "pieceScaledValue": pieceScaledValue,  # Piece unit conversion factor
        "haveOtherUnit": "101" if goodsOtherUnit else "102",  # Whether there are other units
        "goodsOtherUnits": goodsOtherUnit  # Non-default, non-piece UOMs
    }]

    efris_log_info(f"The JSON item for Company {e_company} is: {goodsUpload}")

    # Upload the item to EFRIS
    success, response = make_post(interfaceCode="T130", content=goodsUpload, company_name=e_company,reference_doc_type=doc.doctype, reference_document=doc.name)
    
    
    if success:
        efris_log_info(f"Item successfully uploaded to EFRIS for {e_company}")
        frappe.msgprint(f"Item successfully uploaded to EFRIS for {e_company}")        
        
        if not doc.is_efris_registered:
            doc.is_efris_registered = 1
            efris_log_info(f"The Value Of Is Efris Registered is updated to {doc.get('is_efris_registered', '')}")
    else:
        efris_log_error(f"Failed to upload item to EFRIS for {e_company}: {response}")
        frappe.throw(f"Failed to upload item to EFRIS for {e_company}: {response}")




@frappe.whitelist()
def create_item_prices(item_code, uoms, currency):
    try:
        # Ensure uoms is in the correct format (list)
        if isinstance(uoms, str):
            uoms = json.loads(uoms)

        # Log the currency for debugging
        price_list = frappe.get_value('Price List', {'currency': currency, 'selling': 1}, 'name')
        efris_log_info(f"The Price List is {price_list}")
        if not price_list:
            frappe.throw(f"No Price List found for currency {currency}")

        # Loop through the UOMs and create/update Item Price records
        for uom_row in uoms:
            uom = uom_row.get('uom')
            price = uom_row.get('efris_unit_price')
            
            efris_log_info(f"The uom is {uom}")
            efris_log_info(f"The Standard Price is {price}")

            if price:
                # Check if an Item Price already exists for this item and UOM
                existing_item_price = frappe.get_all('Item Price', filters={
                    'item_code': item_code,
                    'uom': uom,
                    'price_list': price_list                   
                }, fields=['name', 'price_list_rate'])

                if existing_item_price:
                    # Update the existing Item Price if the price has changed
                    existing_price = existing_item_price[0]['price_list_rate']
                    if existing_price != price:
                        item_price_doc = frappe.get_doc('Item Price', existing_item_price[0]['name'])
                        item_price_doc.price_list_rate = price
                        item_price_doc.save(ignore_permissions=True)
                        efris_log_info(f"Item Price for item {item_code} and UOM {uom} updated to {price}.")
                else:
                    # Create a new Item Price record if it doesn't exist
                    item_price_doc = frappe.get_doc({
                        'doctype': 'Item Price',
                        'item_code': item_code,
                        'uom': uom,
                        'price_list': price_list,
                        'currency': currency,
                        'price_list_rate': price,
                        'selling': 1
                    })
                    item_price_doc.insert(ignore_permissions=True)
                    efris_log_info(f"Item Price for item {item_code} and UOM {uom} created.")
    
    except Exception as e:
        frappe.throw(f"Error creating/updating Item Prices: {str(e)}")



#######################
def validate_efris_uom(uom, label):
    uom_code = frappe.get_value('UOM', {'uom_name': uom}, 'efris_uom_code')
    if not uom_code:
        frappe.throw(f"The Selected {label} UOM ({uom}) is not a valid EFRIS UOM")
    efris_log_info(f"{label} UOM ({uom}) has EFRIS Code {uom_code}")

#####################
def validate_efris_item(doc):
    efris_log_info(f"Validating EFRIS Item: {doc.get('item_code')}")
    validate_item_tax_template(doc)
    validate_uoms(doc)

def validate_item_tax_template(doc):
    if not doc.get('taxes'):
        frappe.throw("Please select an Item Tax Template for an EFRIS ITEM.")

def validate_uoms(doc):
    uoms = doc.get("uoms", [])
    has_multiple_uom = doc.get("has_multiple_uom")

    # Defaults for single UOM
    if not has_multiple_uom and len(uoms) == 1:
        single_uom_row = uoms[0]
        single_uom_row.efris_unit_price = doc.get('standard_rate')
        single_uom_row.is_efris_uom = 1
        single_uom_row.custom_package_scale_value = 1
        single_uom_row.custom_efris_package_unit = 1
        doc.purchase_uom = single_uom_row.get('uom')
        doc.sales_uom = single_uom_row.get('uom')

        efris_log_info(f"Defaults set for single UOM: {single_uom_row.get('uom')}")

    # Validation logic
    piece_unit_count = 0
    package_unit_count = 0
    is_efris_uom_count = 0

    for row in uoms:
        piece_unit = row.get("is_piece_unit")
        package_unit = row.get("custom_efris_package_unit")
        efris_unit_price = row.get("efris_unit_price")
        custom_package_scale_value = row.get("custom_package_scale_value")
        is_efris_uom = row.get("is_efris_uom")

        if is_efris_uom:
            is_efris_uom_count += 1
        if piece_unit:
            piece_unit_count += 1
        if package_unit:
            package_unit_count += 1

        if is_efris_uom and (not efris_unit_price or not custom_package_scale_value):
            frappe.throw("EFRIS UOMs must have a unit price and scale value.")

    validate_uom_counts(has_multiple_uom, piece_unit_count, package_unit_count, is_efris_uom_count)

def validate_uom_counts(has_multiple_uom, piece_count, package_count, efris_count):
    if has_multiple_uom:
        if efris_count <= 1:
            frappe.throw("You must have additional UOMs if 'Has Multiple UOMs' is True.")
        if piece_count == 0:
            frappe.throw("EFRIS Piece Unit must be set if 'Has Multiple UOMs' is True.")
        if piece_count > 1:
            frappe.throw("Only one EFRIS Piece Measure Unit can be set.")
    else:
        if piece_count > 0:
            frappe.throw("EFRIS Piece Unit should not be set if 'Has Multiple UOMs' is False.")
    if package_count == 0:
        frappe.throw("EFRIS Package Measure Unit must be set.")
    if package_count > 1:
        frappe.throw("Only one EFRIS Package Measure Unit can be set.")


###################
@frappe.whitelist()
def item_validations(doc, method):
    try:
        if frappe.flags.in_import and doc.get("is_efris_registered"):
            efris_log_info(f"Validation Excludes EFRIS registered Item {doc.get('item_code')}")
            return

        if not doc.get("is_efris_item"):
            efris_log_info("Non EFRIS Item")
            return

        validate_efris_item(doc)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Item Validation Error")
        frappe.throw(f"Item Validations Failed!")
@frappe.whitelist()
def get_item_tax_template(company, e_tax_category):
    """
    Fetch the Item Tax Template linked to a specific company and e_tax_category
    in the child table (Item Tax Template Detail).
    """
    try:
        tax_templates = frappe.db.get_all("Item Tax Template",{"company":company})
        if tax_templates:
            efris_log_info(f"Tax Templates:{tax_templates}")
            for doc in tax_templates:
                item_tax = frappe.get_doc("Item Tax Template",{'name':doc.name})
                efris_log_info(f" Template Doc {item_tax}")
                taxes = item_tax.get("taxes",[])               
                for tax in taxes:
                    if tax.custom_e_tax_category == e_tax_category:
                        # Match found, return this Item Tax Template
                        return item_tax.name
                
        
        return None
    except Exception as e:
        frappe.log_error(f"Error fetching Item Tax Template: {str(e)}")
        return []