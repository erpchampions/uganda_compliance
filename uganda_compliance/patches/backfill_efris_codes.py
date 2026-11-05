from uganda_compliance.install import backfill_efris_codes


def execute():
	# sites installed before install.after_install existed have empty EFRIS currency/UOM codes
	backfill_efris_codes()
