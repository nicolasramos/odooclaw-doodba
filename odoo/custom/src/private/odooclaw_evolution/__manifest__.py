{
    'name': 'OdooClaw Evolution',
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'summary': 'Ledger and hot metadata changes for Odoo',
    'description': """
OdooClaw Evolution
==================

Ledger of changes and hot application of N0/N1 changes:
fields, views, server actions and menus, with logical snapshot and rollback.
""",
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/evolution_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'views/change_views.xml',
        'views/forge_views.xml',
        'views/overlay_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odooclaw_evolution/static/src/js/odooclaw_systray.js',
            'odooclaw_evolution/static/src/xml/odooclaw_systray.xml',
            'odooclaw_evolution/static/src/scss/odooclaw_systray.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
