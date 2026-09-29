# Test results — `payment_monero_rpc`

Every result below comes from a **fresh install of the module on a real Odoo + PostgreSQL**
instance, running its tests there with `--test-enable`. Only the Monero wallet/daemon RPC
transport is mocked; nothing talked to a real `monerod` or `monero-wallet-rpc`.

## Summary

| Odoo | Result | Composition |
|------|--------|-------------|
| 18.0 | **0 failed of 65** | 38 shipped tests + 27 adversarial probes (`tests/test_zz_audit_probes.py`) |
| 19.0 | **0 failed of 41** | 39 shipped tests + 2 DB-constraint tests (`tests/test_db_constraints.py`) |
| 20.0 | **0 failed of 43** | 39 shipped tests + 2 DB-constraint tests + 2 Odoo `web` JS suite tests the runner also executes |

The "of N" figures are the totals printed by Odoo's own runner
(`odoo.tests.result: 0 failed, 0 error(s) of N tests`).

### Where the numbers come from

* Test methods in `tests/`: 65 on 18.0, 39 on 19.0 and 20.0 before the constraint tests were
  added (26 in `test_payment_provider.py`, 12 in `test_controllers.py`, 1 in
  `test_sales_order.py`; 19.0/20.0 have one more shipped test than 18.0,
  `test_json_routes_use_jsonrpc_type`), and 41 on 19.0 / 41 on 20.0 with the two
  `test_db_constraints.py` tests.
* On 20.0 the runner reports 2 more than the module contains, because it also runs
  `WebSuite.test_unit_desktop` and `MobileWebSuite.test_unit_mobile` from Odoo's `web` module
  in the same post-install pass. An earlier 20.0 total of "41" was those 2 plus the 39 module
  tests; it was not a miscount.

### Environment

Python 3.12.3, PostgreSQL 16.15, `--without-demo=all`, Odoo checked out from GitHub at
`18.0` @ `d6f4e6d6db`, `19.0` @ `cfb5943f7e`, `20.0` @ `faacf262cd`.

## A defect the re-run found: constraints not created on 19.0 and 20.0

`_sql_constraints` is no longer supported from Odoo 19. Odoo only logs
`Model attribute '_sql_constraints' is no longer supported, please define models.Constraint`
and creates **nothing**. The module still declared its constraints that way, so on 19.0 and
20.0 the database had only primary keys: no `UNIQUE(payment_id)`, no `CHECK(amount > 0)`, and
not the `UNIQUE(txid, payment_id)` added for review finding 3. The existing tests all passed
regardless, because none of them asserted that a constraint exists.

Fixed on 19.0 and 20.0 by declaring them as `models.Constraint` attributes, and guarded by
`tests/test_db_constraints.py`, which reads `pg_constraint` and fails if any is missing. 18.0
still honors `_sql_constraints`; its database was checked and has all three constraints.

| Constraint (table) | 18.0 | 19.0 before | 20.0 before | 19.0 / 20.0 now |
|---|---|---|---|---|
| `UNIQUE(payment_id)` (`monero_payment`) | present | missing | missing | present |
| `CHECK(amount > 0)` (`monero_payment`) | present | missing | missing | present |
| `UNIQUE(txid, payment_id)` (`monero_transaction`) | present | missing | missing | present |

## What the adversarial probes cover (18.0 only)

The 27 probes each assert the *correct* behavior for one review finding, so they fail on the
unfixed code and pass on the fixed code (see `monero_code_review_final.md`).

| Group | Probes | Area |
|-------|--------|------|
| `s` | s01–s08 | Payment state machine: exact payment confirms, overpayment stays `overpaid` by design, transient RPC errors do not fail a payment, expired guard blocks late funds by design, one tx settling two payments, no regression after confirmation, confirmations without a `monero.daemon` row, subaddress filter branch |
| `c` | c01–c07 | Configuration: `https://` RPC URL stays https, address network validation, wrong-network wallet refused, confirmation threshold >= 1, every cron targets an existing method, no duplicate crons, shipped provider disabled |
| `a` | a01–a02 | Access control: Monero Admin cannot write other providers, Monero Manager POS-order grant is scoped |
| `h` | h01–h10 | HTTP routes: guest can start a payment, payment page requires a token, `payment_id` is an unguessable secret, no internal host leakage, anonymous poll cannot permanently fail a payment, process route is idempotent, cancelled order gets no payment, QR blob not stored in session, token-gated QR is `private` cache, `/verify` closed to portal users |

## Shipped tests changed by the security pass

Two shipped tests had encoded the old, buggy behavior as expected, and were corrected on all
three versions:

* `test_create_monero_from_fiat_payment_subaddress` asserted `payment_id == '42'` (the small
  sequential subaddress index). It now asserts `subaddress_index == 42` and that `payment_id`
  is a 64-hex-character token, never the small index.
* `test_payment_page_reads_db_on_empty_session` called `payment_page` without a token. It now
  passes one, matching the corrected access check.

## Known warnings (not failures)

* Odoo 20.0: `Two fields (payment_provider_id, payment_provider) of pos.payment.method() have
  the same label: Payment Provider` (module and `point_of_sale` both define a field with that label).
* Expected error logs from tests that deliberately simulate wallet failures
  (`test_fetch_wallet_addresses_failure`, `test_get_wallet_client_failure`) and from the
  blocked exchange-rate fetches in the sandbox.

## Not covered

* **Adversarial probes on 19.0 and 20.0.** They were not ported. On those versions the fixes are
  confirmed not to break the shipped suites, but guest checkout end-to-end, idempotency and ACL
  scoping were only directly exercised on 18.0.
* **POS frontend and website checkout JS.** No browser or POS session was run on any version.
* **Live Monero RPC.** Wallet and daemon calls are mocked.

## Reproducing

From an Odoo checkout of the matching version, with `addons/<version>` on the addons path:

```bash
odoo -d test_monero -i payment_monero_rpc --test-enable --test-tags /payment_monero_rpc \
     --without-demo=all --stop-after-init
```
