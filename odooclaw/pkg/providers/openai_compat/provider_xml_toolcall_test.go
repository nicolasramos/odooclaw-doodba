package openai_compat

import (
	"strings"
	"testing"
)

// The literal block the demo bot published to Discuss instead of calling the
// tool. Taken verbatim from the live instance (NRA-3210): the model emitted an
// XML dialect whose tool name and arguments live in child tags, which the
// JSON-shaped Qwen parser did not recognise - so the call never ran and the
// markup reached the user as the answer.
const liveXMLToolCall = `<tool_call>
<function=odoo_search_read>
<parameter=model>
res.partner
</parameter>
<parameter=arguments>
{"domain": []}
</arguments>
</tool_call>`

func TestExtractQwenXMLFunctionToolCalls_LiveBlock(t *testing.T) {
	got := extractQwenContentToolCalls(liveXMLToolCall)
	if len(got) != 1 {
		t.Fatalf("got %d tool calls, want 1 (the block went unparsed)", len(got))
	}

	name := got[0].Function.Name
	if name != "odoo_search_read" {
		t.Errorf("name = %q, want %q", name, "odoo_search_read")
	}

	if got[0].Arguments["model"] != "res.partner" {
		t.Errorf("model arg = %#v, want %q", got[0].Arguments["model"], "res.partner")
	}

	// The nested JSON must arrive decoded, not as a string the tool has to
	// parse again.
	args, ok := got[0].Arguments["arguments"].(map[string]any)
	if !ok {
		t.Fatalf("arguments arg = %#v, want a decoded map", got[0].Arguments["arguments"])
	}
	if _, ok := args["domain"]; !ok {
		t.Errorf("arguments arg lost its domain key: %#v", args)
	}
}

func TestExtractQwenXMLFunctionToolCalls_PrefixedName(t *testing.T) {
	// The gateway prefixes MCP tool names with the server; the model echoes
	// whatever it was given, so the prefixed form must parse unchanged.
	block := `<tool_call>
<function=mcp_odoo-manager_odoo_search_read>
<parameter=model>
res.partner
</parameter>
<parameter=limit>
10
</parameter>
</tool_call>`

	got := extractQwenContentToolCalls(block)
	if len(got) != 1 {
		t.Fatalf("got %d tool calls, want 1", len(got))
	}
	if got[0].Function.Name != "mcp_odoo-manager_odoo_search_read" {
		t.Errorf("name = %q, want the prefixed name unchanged", got[0].Function.Name)
	}
	if got[0].Arguments["limit"] != float64(10) {
		t.Errorf("limit = %#v, want numeric 10", got[0].Arguments["limit"])
	}
}

func TestExtractQwenXMLFunctionToolCalls_StripsFromUserText(t *testing.T) {
	// Whatever is parsed must not be published to the user afterwards.
	text := "Voy a consultarlo.\n" + liveXMLToolCall

	got := extractQwenContentToolCalls(text)
	if len(got) != 1 {
		t.Fatalf("got %d tool calls, want 1", len(got))
	}
	if stripped := stripQwenContentToolCalls(text); strings.Contains(stripped, "<function=") {
		t.Errorf("markup survived stripping, so it would be published: %q", stripped)
	}
}
