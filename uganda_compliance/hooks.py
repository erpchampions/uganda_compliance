app_name = "uganda_compliance"
app_title = "Uganda Compliance"
app_publisher = "ERP Champions Ltd"
app_description = "ERPNext Tax Compliance with Uganda"
app_email = "moki@erpchampions.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/uganda_compliance/css/uganda_compliance.css"
# app_include_js = "/assets/uganda_compliance/js/uganda_compliance.js"

# include js, css files in header of web template
# web_include_css = "/assets/uganda_compliance/css/uganda_compliance.css"
# web_include_js = "/assets/uganda_compliance/js/uganda_compliance.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "uganda_compliance/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "uganda_compliance.utils.jinja_methods",
# 	"filters": "uganda_compliance.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "uganda_compliance.install.before_install"
# after_install = "uganda_compliance.install.after_install"


# Uninstallation
# ------------

# before_uninstall = "uganda_compliance.uninstall.before_uninstall"
# after_uninstall = "uganda_compliance.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "uganda_compliance.utils.before_app_install"
# after_app_install = "uganda_compliance.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "uganda_compliance.utils.before_app_uninstall"
# after_app_uninstall = "uganda_compliance.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "uganda_compliance.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------


# scheduler_events = {
# 	"all": [
# 		"uganda_compliance.tasks.all"
# 	],
# 	"daily": [
# 		"uganda_compliance.tasks.daily",
#         "uganda_compliance.efris.api_classes.e_invoice.check_credit_note_approval_status",
#         "uganda_compliance.efris.api_classes.efris_invoice_sync.efris_invoice_sync"
# 	],
# 	"hourly": [
# 		"uganda_compliance.tasks.hourly"
# 	],
# 	"weekly": [
# 		"uganda_compliance.tasks.weekly"
# 	],
# 	"monthly": [
# 		"uganda_compliance.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "uganda_compliance.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "uganda_compliance.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "uganda_compliance.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["uganda_compliance.utils.before_request"]
# after_request = ["uganda_compliance.utils.after_request"]

# Job Events
# ----------
# before_job = ["uganda_compliance.utils.before_job"]
# after_job = ["uganda_compliance.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"uganda_compliance.auth.validate"
# ]
# Installation
# ------------
# before_install = "uganda_compliance.patches.add_e_company_to_customer"

app_include_js = "/assets/uganda_compliance/js/item_custom.js"

doc_events = {
    "Sales Invoice": {
        "on_submit": "uganda_compliance.efris.api_classes.e_invoice.on_submit_sales_invoice",
        "on_update": "uganda_compliance.efris.api_classes.e_invoice.on_update_sales_invoice",
        "on_cancel": "uganda_compliance.efris.api_classes.e_invoice.on_cancel_sales_invoice",
        "before_save": ["uganda_compliance.efris.api_classes.e_invoice.Sales_invoice_is_efris_validation",
                        "uganda_compliance.efris.api_classes.e_invoice.sales_uom_validation" ,
                        "uganda_compliance.efris.api_classes.e_invoice.calculate_additional_discounts"                      
                        ]                
        
    },
    "Item": {
        "before_save": "uganda_compliance.efris.api_classes.e_goods_services.before_save_item",
        "validate": "uganda_compliance.efris.api_classes.e_goods_services.item_validations"

    },
    "Purchase Receipt":{
        "on_submit":"uganda_compliance.efris.api_classes.stock_in.stock_in_T131",
        "before_save":["uganda_compliance.efris.api_classes.stock_in.before_save_on_purchase_receipt",
                       "uganda_compliance.efris.api_classes.stock_in.purchase_uom_validation"
                       ],
        
    },
    "Stock Entry":{
        "on_submit":"uganda_compliance.efris.api_classes.stock_in.stock_in_T131",
        "before_save":"uganda_compliance.efris.api_classes.stock_in.before_save_on_stock_entry"
    },
    "E Invoicing Settings":{
        "before_save":["uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.before_save",
                       "uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.create_item_tax_templates"                       
                       ]        
    },
    "Stock Reconciliation":{
        "on_submit":"uganda_compliance.efris.api_classes.stock_in.stock_in_T131"
    },
    "Customer":{
        "before_save":"uganda_compliance.efris.api_classes.e_customer.before_save_query_customer"
        
    },
    "Company":{
       "before_save":"uganda_compliance.efris.api_classes.e_company.before_save_query_company"
    }
      
}




doctype_list_js = {
    "Sales Invoice": [
        "efris/client_scripts/sales_invoice.js"
        
        ],
    "Purchase Receipt": [
    "efris/client_scripts/purchase_receipt.js"
    
        ],
    
    "Stock Entry": [
    "efris/client_scripts/stock_entry.js"
        
        ],
    
    "E Invoicing Settings": [
    "efris/doctype/e_invoicing_settings/e_invoicing_settings.js"
        
        ],
    "Stock Reconciliation": [
    "efris/client_scripts/stock_reconciliation.js"
        
        ],
    "Item": [
    "efris/client_scripts/item.js"
        
        ],
     "Company": [
    "efris/client_scripts/company.js"
        
        ],
    "Warehouse": [
    "efris/client_scripts/warehouse.js"
        
        ]

}
   



fixtures = [
    "E Tax Category", 
    "Efris Commodity Code",
    "UOM",
    {
        "doctype": "Print Format",
        "filters": {
            "name": ["in", ["EFRIS E Invoice", "EFRIS Sales Invoice","POS EFRIS Invoice"]]
        }
    },
    {
        "doctype": "Print Style",
        "filters": {
            "name": ["=", "Redesign"]
        }
    },
    {
        "doctype": "Currency",
        "filters": {
            "efris_currency_code": ["!=", None]
        }
    }
    # {
    #     "doctype": "File",
    #     "filters": {
    #         "file_name": ["=","ura_efris_logo.png"]
    #     }
    # }
]

