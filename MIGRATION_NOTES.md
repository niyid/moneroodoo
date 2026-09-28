# Migration notes — `payment_monero_rpc` 18.0 → 19.0 → 20.0

Everything below was checked against the **real `odoo/odoo` source** of the `18.0`, `19.0`
and `20.0` branches (each reports `version_info = (N, 0, 0, FINAL, 0)` in `odoo/release.py`),
and every branch was **installed and its test suite run on a live Odoo + PostgreSQL 16
instance** (see `TEST_RESULTS.md`).

## Bugs found by really installing the module (all branches)

These are defects in the original 18.0 code, not version differences. Static checks could
not see them; the first real install did.

1. **Hooks were never found.** `__init__.py` only did `from . import hooks`, but Odoo calls
   `getattr(<package>, "post_init_setup")`. Fixed with `from .hooks import post_init_setup, uninstall_hook`.
2. **Hook signature.** `odoo/modules/loading.py` calls hooks as `hook(env)` in 18.0, 19.0 *and*
   20.0. The original `(cr, registry)` signature raises `TypeError` on all three.
3. **Dead `super()` call.** `payment.provider._get_compatible_payment_methods` called a parent
   method that only exists on `payment.method`. It now falls back safely.
4. **Confirmations read before they were saved.** `check_payment_status` computed the
   `confirmed` state *before* upserting the transactions, so a payment could not become
   `confirmed` on the poll that first saw enough confirmations. The upsert now runs first.
5. **`payment_page` route** had no explicit `type`; it is now `type='http'`.
6. **Tests** were not runnable as written: `mock.patch` on the unbound `request` proxy,
   `patch.object` on read-only record instances, placeholder wallet addresses failing
   validation, a lazily created `sale.order.access_token`, tuples passed to Odoo's
   `assertRaises`, timezone-aware values written to naive `Datetime` fields, and a flow test
   that never seeded the daemon height confirmations are computed from.

## 19.0

| Change | Evidence |
|---|---|
| `res.groups.category_id` removed → `res.groups.privilege` + `privilege_id` | 18.0 defines `category_id` in `res_users.py`; 19.0 `res_groups.py` defines `privilege_id` |
| `@route(type='json')` → `type='jsonrpc'` | 19.0 `http.py` warns "Since 19.0, @route(type='json') is a deprecated alias" |
| POS JS import paths moved (`pos_hook`, `make_awaitable_dialog`, `OnlinePaymentPopup`) | new paths exist in the 19.0 tree |
| `_()` needs `self.env` of the calling frame | test-only stub for directly instantiated controllers |

`security/monero_groups.xml` (the old, never-wired workaround that dropped the category and
record rules) is removed from 19.0 and 20.0.

## 20.0 (everything in 19.0, plus)

| Change | Evidence / fix |
|---|---|
| `ir.rule` and `ir.model.access` merged into **`ir.access`** | `ir_rule.py` gone, `ir_access.py` added; Odoo ships `odoo/upgrade_code/19.4-00-ir-access.py`. Security is now `security/ir.access.csv` (`id,name,model_id,group_id/id,operation,domain`) |
| `ir.config_parameter.get_param/set_param` removed | typed `get_str/get_bool/get_int/get_float` and `set_*`; module uses `get_str/set_str` |
| `Binary` fields reject `bytes` | wrap in `BinaryBytes(...)`; reads return `BinaryValue` (`.to_base64()`, `bytes(...)`); attachments use `raw` |
| `payment.provider.state` → `active` | data file |
| `payment.method` is per provider (`provider_id`, unique with `code`) | data file reordered |
| `pos.payment.method.use_payment_terminal` → `payment_provider`; `_get_payment_terminal_selection` → `_get_terminal_provider_selection` | `pos_payment.py` |
| `t-esc` → `t-out`; provider form xpaths changed | kanban and form views |
| `odoo/http.py` became an `odoo/http/` package | `from odoo.http import request, route` still works |

## NOT verified

* **POS frontend.** No browser/POS session was run. On 19.0 core moved online-payment
  validation from `PaymentScreen._isOrderValid` to `OrderPaymentValidation.isOrderValid`, so
  this module's `_isOrderValid` override is **inert on 19.0** and must be retargeted. On
  **20.0** `OnlinePaymentPopup` no longer exists and the overlay is **not bundled**.
  Server-side POS models install and pass tests on both.
* **Live Monero RPC.** Wallet/daemon calls are mocked; nothing talked to a real
  `monerod`/`monero-wallet-rpc`. Exchange-rate fetches were blocked by the sandbox network.
* **Website checkout in a browser.** Templates render at install; the JS was not exercised.
