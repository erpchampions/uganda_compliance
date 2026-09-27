import json
import unittest
from unittest.mock import patch, MagicMock

from uganda_compliance.efris.api_classes import e_invoice


class TestSendPosInvoiceToEfris(unittest.TestCase):
	def setUp(self):
		self.doc_dict = {
			"doctype": "POS Invoice",
			"name": "POS-INV-0001",
			"company": "FB Fashions",
			"efris_invoice": 1,
			"is_consolidated": 0,
		}

	@patch.object(e_invoice, "on_submit_pos_invoice")
	def test_returns_success_payload(self, mock_on_submit):
		doc = MagicMock()
		result = e_invoice.send_pos_invoice_to_efris(doc)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["message"], "POS Invoice sent to EFRIS successfully.")
		mock_on_submit.assert_called_once_with(doc, "manual_submit")

	@patch.object(e_invoice, "on_submit_pos_invoice")
	@patch.object(e_invoice.frappe, "get_doc")
	def test_accepts_dict_input_and_loads_doc(self, mock_get_doc, mock_on_submit):
		built_doc = MagicMock()
		mock_get_doc.return_value = built_doc

		result = e_invoice.send_pos_invoice_to_efris(self.doc_dict)

		mock_get_doc.assert_called_once_with(self.doc_dict)
		mock_on_submit.assert_called_once_with(built_doc, "manual_submit")
		self.assertEqual(result["status"], "success")

	@patch.object(e_invoice, "on_submit_pos_invoice")
	@patch.object(e_invoice.frappe, "get_doc")
	def test_accepts_json_string_input(self, mock_get_doc, mock_on_submit):
		built_doc = MagicMock()
		mock_get_doc.return_value = built_doc
		json_payload = json.dumps(self.doc_dict)

		result = e_invoice.send_pos_invoice_to_efris(json_payload)

		mock_get_doc.assert_called_once_with(self.doc_dict)
		mock_on_submit.assert_called_once_with(built_doc, "manual_submit")
		self.assertEqual(result["status"], "success")

	@patch.object(e_invoice, "on_submit_pos_invoice")
	def test_invalid_json_string_raises(self, mock_on_submit):
		with self.assertRaises(json.JSONDecodeError):
			e_invoice.send_pos_invoice_to_efris("{not-json")
		mock_on_submit.assert_not_called()

	@patch.object(e_invoice, "on_submit_pos_invoice", side_effect=RuntimeError("boom"))
	def test_propagates_downstream_errors(self, _mock_on_submit):
		with self.assertRaises(RuntimeError):
			e_invoice.send_pos_invoice_to_efris(MagicMock())

	@patch.object(e_invoice, "on_submit_pos_invoice")
	def test_passes_manual_submit_method_flag(self, mock_on_submit):
		"""Manual send must bypass the auto_send_submitted_invoice check downstream."""
		doc = MagicMock()
		e_invoice.send_pos_invoice_to_efris(doc)

		_, kwargs = mock_on_submit.call_args
		args, _ = mock_on_submit.call_args
		self.assertEqual(args[1], "manual_submit")


if __name__ == "__main__":
	unittest.main()