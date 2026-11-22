import os
import re
import shutil

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

SLUG_RE = re.compile(r'^[a-z][a-z0-9_]{2,24}$')
MODEL_RE = re.compile(r'^x_[a-z0-9_]+$')

STATES = [
    ('draft', 'Draft'),
    ('generated', 'Generated'),
    ('validated', 'Validated'),
    ('installed', 'Installed'),
    ('rolled_back', 'Rolled back'),
    ('removed', 'Files removed'),
]


class OdooClawForge(models.Model):
    _name = 'odooclaw.forge'
    _description = 'OdooClaw module factory'
    _order = 'id desc'

    name = fields.Char(required=True)
    module_name = fields.Char(
        required=True,
        help='Technical module name, e.g. evo_demo_note',
    )
    model_name = fields.Char(
        required=True,
        help='Technical model name, e.g. x_evo_demo_note',
    )
    description = fields.Text()
    workspace = fields.Char(
        required=True,
        default=lambda self: self._default_workspace(),
        help='Directory that is already in the Odoo addons path.',
    )
    module_path = fields.Char(readonly=True)
    state = fields.Selection(STATES, default='draft', required=True)
    log = fields.Text(readonly=True)

    @api.model
    def _default_workspace(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'odooclaw_evolution.workspace', '/mnt/extra-addons'
        )

    def _safe_workspace(self):
        self.ensure_one()
        workspace = os.path.realpath(self.workspace)
        if not os.path.isdir(workspace):
            raise UserError(_('Workspace does not exist: %s', workspace))
        return workspace

    def _safe_module_path(self):
        self.ensure_one()
        workspace = self._safe_workspace()
        module_path = os.path.realpath(os.path.join(workspace, self.module_name))
        if os.path.commonpath([workspace, module_path]) != workspace:
            raise ValidationError(_('Module path escapes the workspace.'))
        return module_path

    def _write(self, root, relative, content):
        path = os.path.join(root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(content)

    def action_generate(self):
        for forge in self:
            forge._generate_one()
        return True

    def _generate_one(self):
        if not SLUG_RE.match(self.module_name or ''):
            raise ValidationError(
                _('Module name must match [a-z][a-z0-9_]{2,24}.')
            )
        if not MODEL_RE.match(self.model_name or ''):
            raise ValidationError(
                _('Model name must start with x_ and use lowercase letters, digits and underscores.')
            )
        if self.env['ir.module.module'].sudo().search(
            [('name', '=', self.module_name)], limit=1
        ):
            raise ValidationError(_('Module %s already exists.', self.module_name))
        module_path = self._safe_module_path()
        if os.path.exists(module_path):
            raise ValidationError(_('Directory already exists: %s', module_path))
        os.makedirs(module_path)

        label = self.name
        model = self.model_name
        module = self.module_name
        description = self.description or label
        class_name = 'GeneratedRecord'
        xml_root = 'evo_%s' % module.replace('evo_', '', 1)

        self._write(module_path, '__init__.py', 'from . import models\n')
        self._write(module_path, '__manifest__.py', (
            "{\n"
            "    'name': %r,\n"
            "    'version': '18.0.1.0.0',\n"
            "    'category': 'Technical',\n"
            "    'summary': %r,\n"
            "    'depends': ['base'],\n"
            "    'data': [\n"
            "        'security/ir.model.access.csv',\n"
            "        'views/%s_views.xml',\n"
            "    ],\n"
            "    'installable': True,\n"
            "    'auto_install': False,\n"
            "    'license': 'LGPL-3',\n"
            "}\n"
        ) % (label, description, xml_root))
        self._write(module_path, 'models/__init__.py', 'from . import %s\n' % xml_root)
        self._write(module_path, 'models/%s.py' % xml_root, (
            "from odoo import fields, models\n"
            "\n"
            "\n"
            "class %s(models.Model):\n"
            "    _name = %r\n"
            "    _description = %r\n"
            "\n"
            "    name = fields.Char(required=True)\n"
            "    note = fields.Text()\n"
            "    active = fields.Boolean(default=True)\n"
        ) % (class_name, model, description))
        self._write(module_path, 'security/ir.model.access.csv', (
            "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
            "access_%(model)s,access_%(model)s,model_%(model)s,base.group_user,1,1,1,1\n"
        ) % {'model': model})
        self._write(module_path, 'views/%s_views.xml' % xml_root, (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<odoo>\n'
            '    <record id="view_%(model)s_list" model="ir.ui.view">\n'
            '        <field name="name">%(model)s.list</field>\n'
            '        <field name="model">%(model)s</field>\n'
            '        <field name="arch" type="xml">\n'
            '            <list>\n'
            '                <field name="name"/>\n'
            '                <field name="note"/>\n'
            '            </list>\n'
            '        </field>\n'
            '    </record>\n'
            '    <record id="view_%(model)s_form" model="ir.ui.view">\n'
            '        <field name="name">%(model)s.form</field>\n'
            '        <field name="model">%(model)s</field>\n'
            '        <field name="arch" type="xml">\n'
            '            <form>\n'
            '                <sheet>\n'
            '                    <group>\n'
            '                        <field name="name"/>\n'
            '                        <field name="note"/>\n'
            '                    </group>\n'
            '                </sheet>\n'
            '            </form>\n'
            '        </field>\n'
            '    </record>\n'
            '    <record id="action_%(model)s" model="ir.actions.act_window">\n'
            '        <field name="name">%(label)s</field>\n'
            '        <field name="res_model">%(model)s</field>\n'
            '        <field name="view_mode">list,form</field>\n'
            '    </record>\n'
            '    <menuitem id="menu_%(model)s_root" name="%(label)s" sequence="90"/>\n'
            '    <menuitem id="menu_%(model)s" name="%(label)s" '
            'parent="menu_%(model)s_root" action="action_%(model)s" sequence="10"/>\n'
            '</odoo>\n'
        ) % {'model': model, 'label': label})
        self._write(module_path, 'tests/__init__.py', 'from . import test_%s\n' % xml_root)
        self._write(module_path, 'tests/test_%s.py' % xml_root, (
            "from odoo.tests.common import TransactionCase\n"
            "\n"
            "\n"
            "class TestGenerated(TransactionCase):\n"
            "    def test_create(self):\n"
            "        record = self.env[%r].create({'name': 'probe'})\n"
            "        self.assertEqual(record.name, 'probe')\n"
        ) % model)
        self._write(module_path, 'README.md', (
            '# %s\n\n'
            'Generated by OdooClaw Evolution.\n\n'
            'Model: `%s`\n'
        ) % (label, model))
        self.write({
            'module_path': module_path,
            'state': 'generated',
            'log': 'Generated at %s' % module_path,
        })

    def action_check(self):
        for forge in self:
            if forge.state not in ('generated', 'validated'):
                raise UserError(_('Generate the module first.'))
            self.env['ir.module.module'].sudo().update_list()
            module = self.env['ir.module.module'].sudo().search(
                [('name', '=', forge.module_name)], limit=1
            )
            if not module:
                raise UserError(
                    _('Module %s not found. Is the workspace in the addons path?', forge.module_name)
                )
            forge.write({
                'state': 'validated',
                'log': 'Module visible: %s' % module.state,
            })
        return True

    def action_install(self):
        for forge in self:
            module = self.env['ir.module.module'].sudo().search(
                [('name', '=', forge.module_name)], limit=1
            )
            if not module:
                raise UserError(_('Run Check first.'))
            module.button_immediate_install()
            forge.write({'state': 'installed', 'log': 'Installed: %s' % forge.module_name})
        return True

    def action_uninstall(self):
        for forge in self:
            module = self.env['ir.module.module'].sudo().search(
                [('name', '=', forge.module_name)], limit=1
            )
            if not module or module.state != 'installed':
                raise UserError(_('Only installed modules can be uninstalled.'))
            module.button_immediate_uninstall()
            forge.write({
                'state': 'rolled_back',
                'log': 'Uninstalled: %s' % forge.module_name,
            })
        return True

    def action_remove_files(self):
        for forge in self:
            if forge.state != 'rolled_back':
                raise UserError(_('Uninstall the module before removing its files.'))
            path = os.path.realpath(forge.module_path)
            workspace = forge._safe_workspace()
            if os.path.commonpath([workspace, path]) != workspace:
                raise UserError(_('Refusing to remove a path outside the workspace.'))
            if os.path.isdir(path):
                shutil.rmtree(path)
            forge.write({
                'state': 'removed',
                'module_path': False,
                'log': 'Files removed: %s' % path,
            })
        return True
