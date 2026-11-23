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
