# -*- coding: utf-8 -*-
{
    'name': 'Commissioned Purchase/Inventory Management Modifications',
    'category': 'Purchase',
    'author': 'GFP Solutions',
    'summary': 'Custom',
    'version': '1.0',
    'description': """
Purchase/Inventory Management modifications commissioned by Speedhut. Check Flow for modification details.

THIS MODULE IS PROVIDED AS IS - INSTALLATION AT USERS' OWN RISK - AUTHOR OF MODULE DOES NOT CLAIM ANY
RESPONSIBILITY FOR ANY BEHAVIOR ONCE INSTALLED.
        """,

    'depends':['base','account_accountant','purchase','stock'],
    'data':[
            'records/records.xml',
            'views/stock_picking_return_views.xml',
            'views/stock_picking_fix_views.xml',
            'views/purchase_views.xml'
            ],
    'installable': True,
}
