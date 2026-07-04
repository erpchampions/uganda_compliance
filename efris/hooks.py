app_name = "efris"
app_title = "Efris"
app_publisher = "Ignite Digital "
app_description = "EFRIS App Uganda"
app_email = "hello@igniteug.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "efris",
# 		"logo": "/assets/efris/logo.png",
# 		"title": "Efris",
# 		"route": "/efris",
# 		"has_permission": "efris.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/efris/css/efris.css"
app_include_js = [
	"/assets/efris/js/dictionary.js",
	"/assets/efris/js/link_filters.js",
	"/assets/efris/js/exchange_rate.js",
	"/assets/efris/js/batch_invoice.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/efris/css/efris.css"
# web_include_js = "/assets/efris/js/efris.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "efris/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Customer": "public/js/party.js",
	"Supplier": "public/js/party.js",
	"Item": "public/js/item.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	"POS Invoice": "public/js/pos_invoice.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Purchase Receipt": "public/js/purchase_receipt.js",
	"Stock Entry": "public/js/stock_entry.js",
	"Payment Entry": "public/js/payment_entry.js",
	"Subscription": "public/js/subscription.js",
}
doctype_list_js = {
	"Customer": "public/js/party_list.js",
	"Supplier": "public/js/party_list.js",
	"Sales Invoice": "public/js/sales_invoice_list.js",
	"POS Invoice": "public/js/pos_invoice_list.js",
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "efris/public/icons.svg"

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

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {
	"methods": [
		"efris.efris.api.invoice.derive_print_data",
	],
}

# Installation
# ------------

# before_install = "efris.install.before_install"
after_install = "efris.efris.setup.install_custom_fields"
after_migrate = "efris.efris.setup.install_custom_fields"

# Uninstallation
# ------------

# before_uninstall = "efris.uninstall.before_uninstall"
# after_uninstall = "efris.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "efris.utils.before_app_install"
# after_app_install = "efris.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "efris.utils.before_app_uninstall"
# after_app_uninstall = "efris.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "efris.notifications.get_notification_config"

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

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Customer": {
		"validate": "efris.efris.api.taxpayer.auto_validate_party_tin",
	},
	"Supplier": {
		"validate": "efris.efris.api.taxpayer.auto_validate_party_tin",
	},
	"Item": {
		"validate": "efris.efris.api.goods.sync_piece_unit_from_uoms",
		"on_update": "efris.efris.api.goods.auto_upload_on_save",
	},
	"Item Price": {
		"on_update": "efris.efris.api.goods.on_item_price_change",
	},
	"Stock Entry": {
		"on_submit": "efris.efris.api.stock.auto_upload_on_submit",
	},
	"Purchase Receipt": {
		"on_submit": "efris.efris.api.stock.auto_upload_on_submit",
	},
	"Purchase Invoice": {
		"on_submit": "efris.efris.api.stock.auto_upload_on_submit",
	},
	"Sales Invoice": {
		"validate": "efris.efris.api.invoice.stamp_upload_trigger",
		"on_submit": "efris.efris.api.invoice.auto_upload_on_submit",
	},
	"POS Invoice": {
		"validate": "efris.efris.api.invoice.stamp_upload_trigger",
		"on_submit": "efris.efris.api.invoice.auto_upload_on_submit",
	},
	"Payment Entry": {
		"on_submit": "efris.efris.api.payment.auto_upload_on_payment_submit",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"efris.tasks.sync_dictionaries",
		"efris.tasks.sync_excise_duty",
		"efris.tasks.sync_commodity_categories",
		"efris.tasks.sync_exchange_rate",
	],
}

# Testing
# -------

# before_tests = "efris.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "efris.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "efris.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "efris.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["efris.utils.before_request"]
# after_request = ["efris.utils.after_request"]

# Job Events
# ----------
# before_job = ["efris.utils.before_job"]
# after_job = ["efris.utils.after_job"]

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
# 	"efris.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

