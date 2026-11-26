import json
import logging

from lxml import etree

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

CONTEXT_TAGS = ('field', 'group', 'page', 'button', 'notebook')


class OdooClawEvolutionApi(http.Controller):

    def _check_token(self):
        token = request.httprequest.headers.get('X-OdooClaw-Token')
        expected = request.env['ir.config_parameter'].sudo().get_param(
            'odooclaw_evolution.api_token'
        )
        if not expected or not token or token != expected:
            return False
        return True

    def _api_user(self):
        uid = int(request.env['ir.config_parameter'].sudo().get_param(
            'odooclaw_evolution.api_user_id'
        ) or 2)
        return request.env(user=uid)

    @http.route(
        '/odooclaw_evolution/api/context',
        type='json',
        auth='none',
        csrf=False,
        methods=['POST'],
    )
    def context(self, model=None, view_type='form', view_id=None, res_id=None,
                action_id=None, **kwargs):
        if not self._check_token():
            return {'error': 'unauthorized'}
        if not model:
            return {'error': 'model_required'}
        env = self._api_user()
        if model not in env:
            return {
                'error': 'model_not_found',
                'message': 'Unknown model %r. Use the technical model name, e.g. crm.lead.' % model,
            }
        record = env[model]
        record.check_access_rights('read')
        record.check_access_rule('read')
        options = {'toolbar': False, 'load_filters': False}
        if action_id:
            options['action_id'] = int(action_id)
        if res_id:
            options['res_id'] = int(res_id)
        views = [(int(view_id) if view_id else False, view_type)]
        result = record.get_views(views, options=options)
        view = (result.get('views') or {}).get(view_type) or {}
        model_info = (result.get('models') or {}).get(model) or {}
        arch = view.get('arch') or ''
        fields = view.get('fields') or model_info.get('fields') or {}
        points = []
        if arch:
            try:
                root = etree.fromstring(arch)
                for node in root.iter():
                    name = node.get('name')
                    if not name or node.tag not in CONTEXT_TAGS:
                        continue
                    points.append({
                        'tag': node.tag,
                        'name': name,
                        'string': node.get('string') or '',
                        'xpath': root.getroottree().getpath(node),
                    })
            except Exception:
                _logger.exception('OdooClaw context arch parse failed')
        resolved_view_id = view.get('id') or (int(view_id) if view_id else False)
        view_xmlid = ''
        if resolved_view_id:
            view_record = env['ir.ui.view'].browse(resolved_view_id)
            view_xmlid = view_record.get_external_id().get(resolved_view_id) or ''
        return {
            'model': model,
            'view_type': view_type,
            'view_id': resolved_view_id,
            'view_xmlid': view_xmlid,
            'arch': arch,
            'fields': fields,
            'insert_points': points,
            'models': result.get('models') or {},
        }

    @http.route(
        '/odooclaw_evolution/api/fields',
        type='json',
        auth='none',
        csrf=False,
        methods=['POST'],
    )
    def fields(self, model=None, filter=None, limit=200, **kwargs):
        if not self._check_token():
            return {'error': 'unauthorized'}
        if not model:
            return {'error': 'model_required'}
        env = self._api_user()
        if model not in env:
            return {'error': 'model_not_found'}
        record = env[model]
        record.check_access_rights('read')
        record.check_access_rule('read')
        needle = (filter or '').strip().lower()
        result = {}
        for name, info in record.fields_get().items():
            label = info.get('string') or ''
            if needle and needle not in name.lower() and needle not in label.lower():
                continue
            result[name] = {
                'type': info.get('type') or '',
                'string': label,
                'required': bool(info.get('required')),
                'readonly': bool(info.get('readonly')),
            }
            if len(result) >= max(1, int(limit or 200)):
                break
        return {'model': model, 'fields': result, 'count': len(result)}

    @http.route(
        '/odooclaw_evolution/api/change',
        type='json',
        auth='none',
        csrf=False,
        methods=['POST'],
    )
    def change(self, action=None, **kwargs):
        if not self._check_token():
            return {'error': 'unauthorized'}
        Change = request.env['odooclaw.change'].sudo()
        if action == 'propose':
            payload = kwargs.get('payload') or {}
            # Models like to wrap the payload under its kind
            # ({"view": {...}}). Accept it, store the canonical flat shape.
            if isinstance(payload, dict) and len(payload) == 1:
                key = next(iter(payload))
                if key in ('field', 'view', 'action', 'menu', 'module') and isinstance(payload[key], dict):
                    payload = payload[key]
            change = Change.create({
                'name': kwargs.get('name') or 'API change',
                'request_text': kwargs.get('request_text') or '',
                'kind': kwargs.get('kind') or 'field',
                'level': kwargs.get('level') or 'n1',
                'target_model': kwargs.get('target_model') or '',
                'target_module': kwargs.get('target_module') or '',
                'payload': json.dumps(payload),
            })
            try:
                change.action_validate()
            except Exception as error:  # noqa: BLE001
                return {
                    'id': change.id,
                    'reference': change.reference,
                    'status': change.status,
                    'validation_error': 'invalid_payload',
                    'message': str(error),
                }
            return {'id': change.id, 'reference': change.reference, 'status': change.status}
        change = Change.browse(int(kwargs.get('change_id') or 0)).exists()
        if not change:
            return {'error': 'not_found'}
        if action == 'apply':
            if change.status == 'draft':
                change.action_validate()
            change.action_apply()
            return {'id': change.id, 'status': change.status}
        if action == 'rollback':
            change.action_rollback()
            return {'id': change.id, 'status': change.status}
        if action == 'detail':
            return {
                'id': change.id,
                'reference': change.reference,
                'status': change.status,
                'kind': change.kind,
                'level': change.level,
                'target_model': change.target_model or '',
                'request_text': change.request_text or '',
                'payload': change.payload or '',
                'snapshot': change.snapshot or '',
                'note': change.note or '',
                'applied_at': str(change.applied_at or ''),
                'rolled_back_at': str(change.rolled_back_at or ''),
            }
        if action == 'status':
            return {'id': change.id, 'reference': change.reference, 'status': change.status}
        return {'error': 'unknown_action'}

    @http.route(
        '/odooclaw_evolution/api/overlay/run',
        type='json',
        auth='none',
        csrf=False,
        methods=['POST'],
    )
    def overlay_run(self, overlay=None, model=None, ids=None, params=None, shadow=False, **kwargs):
        if not self._check_token():
            return {'error': 'unauthorized'}
        Overlay = request.env['odooclaw.overlay'].sudo()
        overlay_record = Overlay.search([('code', '=', overlay)], limit=1)
        if not overlay_record:
            return {'error': 'overlay_not_found'}
        env = request.env(user=overlay_record.user_id.id)
        run = env['odooclaw.overlay.run'].create({
            'overlay_id': overlay_record.id,
            'model': model,
            'res_ids': ','.join(str(item) for item in (ids or [])),
            'params': json.dumps(params or {}),
            'shadow': bool(shadow),
        })
        try:
            run.action_run()
        except Exception as exc:
            current = Overlay.browse(overlay_record.id)
            return {
                'error': str(exc),
                'mode': current.mode,
                'failure_count': current.failure_count,
            }
        current = Overlay.browse(overlay_record.id)
        return {
            'overlay': current.code,
            'mode': current.mode,
            'failure_count': current.failure_count,
        }
