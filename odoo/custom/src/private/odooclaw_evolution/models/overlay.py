import json
import logging

import requests

from odoo import SUPERUSER_ID, api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

ALLOWED_OPS = ('write', 'create', 'unlink', 'raise')
SENSITIVE_MODELS = (
    'ir.model',
    'ir.model.fields',
    'ir.ui.view',
    'ir.rule',
    'ir.config_parameter',
    'ir.actions.server',
    'ir.module.module',
    'res.users',
    'res.groups',
)
SENSITIVE_KEYS = ('sudo', '__', 'ir.', 'res.users', 'res.groups')
PROTECTED_FIELDS = ('id', 'create_uid', 'create_date', 'write_uid', 'write_date')
MAX_OPERATIONS = 20
MAX_RECORDS = 100


class OdooClawOverlay(models.Model):
    _name = 'odooclaw.overlay'
    _description = 'OdooClaw overlay rule'
    _order = 'id desc'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    endpoint = fields.Char(
        required=True,
        default='http://forge-overlay:8099/plan',
        help='HTTP endpoint of the overlay host.',
    )
    mode = fields.Selection(
        [('shadow', 'Shadow'), ('active', 'Active'), ('disabled', 'Disabled')],
        default='shadow',
        required=True,
    )
    user_id = fields.Many2one(
        'res.users',
        required=True,
        default=lambda self: self.env.user,
        help='Business operations run with this user, never with sudo().',
    )
    max_failures = fields.Integer(default=3)
    failure_count = fields.Integer(default=0, readonly=True)
    last_error = fields.Text(readonly=True)
    active = fields.Boolean(default=True)
    allow_automations = fields.Boolean(
        default=False,
        help='Allow writes that can trigger tracked fields or active automations.',
    )
    plan_ids = fields.One2many('odooclaw.plan', 'overlay_id')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Overlay code must be unique.'),
    ]

    def _call_host(self, payload):
        self.ensure_one()
        try:
            response = requests.post(self.endpoint, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise UserError(_('Overlay host error: %s', exc)) from exc

    def _validate_plan(self, plan, payload):
        if not isinstance(plan, dict) or plan.get('version') != 1:
            raise ValidationError(_('Invalid plan version.'))
        operations = plan.get('operations')
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
            raise ValidationError(
                _('Plan must contain between 1 and %s operations.', MAX_OPERATIONS)
            )
        model = payload.get('model') or ''
        if model not in self.env.registry.models:
            raise ValidationError(_('Unknown model: %s', model))
        if model in SENSITIVE_MODELS:
            raise ValidationError(_('Model not allowed: %s', model))
        fields = self.env[model]._fields
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValidationError(_('Operation must be an object.'))
            kind = operation.get('op')
            if kind not in ALLOWED_OPS:
                raise ValidationError(_('Operation not allowed: %s', kind))
            operation_model = operation.get('model') or model
            if operation_model != model:
                raise ValidationError(_('Operation model must match the request model.'))
            operation['model'] = model
            ids = operation.get('ids') or []
            if kind == 'create':
                if ids:
                    raise ValidationError(_('Create does not accept ids.'))
            elif kind in ('write', 'unlink'):
                if not isinstance(ids, list) or not ids or len(ids) > MAX_RECORDS:
                    raise ValidationError(
                        _('Operation needs between 1 and %s ids.', MAX_RECORDS)
                    )
                if any(not isinstance(item, int) for item in ids):
                    raise ValidationError(_('Ids must be integers.'))
                if kind == 'unlink' and payload.get('shadow'):
                    raise ValidationError(_('Unlink is not allowed in shadow mode.'))
            if kind in ('write', 'create'):
                values = operation.get('values')
                if not isinstance(values, dict) or not values:
                    raise ValidationError(_('Operation needs values.'))
                for key, value in values.items():
                    if key not in fields:
                        raise ValidationError(_('Unknown field: %s', key))
                    if key in PROTECTED_FIELDS:
                        raise ValidationError(_('Field not allowed: %s', key))
                    if any(token in key for token in SENSITIVE_KEYS):
                        raise ValidationError(_('Field not allowed: %s', key))
                    if isinstance(value, str) and 'sudo(' in value:
                        raise ValidationError(_('sudo() is not allowed.'))
            if kind == 'raise':
                message = operation.get('message') or ''
                if not isinstance(message, str) or not 1 <= len(message) <= 500:
                    raise ValidationError(
                        _('Raise needs a message up to 500 characters.')
                    )
        return True

    def _validate_permissions(self, plan, payload):
        model_name = payload['model']
        model = self.env[model_name]
        for operation in plan['operations']:
            kind = operation['op']
            if kind == 'create':
                model.check_access_rights('create')
                company_id = operation['values'].get('company_id')
                if company_id and company_id not in self.env.companies.ids:
                    raise ValidationError(_('Company not allowed: %s', company_id))
            elif kind in ('write', 'unlink'):
                records = model.browse(operation['ids']).exists()
                if len(records) != len(operation['ids']):
                    raise ValidationError(_('Some records do not exist.'))
                records.check_access_rights('write' if kind == 'write' else 'unlink')
                records.check_access_rule('write' if kind == 'write' else 'unlink')
                if 'company_id' in model._fields:
                    for record in records:
                        if record.company_id and record.company_id not in self.env.companies:
                            raise ValidationError(
                                _('Record %s belongs to company %s, not allowed for this user.',
                                  record.id, record.company_id.display_name)
                            )
        return True

    def _validate_effects(self, plan, payload):
        model_name = payload['model']
        model = self.env[model_name]
        fields = model._fields
        for operation in plan['operations']:
            if operation['op'] in ('write', 'create'):
                for key in operation['values']:
                    if getattr(fields[key], 'tracking', False) and not self.allow_automations:
                        raise ValidationError(
                            _('Field %s is tracked and can post a message. '
                              'Enable automations to allow it.', key)
                        )
        if self.allow_automations:
            return True
        if 'base.automation' not in self.env.registry.models:
            return True
        automations = self.env['base.automation'].sudo().search([
            ('active', '=', True),
            ('model_id.model', '=', model_name),
            ('trigger', 'in', ('on_create', 'on_write', 'on_unlink')),
        ])
        if automations:
            raise ValidationError(
                _('Active automations on %s: %s. Enable automations to allow it.',
                  model_name, ', '.join(automations.mapped('name')))
            )
        return True

    def _apply_plan(self, plan):
        for operation in plan['operations']:
            kind = operation['op']
            model = operation['model']
            if kind == 'write':
                self.env[model].browse(operation['ids']).write(operation['values'])
            elif kind == 'create':
                self.env[model].create(operation['values'])
            elif kind == 'unlink':
                self.env[model].browse(operation['ids']).unlink()
            elif kind == 'raise':
                raise UserError(operation['message'])

    def _record_failure(self, payload, plan, error, state='failed'):
        self.ensure_one()
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            overlay = env['odooclaw.overlay'].browse(self.id)
            new_count = overlay.failure_count + 1
            values = {
                'failure_count': new_count,
                'last_error': str(error)[:2000],
            }
            if new_count >= overlay.max_failures:
                values['mode'] = 'disabled'
            overlay.write(values)
            env['odooclaw.plan'].create({
                'overlay_id': self.id,
                'user_id': self.env.user.id,
                'company_id': self.env.company.id,
                'request': json.dumps(payload, ensure_ascii=False),
                'plan': json.dumps(plan or {}, ensure_ascii=False),
                'state': state,
                'result': str(error)[:2000],
            })
            cr.commit()

    def action_reset(self):
        self.write({'failure_count': 0, 'last_error': False, 'mode': 'shadow'})
        return True

    def action_open_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Plans',
            'res_model': 'odooclaw.plan',
            'view_mode': 'list,form',
            'domain': [('overlay_id', '=', self.id)],
            'context': {'default_overlay_id': self.id},
        }


class OdooClawPlan(models.Model):
    _name = 'odooclaw.plan'
    _description = 'OdooClaw overlay plan'
    _order = 'id desc'

    overlay_id = fields.Many2one('odooclaw.overlay', required=True, ondelete='cascade')
    user_id = fields.Many2one(
        'res.users', required=True, default=lambda self: self.env.user
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company
    )
    request = fields.Text(readonly=True)
    plan = fields.Text(readonly=True)
    state = fields.Selection(
        [
            ('shadow', 'Shadow'),
            ('applied', 'Applied'),
            ('rejected', 'Rejected'),
            ('failed', 'Failed'),
        ],
        default='shadow',
        required=True,
    )
    result = fields.Text(readonly=True)


class OdooClawOverlayRun(models.TransientModel):
    _name = 'odooclaw.overlay.run'
    _description = 'Run an overlay rule'

    overlay_id = fields.Many2one('odooclaw.overlay', required=True)
    model = fields.Char(required=True)
    res_ids = fields.Char(help='Comma-separated record ids.')
    params = fields.Text(default='{}')
    shadow = fields.Boolean(default=False)

    def _parse_ids(self):
        raw = (self.res_ids or '').strip()
        if not raw:
            return []
        try:
            ids = [int(part.strip()) for part in raw.split(',') if part.strip()]
        except ValueError as exc:
            raise ValidationError(_('Record ids must be integers.')) from exc
        if len(ids) > MAX_RECORDS:
            raise ValidationError(_('At most %s records.', MAX_RECORDS))
        return ids

    def _parse_params(self):
        try:
            params = json.loads(self.params or '{}')
        except ValueError as exc:
            raise ValidationError(_('Params must be valid JSON.')) from exc
        if not isinstance(params, dict):
            raise ValidationError(_('Params must be a JSON object.'))
        return params

    def action_run(self):
        self.ensure_one()
        overlay = self.overlay_id
        if overlay.mode == 'disabled':
            raise UserError(_('Overlay is disabled. Reset it before running again.'))
        if not overlay.active:
            raise UserError(_('Overlay is archived.'))
        shadow = True if overlay.mode == 'shadow' else self.shadow
        payload = {
            'version': 1,
            'rule': overlay.code,
            'model': self.model,
            'ids': self._parse_ids(),
            'params': self._parse_params(),
            'shadow': shadow,
        }
        plan = None
        try:
            plan = overlay._call_host(payload)
            overlay._validate_plan(plan, payload)
            overlay._validate_permissions(plan, payload)
            overlay._validate_effects(plan, payload)
            plan_record = self.env['odooclaw.plan'].create({
                'overlay_id': overlay.id,
                'user_id': self.env.user.id,
                'company_id': self.env.company.id,
                'request': json.dumps(payload, ensure_ascii=False),
                'plan': json.dumps(plan, ensure_ascii=False),
                'state': 'shadow' if shadow else 'applied',
            })
            if not shadow:
                with self.env.cr.savepoint():
                    overlay._apply_plan(plan)
                plan_record.write({'result': 'applied'})
            return {'type': 'ir.actions.act_window_close'}
        except ValidationError as exc:
            overlay._record_failure(payload, plan, exc, state='rejected')
            raise
        except UserError as exc:
            overlay._record_failure(payload, plan, exc, state='rejected')
            raise
        except Exception as exc:
            _logger.exception('Overlay run failed')
            overlay._record_failure(payload, plan, exc, state='failed')
            raise
