package openai_compat

import (
	"testing"
)

// Segundo bloque real, el que Nico pegó a las 15:24 tras el despliegue del
// arreglo. Se diferencia del primero en la forma del cierre: aquí el parámetro
// lleva `</parameter>` Y ADEMÁS un `</arguments>` sobrante antes de
// `</tool_call>`. Hay que comprobar que este dialecto también se reconoce.
const liveBlock2 = `<tool_call>
<function=odoo_search_read>
<parameter=model>
sale.order
</parameter>
<parameter=arguments>
{"domain": [["state", "=", "sale"], ["date_order", ">=", "2026-09-01"], ["date_order", "<=", "2026-09-30"]]}
</parameter>
</arguments>
</tool_call>`

func TestExtractQwenXML_SecondLiveBlock(t *testing.T) {
	got := extractQwenContentToolCalls(liveBlock2)
	if len(got) != 1 {
		t.Fatalf("got %d tool calls, want 1", len(got))
	}
	if got[0].Function.Name != "odoo_search_read" {
		t.Errorf("name = %q", got[0].Function.Name)
	}
	if got[0].Arguments["model"] != "sale.order" {
		t.Errorf("model = %#v, want sale.order", got[0].Arguments["model"])
	}
	args, ok := got[0].Arguments["arguments"].(map[string]any)
	if !ok {
		t.Fatalf("arguments = %#v, want decoded map", got[0].Arguments["arguments"])
	}
	dom, ok := args["domain"].([]any)
	if !ok || len(dom) != 3 {
		t.Fatalf("domain = %#v, want 3 conditions", args["domain"])
	}

	// Y no debe quedar markup para publicar.
	if s := stripQwenContentToolCalls(liveBlock2); containsAny(s, "<function=", "<tool_call>", "</arguments>") {
		t.Errorf("markup survived stripping: %q", s)
	}
}

func containsAny(s string, subs ...string) bool {
	for _, sub := range subs {
		if indexOfSub(s, sub) {
			return true
		}
	}
	return false
}

func indexOfSub(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
