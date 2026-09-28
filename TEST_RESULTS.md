# Test results

Environment: Ubuntu 24.04, Python 3.12, PostgreSQL 16, sparse checkouts of the real
`18.0`, `19.0`, `20.0` branches of `odoo/odoo` (base, web, mail, payment, portal, sale,
website, website_sale, point_of_sale, pos_online_payment and their dependencies).

Command (fresh database each time):

    odoo-bin -d <db> -i payment_monero_rpc --test-enable --test-tags /payment_monero_rpc --stop-after-init --without-demo=all

| Odoo | Module version | Install | Result |
|---|---|---|---|
| 18.0 | 18.0.0.0.3 | OK | 0 failed, 0 errors of 38 tests |
| 19.0 | 19.0.1.0.0 | OK | 0 failed, 0 errors of 39 tests |
| 20.0 | 20.0.1.0.0 | OK | 0 failed, 0 errors of 41 tests |

Not covered: browser/POS sessions, real monerod/wallet RPC, external exchange-rate APIs.
See `MIGRATION_NOTES.md`.
