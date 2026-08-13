package agent

import (
	"fmt"
	"strings"
	"testing"

	"github.com/nicolasramos/odooclaw/pkg/providers/protocoltypes"
)

// TestDebugRetrieval prints the top-5 tools that retrieveRelevantTools returns
// for the real production queries that regressed. Run with:
//   go test ./pkg/agent/ -run TestDebugRetrieval -v
func TestDebugRetrieval(t *testing.T) {
	names := []string{
		"mcp_odoo-mcp_odoo_search", "mcp_odoo-mcp_odoo_read", "mcp_odoo-mcp_odoo_create",
		"mcp_odoo-mcp_odoo_write", "mcp_odoo-mcp_odoo_invoke_action", "mcp_odoo-mcp_odoo_find_partner",
		"mcp_odoo-mcp_odoo_get_partner_summary", "mcp_odoo-mcp_odoo_create_activity",
		"mcp_odoo-mcp_odoo_list_pending_activities", "mcp_odoo-mcp_odoo_mark_activity_done",
		"mcp_odoo-mcp_odoo_post_chatter_message", "mcp_odoo-mcp_odoo_find_task",
		"mcp_odoo-mcp_odoo_create_task", "mcp_odoo-mcp_odoo_update_task", "mcp_odoo-mcp_odoo_find_my_tasks",
		"mcp_odoo-mcp_odoo_update_task_status", "mcp_odoo-mcp_odoo_find_sale_order",
		"mcp_odoo-mcp_odoo_get_sale_order_summary", "mcp_odoo-mcp_odoo_get_record_summary",
		"mcp_odoo-mcp_odoo_create_purchase_order", "mcp_odoo-mcp_odoo_find_purchase_order",
		"mcp_odoo-mcp_odoo_get_purchase_order_summary", "mcp_odoo-mcp_odoo_get_purchase_receipt_status",
		"mcp_odoo-mcp_odoo_get_purchase_invoice_status", "mcp_odoo-mcp_odoo_suggest_vendor_products",
		"mcp_odoo-mcp_odoo_match_vendor_bill_to_purchase_order", "mcp_odoo-mcp_odoo_create_vendor_invoice",
		"mcp_odoo-mcp_odoo_find_pending_invoices", "mcp_odoo-mcp_odoo_get_invoice_summary",
		"mcp_odoo-mcp_odoo_get_model_schema", "mcp_odoo-mcp_odoo_get_capabilities",
		"mcp_odoo-mcp_odoo_create_helpdesk_ticket", "mcp_odoo-mcp_odoo_create_helpdesk_ticket_from_partner",
		"mcp_odoo-mcp_odoo_create_activity_summary", "mcp_odoo-mcp_odoo_close_activity_with_reason",
		"mcp_odoo-mcp_odoo_draft_ticket_email", "mcp_odoo-mcp_odoo_create_contract_line",
		"mcp_odoo-mcp_odoo_replace_contract_line", "mcp_odoo-mcp_odoo_close_contract_line",
		"mcp_odoo-mcp_odoo_create_calendar_event", "mcp_odoo-mcp_odoo_create_sale_order",
		"mcp_odoo-mcp_odoo_confirm_sale_order", "mcp_odoo-mcp_odoo_create_lead",
		"mcp_odoo-mcp_odoo_find_product", "mcp_odoo-mcp_odoo_get_product_summary",
		"mcp_odoo-mcp_odoo_get_stock_availability", "mcp_odoo-mcp_odoo_find_purchase_receipts",
		"mcp_odoo-mcp_odoo_find_sale_deliveries", "mcp_odoo-mcp_odoo_find_inventory_discrepancies",
		"mcp_odoo-mcp_odoo_log_timesheet", "mcp_odoo-mcp_odoo_find_attendance", "mcp_odoo-mcp_odoo_check_in",
		"mcp_odoo-mcp_odoo_check_out", "mcp_odoo-mcp_odoo_get_my_today_summary",
		"mcp_odoo-mcp_odoo_create_expense_report", "mcp_odoo-mcp_odoo_submit_expense_report",
		"mcp_odoo-mcp_odoo_approve_expense", "mcp_odoo-mcp_odoo_register_payment",
		"mcp_odoo-mcp_odoo_find_unreconciled_bank_lines", "mcp_odoo-mcp_odoo_suggest_bank_reconciliation",
		"mcp_odoo-mcp_odoo_reconcile_bank_line", "mcp_odoo-mcp_odoo_register_invoice_payment",
		"mcp_odoo-mcp_odoo_get_ar_ap_aging", "mcp_odoo-mcp_odoo_run_period_close_checks",
		"mcp_odoo-mcp_odoo_create_journal_entry", "mcp_odoo-mcp_odoo_post_journal_entry",
		"mcp_odoo-mcp_odoo_get_tax_summary", "mcp_odoo-mcp_odoo_validate_vendor_bill_duplicate",
		"mcp_odoo-mcp_odoo_suggest_expense_account_and_taxes", "mcp_odoo-mcp_odoo_create_vendor_bill_from_ocr_validated",
		"mcp_odoo-mcp_odoo_get_view_by_xmlid", "mcp_odoo-mcp_odoo_find_views_by_model",
		"mcp_odoo-mcp_odoo_get_report_template", "mcp_odoo-mcp_odoo_scan_view_migration_issues",
		"mcp_odoo-mcp_odoo_scan_report_migration_issues", "mcp_odoo-mcp_odoo_propose_view_patch",
		"mcp_odoo-mcp_odoo_propose_report_patch", "mcp_odoo-mcp_odoo_validate_view_patch",
		"mcp_odoo-mcp_odoo_validate_report_patch", "mcp_odoo-mcp_odoo_preview_view_patch",
		"mcp_odoo-mcp_odoo_preview_report_patch", "mcp_odoo-mcp_odoo_test_view_compilation",
		"mcp_odoo-mcp_odoo_test_report_compilation", "mcp_odoo-mcp_odoo_apply_view_patch_safe",
		"mcp_odoo-mcp_odoo_apply_report_patch_safe", "mcp_odoo-mcp_odoo_rollback_patch_safe",
		"mcp_odoo-mcp_odoo_assist_view_migration", "mcp_odoo-mcp_odoo_assist_report_migration",
		"mcp_odoo-mcp_odoo_visualize_view_patch", "mcp_odoo-mcp_odoo_visualize_report_patch",
		"mcp_odoo-mcp_odoo_batch_assist_view_migration", "mcp_odoo-mcp_odoo_batch_assist_report_migration",
		"mcp_odoo-mcp_odoo_find_tasks_for_user", "mcp_odoo-mcp_odoo_get_task_stats",
		"mcp_odoo-mcp_odoo_get_financial_snapshot", "mcp_odoo-mcp_odoo_find_partner_summary",
	}
	defs := make([]protocoltypes.ToolDefinition, 0, len(names))
	for _, n := range names {
		defs = append(defs, protocoltypes.ToolDefinition{
			Type: "function",
			Function: protocoltypes.ToolFunctionDefinition{
				Name: n, Description: "test", Parameters: map[string]any{},
			},
		})
	}
	queries := []string{
		"Registra un nuevo contacto llamado Maria Garcia",
		"Busca el cliente Acme",
		"Me ayudas? necesito saber mi saldo",
		"Hola, cuantos clientes tenemos?",
	}
	for _, q := range queries {
		got := retrieveRelevantTools(defs, q, maxLocalToolsInPrompt)
		var sb strings.Builder
		for i, d := range got {
			sb.WriteString(fmt.Sprintf("  %d. %s\n", i+1, d.Function.Name))
		}
		t.Logf("QUERY: %q\n%s", q, sb.String())
	}
}
