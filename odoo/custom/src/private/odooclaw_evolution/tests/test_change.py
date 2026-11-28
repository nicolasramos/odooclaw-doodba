import ast
import json

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestOdooClawChange(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Change = cls.env['odooclaw.change']

    def _change(self, kind, payload, level='n1'):
        return self.Change.create({
            'name': 'Test %s' % kind,
            'kind': kind,
            'level': level,
            'target_model': payload.get('model', ''),
            'payload': json.dumps(payload),
        })

    def test_field_cycle(self):
        change = self._change('field', {
            'model': 'res.partner',
            'name': 'x_evo_test_field',
            'ttype': 'char',
            'field_description': 'Evo Test Field',
            'help': 'Campo de prueba del ciclo de evolucion.',
        })
        self.assertEqual(change.status, 'draft')
        change.action_validate()
        self.assertEqual(change.status, 'validated')
        change.action_apply()
        self.assertEqual(change.status, 'applied')
        self.assertIn(
            'x_evo_test_field',
            self.env['res.partner'].fields_get(['x_evo_test_field']),
        )
        change.action_rollback()
        self.assertEqual(change.status, 'rolled_back')
        self.assertNotIn(
            'x_evo_test_field',
            self.env['res.partner'].fields_get(['x_evo_test_field']),
        )

    def test_view_cycle(self):
        view_change = self._change('view', {
            'model': 'res.partner',
            'inherit_xmlid': 'base.view_partner_form',
            'name': 'res.partner.evo.view',
            'arch': (
                '<data><xpath expr="//field[@name=\'comment\']" position="after">'
                '<div name="evo_marker">EVO</div>'
                '</xpath></data>'
            ),
        })
        view_change.action_validate()
        view_change.action_apply()
        snapshot = json.loads(view_change.snapshot)
        view = self.env['ir.ui.view'].browse(snapshot['view_id'])
        self.assertEqual(view.inherit_id.id, self.env.ref('base.view_partner_form').id)
        self.assertEqual(view.mode, 'extension')
        self.assertEqual(view.model, 'res.partner')
        self.assertEqual(view.type, 'form')
        self.assertTrue(view.active)
        self.assertIn('evo_marker', view.arch)

        view_change.action_rollback()
        self.assertFalse(view.exists())

    def test_action_cycle(self):
        change = self._change('action', {
            'model': 'res.partner',
            'name': 'Evo Action',
            'code': "record.write({'comment': record.comment})",
        })
        change.action_validate()
        change.action_apply()
        action = self.env['ir.actions.server'].search(
            [('name', '=', 'Evo Action')], limit=1
        )
        self.assertTrue(action)
        change.action_rollback()
        self.assertFalse(action.exists())

    def test_menu_cycle(self):
        change = self._change('menu', {
            'name': 'Evo Menu',
        })
        change.action_validate()
        change.action_apply()
        snapshot = json.loads(change.snapshot)
        menu = self.env['ir.ui.menu'].browse(snapshot['menu_id']).exists()
        self.assertTrue(menu)
        change.action_rollback()
        self.assertFalse(menu.exists())

    def test_invalid_field_name(self):
        change = self._change('field', {
            'model': 'res.partner',
            'name': 'evo_bad',
            'ttype': 'char',
        })
        with self.assertRaises(ValidationError):
            change.action_validate()

    def test_forbidden_code(self):
        change = self._change('action', {
            'model': 'res.partner',
            'name': 'Bad Action',
            'code': "record.sudo().write({'comment': 'x'})",
        })
        with self.assertRaises(ValidationError):
            change.action_validate()

    def test_rollback_requires_applied(self):
        change = self._change('field', {
            'model': 'res.partner',
            'name': 'x_evo_not_applied',
            'ttype': 'char',
            'help': 'Campo de prueba del rollback.',
        })
        change.action_validate()
        with self.assertRaises(UserError):
            change.action_rollback()

    def test_field_without_help_is_refused(self):
        change = self._change('field', {
            'model': 'res.partner',
            'name': 'x_evo_needs_help',
            'ttype': 'char',
            'field_description': 'No help',
        })
        with self.assertRaises(ValidationError):
            change.action_validate()
        self.assertEqual(change.status, 'draft')

    def test_field_help_can_be_disabled_by_setting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'odooclaw.require_field_help', 'False'
        )
        change = self._change('field', {
            'model': 'res.partner',
            'name': 'x_evo_no_help_allowed',
            'ttype': 'char',
            'field_description': 'No help, setting off',
        })
        change.action_validate()
        self.assertEqual(change.status, 'validated')

    def test_module_push_to_configured_repository(self):
        import os
        import shutil
        import subprocess
        import tempfile

        base = tempfile.mkdtemp(prefix="oc_repo_test_")
        bare = os.path.join(base, "bare.git")
        subprocess.run(["git", "init", "--bare", bare], check=True, capture_output=True)
        module_path = os.path.join(base, "oc_push_demo")
        os.makedirs(module_path)
        with open(os.path.join(module_path, "__manifest__.py"), "w") as fh:
            fh.write("{'name': 'Push demo', 'version': '18.0.1.0.0'}")
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("odooclaw.repo.url", "file://" + bare)
        icp.set_param("odooclaw.repo.token", "not-needed-local")
        icp.set_param("odooclaw.repo.branch", "main")
        icp.set_param("odooclaw.repo.author", "OdooClaw <bot@example.com>")
        change = self.Change.create({
            "name": "Push demo",
            "kind": "module",
            "level": "n2",
            "payload": json.dumps({"module": "oc_push_demo"}),
        })
        sha = change._push_module_to_repo("oc_push_demo", module_path)
        try:
            self.assertTrue(sha, "the push must return the commit hash")
            log = subprocess.run(
                ["git", "--git-dir", bare, "log", "--oneline", "main"],
                capture_output=True, text=True,
            )
            self.assertIn("oc_push_demo", log.stdout)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def _module_change(self, files):
        return self.Change.create({
            "name": "Module gate",
            "kind": "module",
            "level": "n2",
            "payload": json.dumps({"module": "oc_help_gate", "files": files}),
        })

    def _module_files(self, field_line):
        return {
            "__manifest__.py": "{'name': 'Gate', 'version': '18.0.1.0.0', 'depends': ['base'], 'installable': True}",
            "__init__.py": "from . import models\n",
            "models/__init__.py": "from . import demo\n",
            "models/demo.py": (
                "from odoo import fields, models\n\n\n"
                "class Demo(models.Model):\n"
                "    _name = 'x_gate_demo'\n"
                "    " + field_line + "\n"
            ),
        }

    def test_generated_field_without_help_is_refused(self):
        change = self._module_change(self._module_files("name = fields.Char()"))
        with self.assertRaises(ValidationError):
            change.action_validate()
        self.assertEqual(change.status, "draft")

    def test_generated_field_with_help_passes_validation(self):
        change = self._module_change(
            self._module_files('name = fields.Char(help="Nombre del registro.")')
        )
        change.action_validate()
        self.assertEqual(change.status, "validated")

    def _module_payload(self, files_extra=None):
        files = {
            '__manifest__.py': (
                "{'name': 'QA', 'version': '18.0.1.0.0', "
                "'depends': ['base'], 'installable': True}"
            ),
            '__init__.py': 'from . import models\n',
            'models/__init__.py': 'from . import thing\n',
            'models/thing.py': (
                'from odoo import fields, models\n\n\n'
                'class Thing(models.Model):\n'
                "    _name = 'oc.qa.acl'\n"
                "    _description = 'QA'\n\n"
                "    name = fields.Char(help='Name.')\n"
            ),
        }
        if files_extra:
            files.update(files_extra)
        return {'module': 'oc_qa_acl', 'files': files}

    def test_module_acl_is_generated(self):
        # A model nobody can read is dead on arrival: the generator writes its
        # access rules when the module does not ship a CSV.
        change = self._change('module', self._module_payload(), level='n2')
        normalized = change._ensure_module_acl(change._parse_payload())
        csv = normalized['files']['security/ir.model.access.csv']
        self.assertIn('access_oc_qa_acl_user', csv)
        self.assertIn('model_oc_qa_acl', csv)
        manifest = ast.literal_eval(normalized['files']['__manifest__.py'])
        self.assertIn('security/ir.model.access.csv', manifest['data'])

    def test_module_keeps_its_own_acl(self):
        own = 'id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n'
        change = self._change(
            'module',
            self._module_payload({'security/ir.model.access.csv': own}),
            level='n2',
        )
        normalized = change._ensure_module_acl(change._parse_payload())
        self.assertEqual(normalized['files']['security/ir.model.access.csv'], own)

    def test_module_without_models_needs_no_acl(self):
        payload = {
            'module': 'oc_qa_no_model',
            'files': {
                '__manifest__.py': (
                    "{'name': 'QA', 'version': '18.0.1.0.0', "
                    "'depends': ['base'], 'installable': True}"
                ),
                '__init__.py': '',
            },
        }
        change = self._change('module', payload, level='n2')
        normalized = change._ensure_module_acl(change._parse_payload())
        self.assertNotIn('security/ir.model.access.csv', normalized['files'])
