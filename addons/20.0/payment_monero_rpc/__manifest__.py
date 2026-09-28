# Odoo 20.0 branch: installed and tested against the real 20.0 source. The POS overlay
# is not bundled (see ../../MIGRATION_NOTES.md, "POS frontend").
{
    "name": "payment_monero_rpc",
    "summary": "This module enables private and secure Monero (XMR) payments across your Odoo website and point of sale (POS) systems. It features full RPC integration for seamless interaction with a Monero daemon, real-time transaction tracking, and automated processing of payments. Ideal for merchants seeking privacy-focused crypto payments, the app supports both online and in-store transactions with customizable templates, frontend components, and POS interface enhancements.",
    "author": "Monero Integrations",
    "website": "https://monerointegrations.com/",
    "category": "Payment Providers",
    "version": "20.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "account",
        "website_sale",
        "website_payment",
        "website",
        "payment",
        "base_setup",
        "web",
        "point_of_sale",
        "pos_online_payment"
    ],
    "external_dependencies": {
        "python": [
            "monero",
            "requests",
            "qrcode"
        ],
        "npm": []
    },
    "data": [
        "security/security.xml",
        "security/ir.access.csv",
        "data/mail_templates.xml",
        "data/monero_payment_data.xml",
        "views/monero_daemon_views.xml",
        "views/monero_payment_views.xml",
        "views/monero_payment_templates.xml",
        "views/monero_payment_template_email.xml",
        "views/monero_payment_template_invoice.xml",
        "views/monero_payment_template_proof.xml",
        "views/monero_payment_kanban.xml",
        "views/pos_payment_views.xml",
        "views/menus.xml",
        "data/monero_cron.xml"
    ],
    "assets": {
        "web.assets_frontend": [
            "payment_monero_rpc/static/src/css/monero.css",
            "payment_monero_rpc/static/src/css/monero_pos.css",
            "payment_monero_rpc/static/src/css/payment_page.css",                        
            "payment_monero_rpc/static/src/js/payment_form_monero.js",
            "payment_monero_rpc/static/src/js/payment_monero_checkout.js"
        ],
        "web.assets_backend": [
            "payment_monero_rpc/static/src/xml/monero_payment_template_page.xml"
        ],
        # POS overlay intentionally not bundled on 20.0: core removed OnlinePaymentPopup and moved
        # online validation into OrderPaymentValidation. See MIGRATION_NOTES.md ("POS frontend").
        # "point_of_sale._assets_pos": [ ...static/src/app/*monero* ... ],
    },
    "demo": [
        "demo/demo.xml"
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "post_init_setup",
    "uninstall_hook": "uninstall_hook"
}
