import ast
import pprint
import hashlib
import json

from lxml import etree
import logging
import os
import re
import shutil
import subprocess
import tempfile

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
    ('module', 'Python module'),
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
    'selection',
)

FORBIDDEN_CODE_TOKENS = (
    'sudo(', '__import__', 'open(', 'eval(', 'exec(', 'compile(',
)

ALLOWED_MODULE_IMPORTS = {
    'odoo', 'datetime', 'decimal', 'logging', 'json', 'math', 're',
    'collections', 'itertools', 'functools', 'uuid', 'hashlib', 'base64',
    'zoneinfo', 'dateutil', 'pytz',
}
FORBIDDEN_MODULE_NAMES = {
    'eval', 'exec', 'compile', 'open', '__import__', 'globals', 'locals',
    'vars', '__builtins__', 'input', 'breakpoint', 'getattr', 'setattr',
    'delattr',
}
MAX_MODULE_BYTES = 200_000
MODULE_NAME_RE = re.compile(r'^oc_[a-z0-9_]{2,40}$')
MODULE_FILE_RE = re.compile(r'^[A-Za-z0-9_./-]+$')

# Field constructors the generated code can use. Every one must carry a help
# text: the rule is the same as for N1 fields, enforced here by reading the AST.
FIELD_CONSTRUCTORS = {
    'Char', 'Text', 'Html', 'Integer', 'Float', 'Monetary', 'Boolean', 'Date',
    'Datetime', 'Selection', 'Many2one', 'One2many', 'Many2many', 'Binary',
    'Json', 'Reference', 'Image',
}


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
    target_module = fields.Char(
        help='Module being modified by an N3 change; must be installed.',
    )
    payload = fields.Text()
    snapshot = fields.Text()
    artifact_hash = fields.Char(readonly=True)
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    applied_at = fields.Datetime(readonly=True)
    repo_commit = fields.Char(
        readonly=True,
        help='Commit in the bot repository holding the generated module, when a repository is configured.',
    )
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
            payload = change._parse_payload()
            change._validate_payload(payload)
            vals = {
                'status': 'validated',
                'approved_by': self.env.user.id,
            }
            if change.kind == 'module':
                normalized = change._ensure_module_acl(payload)
                if normalized is not payload:
                    vals['payload'] = json.dumps(
                        normalized, ensure_ascii=False, sort_keys=True
                    )
            change.write(vals)
        return True

    def _validate_level(self):
        """The level must match the kind: N1 metadata only, N2 a new module,
        N3 an installed module whose behaviour is changed."""
        if self.kind == 'module':
            if self.level in ('n0', 'n1'):
                raise ValidationError(
                    _('N1 is metadata only. A module change must be N2 (new module) or N3 (existing module).')
                )
            if self.level == 'n2' and (self.target_module or '').strip():
                raise ValidationError(
                    _('N2 creates a new module; leave target_module empty.')
                )
            if self.level == 'n3':
                target = (self.target_module or '').strip()
                if not target:
                    raise ValidationError(
                        _('N3 requires target_module: the installed module whose logic is changed.')
                    )
                if not self.env['ir.module.module'].search_count(
                    [('name', '=', target), ('state', '=', 'installed')]
                ):
                    raise ValidationError(_('Target module %s is not installed.', target))
        else:
            if self.level in ('n2', 'n3'):
                raise ValidationError(
                    _('N2 and N3 are for module changes only. Use N1 for field, view, action or menu changes.')
                )

    def _validate_payload(self, payload):
        self.ensure_one()
        self._validate_level()
        if self.kind == 'field':
            self._validate_field(payload)
        elif self.kind == 'view':
            self._validate_view(payload)
        elif self.kind == 'action':
            self._validate_action(payload)
        elif self.kind == 'menu':
            self._validate_menu(payload)
        elif self.kind == 'module':
            self._validate_module(payload)
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

    def _require_field_help(self):
        """Whether a created field must explain itself (on by default)."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'odooclaw.require_field_help', 'True'
        )
        return str(value).lower() not in ('false', '0', '')

    def _validate_single_field(self, payload):
        model = payload.get('model')
        name = payload.get('name')
        ttype = payload.get('ttype')
        if not model or not name or not ttype:
            raise ValidationError(_('Field payload requires model, name and ttype.'))
        help_text = (payload.get('help') or '').strip()
        if self._require_field_help() and not help_text:
            raise ValidationError(_(
                'Field %(model)s.%(name)s needs a help text: whoever uses it '
                'has to know what it is for. Add it, or turn off '
                '"Require help on created fields" in the OdooClaw settings.',
                model=model, name=name,
            ))
        payload['help'] = help_text
        if not name.startswith('x_'):
            name = 'x_' + name
            payload['name'] = name
        if ttype not in ALLOWED_FIELD_TYPES:
            raise ValidationError(_('Field type %s is not allowed for N1 changes.', ttype))
        if ttype == 'selection':
            values = payload.get('selection') or []
            if not isinstance(values, list) or not values:
                raise ValidationError(_('Selection fields require a non-empty selection list.'))
            for item in values:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    raise ValidationError(_('Each selection value must be a [value, label] pair.'))
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
        try:
            etree.fromstring(payload['arch'])
        except Exception as error:  # noqa: BLE001
            raise ValidationError(_('The view arch is not valid XML: %s', error))
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


    def _module_new_models(self, files):
        """Models the module actually creates, so their access rules are not forgotten.

        A class with ``_inherit`` only extends an existing model and inherits its
        ACL. A class with ``_name`` has its own table and starts with no access at
        all: a model nobody can read is dead on arrival, so the generator grants
        internal users the four operations unless the module ships its own CSV.
        """
        names = []
        for rel, content in (files or {}).items():
            if not rel.startswith('models/') or not rel.endswith('.py'):
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                declared = None
                inherits = []
                for stmt in node.body:
                    if not (
                        isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                    ):
                        continue
                    key = stmt.targets[0].id
                    value = stmt.value
                    if key == '_name' and isinstance(value, ast.Constant) and isinstance(value.value, str):
                        declared = value.value
                    elif key == '_inherit':
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            inherits.append(value.value)
                        elif isinstance(value, (ast.List, ast.Tuple)):
                            inherits.extend(
                                el.value
                                for el in value.elts
                                if isinstance(el, ast.Constant) and isinstance(el.value, str)
                            )
                if declared and declared not in inherits and declared not in names:
                    names.append(declared)
        return names

    def _acl_csv(self, models):
        rows = ['id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink']
        for model in sorted(models):
            key = model.replace('.', '_')
            rows.append(
                'access_%s_user,access %s user,model_%s,base.group_user,1,1,1,1'
                % (key, model, key)
            )
        return '\n'.join(rows) + '\n'

    def _ensure_module_acl(self, payload):
        files = payload.get('files') or {}
        acl_rel = 'security/ir.model.access.csv'
        models = self._module_new_models(files)
        if not models or acl_rel in files:
            return payload
        files = dict(files)
        files[acl_rel] = self._acl_csv(models)
        try:
            manifest = ast.literal_eval(files['__manifest__.py'])
        except (ValueError, SyntaxError):
            return payload
        data = list(manifest.get('data') or [])
        if acl_rel not in data:
            data.append(acl_rel)
        manifest['data'] = data
        files['__manifest__.py'] = pprint.pformat(manifest, width=100, sort_dicts=False) + '\n'
        payload = dict(payload)
        payload['files'] = files
        return payload

    def _validate_module(self, payload):
        module = (payload.get('module') or '').strip()
        if not MODULE_NAME_RE.match(module):
            raise ValidationError(_('Module name must match oc_<slug>.'))
        files = payload.get('files')
        if not isinstance(files, dict) or not files:
            raise ValidationError(_('Module payload requires a files object.'))
        for name in ('__manifest__.py', '__init__.py'):
            if name not in files:
                raise ValidationError(_('Module is missing %s.', name))
        total = 0
        for rel, content in files.items():
            if (
                not isinstance(rel, str)
                or not MODULE_FILE_RE.match(rel)
                or '..' in rel
                or rel.startswith('/')
            ):
                raise ValidationError(_('Invalid module file path: %s', rel))
            if not isinstance(content, str):
                raise ValidationError(_('File %s must be text.', rel))
            total += len(content)
            if rel.endswith('.py'):
                self._validate_module_python(rel, content)
        if total > MAX_MODULE_BYTES:
            raise ValidationError(_('Module exceeds the %s byte limit.', MAX_MODULE_BYTES))
        try:
            manifest = ast.literal_eval(files['__manifest__.py'])
        except (ValueError, SyntaxError):
            raise ValidationError(_('Manifest must be a Python literal dict.'))
        if not isinstance(manifest, dict):
            raise ValidationError(_('Manifest must be a dict.'))
        version = str(manifest.get('version') or '')
        if not version.startswith('18.0.'):
            raise ValidationError(_('Manifest version must start with 18.0.'))
        if not manifest.get('installable', True):
            raise ValidationError(_('Module must be installable.'))
        depends = manifest.get('depends') or []
        if not isinstance(depends, list):
            raise ValidationError(_('Manifest depends must be a list.'))
        for dep in depends:
            if not isinstance(dep, str) or not self.env['ir.module.module'].search_count(
                [('name', '=', dep), ('state', '=', 'installed')]
            ):
                raise ValidationError(_('Dependency %s is not installed.', dep))
        if self.level == 'n3':
            target = (self.target_module or '').strip()
            if target and target not in depends:
                raise ValidationError(
                    _('The N3 module must declare %s in its depends.', target)
                )

    def _validate_module_python(self, rel, content):
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            raise ValidationError(
                _('Syntax error in %(file)s: %(err)s', file=rel, err=exc)
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split('.')[0]
                    if root not in ALLOWED_MODULE_IMPORTS:
                        raise ValidationError(
                            _('Import not allowed in %(file)s: %(mod)s', file=rel, mod=alias.name)
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                root = (node.module or '').split('.')[0]
                if root not in ALLOWED_MODULE_IMPORTS:
                    raise ValidationError(
                        _('Import not allowed in %(file)s: %(mod)s', file=rel, mod=node.module)
                    )
            elif isinstance(node, ast.Attribute):
                if node.attr == 'sudo':
                    raise ValidationError(_('sudo() is not allowed in generated code.'))
            elif isinstance(node, ast.Name):
                if node.id in FORBIDDEN_MODULE_NAMES:
                    raise ValidationError(
                        _('Name %(name)s is not allowed in generated code (%(file)s).', name=node.id, file=rel)
                    )
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_MODULE_NAMES:
                    raise ValidationError(
                        _('Call to %(name)s is not allowed in generated code (%(file)s).', name=func.id, file=rel)
                    )
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == 'fields'
                    and func.attr in FIELD_CONSTRUCTORS
                    and not any(kw.arg == 'help' for kw in node.keywords)
                ):
                    raise ValidationError(_(
                        'Field %(field)s in %(file)s needs a help text: whoever '
                        'uses it has to know what it is for.',
                        field=func.attr, file=rel,
                    ))

    def action_apply(self):
        for change in self:
            if change.status != 'validated':
                raise UserError(_('Only validated changes can be applied.'))
            payload = change._parse_payload()
            change._validate_payload(payload)
            snapshot = change._apply_payload(payload)
            vals = {
                'status': 'applied',
                'applied_at': fields.Datetime.now(),
            }
            if change.kind == 'module':
                # The generated module lives on the container filesystem, which
                # a fresh deploy replaces. When a bot repository is configured,
                # the module goes there too: same record, durable copy.
                commit = change._push_module_to_repo(
                    snapshot.get('module'), snapshot.get('path')
                )
                if commit:
                    snapshot['repo_commit'] = commit
                    vals['repo_commit'] = commit
            vals['snapshot'] = json.dumps(snapshot, default=str)
            change.write(vals)
        return True

    def _repo_settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'url': (icp.get_param('odooclaw.repo.url') or '').strip(),
            'token': (icp.get_param('odooclaw.repo.token') or '').strip(),
            'branch': (icp.get_param('odooclaw.repo.branch') or '').strip() or 'main',
            'author': (icp.get_param('odooclaw.repo.author') or '').strip()
            or 'OdooClaw <bot@example.com>',
        }

    @staticmethod
    def _repo_auth_url(url, token):
        """Put the token in the URL when it is https and looks like GitHub."""
        if not token or not url.startswith('https://'):
            return url
        scheme, rest = url.split('://', 1)
        return '%s://x-access-token:%s@%s' % (scheme, token, rest)

    def _push_module_to_repo(self, module_name, module_path):
        """Commit the generated module to the bot's own repository.

        Returns the commit hash, or an empty string when no repository is
        configured (the default: nothing leaves the instance) or when it is
        misconfigured. A failed push never breaks the change: the module is
        installed either way, and the failure is logged with its reason.
        """
        self.ensure_one()
        settings = self._repo_settings()
        if not settings['url']:
            return ''
        if not module_name or not module_path or not os.path.isdir(module_path):
            _logger.warning('odooclaw: cannot push module without a path: %s', module_name)
            return ''
        if not os.path.isabs(module_path):
            module_path = os.path.abspath(module_path)
        workdir = tempfile.mkdtemp(prefix='oc_repo_')
        try:
            auth_url = self._repo_auth_url(settings['url'], settings['token'])
            clone = subprocess.run(
                ['git', 'clone', '--depth', '1', auth_url, workdir],
                capture_output=True, text=True, timeout=120,
            )
            if clone.returncode != 0:
                _logger.warning('odooclaw: repo clone failed: %s', clone.stderr.strip())
                return ''
            branch = settings['branch']
            subprocess.run(
                ['git', '-C', workdir, 'checkout', '-B', branch],
                capture_output=True, text=True, timeout=60,
            )
            target = os.path.join(workdir, module_name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(module_path, target)
            name, email = self._parse_author(settings['author'])
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
            subprocess.run(
                ['git', '-C', workdir, 'add', module_name],
                capture_output=True, text=True, timeout=60, env=env,
            )
            commit = subprocess.run(
                [
                    'git', '-C', workdir,
                    '-c', 'user.name=%s' % name,
                    '-c', 'user.email=%s' % email,
                    'commit', '-m', '%s %s' % (self.reference or 'EVO', module_name),
                ],
                capture_output=True, text=True, timeout=60, env=env,
            )
            if commit.returncode != 0:
                _logger.warning(
                    'odooclaw: repo commit failed: %s', commit.stderr.strip() or commit.stdout.strip()
                )
                return ''
            push = subprocess.run(
                ['git', '-C', workdir, 'push', 'origin', branch],
                capture_output=True, text=True, timeout=180, env=env,
            )
            if push.returncode != 0:
                _logger.warning('odooclaw: repo push failed: %s', push.stderr.strip())
                return ''
            head = subprocess.run(
                ['git', '-C', workdir, 'rev-parse', 'HEAD'],
                capture_output=True, text=True, timeout=30, env=env,
            )
            sha = head.stdout.strip()
            self.snapshot = json.dumps(
                dict(json.loads(self.snapshot or '{}'), repo_commit=sha), default=str
            )
            return sha
        except Exception:  # noqa: BLE001 - a push must never break an apply
            _logger.warning('odooclaw: repo push crashed for %s', module_name, exc_info=True)
            return ''
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _parse_author(author):
        match = re.match(r'\s*(.*?)\s*<([^>]+)>\s*$', author or '')
        if match:
            return match.group(1) or 'OdooClaw', match.group(2)
        return author or 'OdooClaw', 'odooclaw@example.com'

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
        if self.kind == 'module':
            return self._apply_module(payload)
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
        if payload.get('ttype') == 'selection':
            for value, label in payload.get('selection') or []:
                self.env['ir.model.fields.selection'].sudo().create({
                    'field_id': field.id,
                    'value': str(value),
                    'name': str(label),
                })
        view = self._place_field_in_form(payload['model'], field, payload.get('insert_after'))
        return {
            'kind': 'field',
            'field_id': field.id,
            'view_id': view.id if view else False,
            'existed': False,
        }

    def _place_field_in_form(self, model_name, field, anchor=None):
        """Insert the new field into the model's default form view.

        A manual field that is not placed anywhere is invisible in the UI, so
        the field change also creates an inherited view. The anchor is the
        requested insert_after when it exists on the model, otherwise the first
        of partner_id/name/user_id present; the insertion goes right after it.
        """
        view = self.env['ir.ui.view'].sudo().search([
            ('model', '=', model_name),
            ('type', '=', 'form'),
            ('inherit_id', '=', False),
        ], order='priority, id', limit=1)
        if not view:
            return None
        model_fields = self.env[model_name]._fields
        chosen = anchor if anchor and anchor in model_fields else None
        if not chosen:
            for candidate in ('partner_id', 'name', 'user_id'):
                if candidate in model_fields:
                    chosen = candidate
                    break
        if not chosen:
            return None
        arch = (
            '<data><field name="%s" position="after">'
            '<field name="%s"/></field></data>'
        ) % (chosen, field.name)
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
        # A field change auto-places its field after a default anchor. When an
        # explicit view change places the same field, drop that auto view so
        # the field is not rendered twice.
        for field_name in re.findall(r'<field\s+name="(x_[^"]+)"', payload['arch']):
            auto = self.env['ir.ui.view'].sudo().search([
                ('name', '=', 'odooclaw.%s.%s' % (payload['model'], field_name)),
            ], limit=1)
            if auto:
                auto.unlink()
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

    def _module_paths(self):
        """Find the writable private addons dir and the auto addons dir that
        holds the symlinks. Doodba links <auto>/<module> to
        ../../custom/src/private/<module>; other deployments put the private
        dir directly in the addons path."""
        import odoo

        paths = list(odoo.addons.__path__)
        private = next(
            (p for p in paths if os.path.basename(os.path.normpath(p)) == 'private'),
            None,
        )
        auto_dir = next(
            (
                p
                for p in paths
                if os.path.basename(os.path.normpath(p)) == 'addons' and os.access(p, os.W_OK)
            ),
            None,
        )
        if not private:
            for addons_dir in paths:
                try:
                    entries = os.listdir(addons_dir)
                except OSError:
                    continue
                for entry in entries:
                    link = os.path.join(addons_dir, entry)
                    if not os.path.islink(link):
                        continue
                    target = os.path.realpath(link)
                    parent = os.path.dirname(target)
                    if os.path.basename(parent) == 'private':
                        return parent, addons_dir
        return private, auto_dir or private

    def _apply_module(self, payload):
        module_name = payload['module']
        files = payload['files']
        private, auto_dir = self._module_paths()
        if not private:
            raise UserError(_('No writable private addons path is configured.'))
        path = os.path.join(private, module_name)
        existed = os.path.isdir(path)
        os.makedirs(path, exist_ok=True)
        for rel, content in files.items():
            full = os.path.join(path, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w', encoding='utf-8') as handle:
                handle.write(content)
        link = os.path.join(auto_dir, module_name)
        if not os.path.lexists(link):
            os.symlink(os.path.relpath(path, auto_dir), link)
        self.env['ir.module.module'].update_list()
        module = self.env['ir.module.module'].search([('name', '=', module_name)], limit=1)
        if not module:
            raise UserError(_('Module %s was not found after update_list.', module_name))
        if module.state == 'installed':
            module.button_immediate_upgrade()
        else:
            module.button_immediate_install()
        self.env.registry.clear_cache()
        if module.state != 'installed':
            raise UserError(
                _('Module %(name)s did not reach the installed state (%(state)s).', name=module_name, state=module.state)
            )
        return {
            'kind': 'module',
            'module': module_name,
            'path': path,
            'existed': existed,
            'state': module.state,
        }

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
        if kind == 'module':
            module = self.env['ir.module.module'].sudo().search([
                ('name', '=', snapshot.get('module') or ''),
            ], limit=1)
            if module and module.state == 'installed':
                module.button_immediate_uninstall()
            path = snapshot.get('path')
            if path and os.path.isdir(path):
                shutil.rmtree(path)
            self.env['ir.module.module'].update_list()
            self.env.registry.clear_cache()
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
