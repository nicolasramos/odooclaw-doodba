import hashlib
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

LEVELS = [
    ('n0', 'N0 · Data'),
    ('n1', 'N1 · Metadata'),
    ('n2', 'N2 · New module'),
    ('n3', 'N3 · Existing module'),
]

KINDS = [
    ('field', 'Field'),
    ('view', 'View'),
    ('action', 'Server action'),
    ('menu', 'Menu'),
]

STATUSES = [
    ('draft', 'Draft'),
    ('validated', 'Validated'),
    ('applied', 'Applied'),
    ('rolled_back', 'Rolled back'),
    ('failed', 'Failed'),
]

ALLOWED_FIELD_TYPES = (
    'char', 'text', 'integer', 'float', 'boolean', 'date', 'datetime',
)

FORBIDDEN_CODE_TOKENS = (
    'sudo(', '__import__', 'open(', 'eval(', 'exec(', 'compile(',
)


class OdooClawChange(models.Model):
    _name = 'odooclaw.change'
    _description = 'OdooClaw change ledger'
    _order = 'id desc'

    name = fields.Char(required=True)
    reference = fields.Char(readonly=True, copy=False, default='/')
    request_text = fields.Text()
    level = fields.Selection(LEVELS, required=True, default='n1')
    kind = fields.Selection(KINDS, required=True)
    status = fields.Selection(STATUSES, required=True, default='draft')
    target_model = fields.Char()
    payload = fields.Text()
    snapshot = fields.Text()
    artifact_hash = fields.Char(readonly=True)
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    applied_at = fields.Datetime(readonly=True)
    rolled_back_at = fields.Datetime(readonly=True)
    note = fields.Text()
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', '/') == '/':
                vals['reference'] = self.env['ir.sequence'].next_by_code('odooclaw.change') or '/'
            if vals.get('payload'):
                vals['artifact_hash'] = hashlib.sha256(vals['payload'].encode()).hexdigest()
        return super().create(vals_list)

    def write(self, vals):
        if 'payload' in vals and vals['payload']:
            vals['artifact_hash'] = hashlib.sha256(vals['payload'].encode()).hexdigest()
        return super().write(vals)

    def _parse_payload(self):
        self.ensure_one()
        try:
            payload = json.loads(self.payload or '{}')
        except ValueError as exc:
            raise ValidationError(_('Invalid payload JSON: %s', exc))
        if not isinstance(payload, dict):
            raise ValidationError(_('Payload must be a JSON object.'))
        return payload

    def action_validate(self):
        for change in self:
            change._validate_payload(change._parse_payload())
            change.write({
                'status': 'validated',
                'approved_by': self.env.user.id,
            })
        return True

    def _validate_payload(self, payload):
        self.ensure_one()
        if self.kind == 'field':
            self._validate_field(payload)
        elif self.kind == 'view':
            self._validate_view(payload)
        elif self.kind == 'action':
            self._validate_action(payload)
        elif self.kind == 'menu':
            self._validate_menu(payload)
        else:
            raise ValidationError(_('Unsupported change kind: %s', self.kind))

    def _validate_field(self, payload):
        items = payload.get('field')
        if isinstance(items, dict):
            self._validate_single_field(items)
            return
        if isinstance(items, list):
            if not items:
                raise ValidationError(_('Field payload requires at least one field.'))
            for item in items:
                self._validate_single_field(item)
            return
        self._validate_single_field(payload)

    def _validate_single_field(self, payload):
        model = payload.get('model')
        name = payload.get('name')
        ttype = payload.get('ttype')
        if not model or not name or not ttype:
            raise ValidationError(_('Field payload requires model, name and ttype.'))
        if not name.startswith('x_'):
            name = 'x_' + name
            payload['name'] = name
        if ttype not in ALLOWED_FIELD_TYPES:
            raise ValidationError(_('Field type %s is not allowed in N1.', ttype))
        if model not in self.env:
            raise ValidationError(_('Unknown model: %s', model))
        existing = self.env['ir.model.fields'].sudo().search([
            ('model', '=', model),
            ('name', '=', name),
        ], limit=1)
        if existing:
            raise ValidationError(_('Field %(model)s.%(name)s already exists.', model=model, name=name))

    def _validate_view(self, payload):
        if not payload.get('model') or not payload.get('arch'):
            raise ValidationError(_('View payload requires model and arch.'))
        if '<data' not in payload['arch']:
            raise ValidationError(_('Inherited view arch must be a <data> element.'))
        if payload.get('inherit_xmlid') and not self.env.ref(payload['inherit_xmlid'], raise_if_not_found=False):
            raise ValidationError(_('Unknown view xmlid: %s', payload['inherit_xmlid']))

    def _validate_action(self, payload):
        if not payload.get('model') or not payload.get('code'):
            raise ValidationError(_('Action payload requires model and code.'))
        if payload['model'] not in self.env:
            raise ValidationError(_('Unknown model: %s', payload['model']))
        code = payload['code']
        for token in FORBIDDEN_CODE_TOKENS:
            if token in code:
                raise ValidationError(_('Action code contains a forbidden token: %s', token))

    def _validate_menu(self, payload):
        if not payload.get('name'):
            raise ValidationError(_('Menu payload requires name.'))
        for key in ('parent_xmlid', 'action_xmlid'):
            if payload.get(key) and not self.env.ref(payload[key], raise_if_not_found=False):
                raise ValidationError(_('Unknown xmlid in %(key)s: %(value)s', key=key, value=payload[key]))

    def action_apply(self):
        for change in self:
            if change.status != 'validated':
                raise UserError(_('Only validated changes can be applied.'))
            payload = change._parse_payload()
            change._validate_payload(payload)
            snapshot = change._apply_payload(payload)
            change.write({
                'status': 'applied',
                'snapshot': json.dumps(snapshot, default=str),
                'applied_at': fields.Datetime.now(),
            })
        return True

    def _apply_payload(self, payload):
        self.ensure_one()
        if self.kind == 'field':
            return self._apply_field(payload)
        if self.kind == 'view':
            return self._apply_view(payload)
        if self.kind == 'action':
            return self._apply_action(payload)
        if self.kind == 'menu':
            return self._apply_menu(payload)
        raise UserError(_('Unsupported change kind: %s', self.kind))

    def _apply_field(self, payload):
        items = payload.get('field')
        if isinstance(items, dict):
            return self._apply_single_field(items)
        if isinstance(items, list):
            return {
                'kind': 'fields',
                'fields': [self._apply_single_field(item) for item in items],
                'existed': False,
            }
        return self._apply_single_field(payload)

    def _apply_single_field(self, payload):
        model = self.env['ir.model'].sudo()._get(payload['model'])
        field = self.env['ir.model.fields'].sudo().create({
            'model_id': model.id,
            'name': payload['name'],
            'field_description': payload.get('field_description') or payload['name'],
            'ttype': payload['ttype'],
            'required': bool(payload.get('required')),
            'help': payload.get('help') or False,
            'state': 'manual',
        })
        view = self._place_field_in_form(payload['model'], field)
        return {
            'kind': 'field',
            'field_id': field.id,
            'view_id': view.id if view else False,
            'existed': False,
        }

    def _place_field_in_form(self, model_name, field):
        """Insert the new field into the model's default form view.

        A manual field that is not placed anywhere is invisible in the UI, so
        the field change also creates an inherited view. The anchor is the
        first of partner_id/name/user_id present on the model; the insertion
        goes right after it.
        """
        view = self.env['ir.ui.view'].sudo().search([
            ('model', '=', model_name),
            ('type', '=', 'form'),
            ('inherit_id', '=', False),
        ], order='priority, id', limit=1)
        if not view:
            return None
        model_fields = self.env[model_name]._fields
        anchor = None
        for candidate in ('partner_id', 'name', 'user_id'):
            if candidate in model_fields:
                anchor = candidate
                break
        if not anchor:
            return None
        arch = (
            '<data><field name="%s" position="after">'
            '<field name="%s"/></field></data>'
        ) % (anchor, field.name)
        new_view = self.env['ir.ui.view'].sudo().create({
            'name': 'odooclaw.%s.%s' % (model_name, field.name),
            'model': model_name,
            'inherit_id': view.id,
            'arch': arch,
            'priority': 99,
        })
        self.env['ir.ui.view'].flush_model()
        self.env['ir.ui.view'].clear_caches()
        self.env.registry.clear_cache()
        return new_view

    def _apply_view(self, payload):
        inherit = False
        if payload.get('inherit_xmlid'):
            inherit = self.env.ref(payload['inherit_xmlid']).id
        elif payload.get('inherit_id'):
            inherit = int(payload['inherit_id'])
        view = self.env['ir.ui.view'].sudo().create({
            'name': payload.get('name') or 'odooclaw.view',
            'model': payload['model'],
            'inherit_id': inherit,
            'arch': payload['arch'],
            'priority': int(payload.get('priority') or 99),
        })
        self.env['ir.ui.view'].flush_model()
        self.env['ir.ui.view'].clear_caches()
        self.env.registry.clear_cache()
        return {'kind': 'view', 'view_id': view.id, 'existed': False}

    def _apply_action(self, payload):
        model = self.env['ir.model'].sudo()._get(payload['model'])
        action = self.env['ir.actions.server'].sudo().create({
            'name': payload.get('name') or 'OdooClaw action',
            'model_id': model.id,
            'state': 'code',
            'code': payload['code'],
        })
        return {'kind': 'action', 'action_id': action.id, 'existed': False}

    def _apply_menu(self, payload):
        parent = False
        if payload.get('parent_xmlid'):
            parent = self.env.ref(payload['parent_xmlid']).id
        action_record = False
        if payload.get('action_xmlid'):
            action_record = self.env.ref(payload['action_xmlid'])
        menu = self.env['ir.ui.menu'].sudo().create({
            'name': payload['name'],
            'parent_id': parent,
            'action': action_record and '%s,%s' % (action_record._name, action_record.id) or False,
            'sequence': int(payload.get('sequence') or 99),
        })
        return {'kind': 'menu', 'menu_id': menu.id, 'existed': False}

    def action_rollback(self):
        for change in self:
            if change.status != 'applied':
                raise UserError(_('Only applied changes can be rolled back.'))
            snapshot = json.loads(change.snapshot or '{}')
            change._rollback_snapshot(snapshot)
            change.write({
                'status': 'rolled_back',
                'rolled_back_at': fields.Datetime.now(),
            })
        return True

    def _rollback_snapshot(self, snapshot):
        self.ensure_one()
        kind = snapshot.get('kind')
        if kind == 'field':
            if snapshot.get('view_id'):
                view = self.env['ir.ui.view'].sudo().browse(snapshot['view_id']).exists()
                if view:
                    view.unlink()
                self.env['ir.ui.view'].clear_caches()
                self.env.registry.clear_cache()
            field = self.env['ir.model.fields'].sudo().browse(snapshot['field_id']).exists()
            if field:
                field.unlink()
            return
        if kind == 'fields':
            for item in snapshot.get('fields', []):
                field = self.env['ir.model.fields'].sudo().browse(item.get('field_id')).exists()
                if field:
                    field.unlink()
            return
        if kind == 'view':
            view = self.env['ir.ui.view'].sudo().browse(snapshot['view_id']).exists()
            if view:
                view.unlink()
            self.env['ir.ui.view'].clear_caches()
            self.env.registry.clear_cache()
            return
        if kind == 'action':
            action = self.env['ir.actions.server'].sudo().browse(snapshot['action_id']).exists()
            if action:
                action.unlink()
            return
        if kind == 'menu':
            menu = self.env['ir.ui.menu'].sudo().browse(snapshot['menu_id']).exists()
            if menu:
                menu.unlink()
            return
        raise UserError(_('Unknown snapshot kind: %s', kind))
