/** @odoo-module **/
import { Component, useState, xml } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class OdooClawDialog extends Component {
    static template = xml`
        <Dialog title="'OdooClaw Live'" size="'md'">
            <div class="o_odooclaw_dialog">
                <p class="text-muted" t-if="contextLabel">
                    <t t-esc="contextLabel"/>
                </p>
                <textarea class="form-control" rows="4" placeholder="¿Qué quieres cambiar?"
                          t-model="state.request"/>
                <p class="text-danger mt-2" t-if="state.error" t-esc="state.error"/>
            </div>
            <t t-set-slot="footer">
                <button class="btn btn-secondary" t-on-click="props.close">Cancelar</button>
                <button class="btn btn-primary" t-on-click="openChat" t-att-disabled="state.sending">
                    <t t-if="state.sending">Abriendo...</t>
                    <t t-else="">Abrir chat</t>
                </button>
            </t>
        </Dialog>
    `;
    static components = { Dialog };
    static props = {
        close: Function,
        model: { type: String, optional: true },
        resId: { type: [Number, Boolean], optional: true },
        viewType: { type: String, optional: true },
        field: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.mail = useService("mail");
        this.state = useState({ request: "", sending: false, error: "" });
    }

    get contextLabel() {
        const parts = [];
        if (this.props.model) {
            parts.push(this.props.model);
        }
        if (this.props.resId) {
            parts.push(`#${this.props.resId}`);
        }
        if (this.props.viewType) {
            parts.push(this.props.viewType);
        }
        if (this.props.field) {
            parts.push(`campo ${this.props.field}`);
        }
        return parts.join(" · ");
    }

    async openChat() {
        if (this.state.sending) {
            return;
        }
        this.state.sending = true;
        this.state.error = "";
        try {
            const channelId = await this.orm.call("odooclaw.chat", "open_chat", [
                this.props.model || "",
                this.props.resId || 0,
                this.props.viewType || "",
                this.props.field || "",
                this.state.request || "",
            ]);
            this.props.close();
            await this.mail.openChat({ id: channelId });
        } catch (error) {
            this.state.error = error.message || String(error);
        } finally {
            this.state.sending = false;
        }
    }
}

export class OdooClawSystray extends Component {
    static template = xml`
        <button class="o_odooclaw_systray btn btn-link" t-on-click="onClick" title="OdooClaw Live">
            <i class="fa fa-magic"/> OdooClaw
        </button>
    `;

    setup() {
        this.action = useService("action");
        this.dialog = useService("dialog");
    }

    onClick() {
        const controller = this.action.currentController;
        const model = controller?.props?.resModel || "";
        const resId = controller?.props?.resId || 0;
        const viewType = controller?.props?.type || "";
        this.dialog.add(OdooClawDialog, {
            model,
            resId,
            viewType,
            field: this.currentField(),
        });
    }

    currentField() {
        const active = document.activeElement;
        const widget = active?.closest?.("[name]");
        if (widget && widget.closest(".o_form_view, .o_list_view")) {
            return widget.getAttribute("name") || "";
        }
        return "";
    }
}

registry.category("systray").add("odooclaw_evolution.systray", {
    Component: OdooClawSystray,
});
