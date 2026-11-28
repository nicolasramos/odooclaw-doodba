{
    'name': 'OdooClaw Evolution',
    'version': '18.0.1.2.0',
    'category': 'Technical',
    'summary': 'Ledger and hot metadata changes for Odoo',
    'description': """
OdooClaw Evolution
==================

Ledger of changes and hot application of N0/N1 changes:
fields, views, server actions and menus, with logical snapshot and rollback.
""",
    'depends': ['base', 'web', 'mail', 'sale_management'],
    'data': [
        'security/evolution_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'views/change_views.xml',
        'views/forge_views.xml',
        'views/overlay_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
