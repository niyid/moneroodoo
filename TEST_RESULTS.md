# Test results — `payment_monero_rpc`

Every result below comes from installing the module on a **real Odoo + PostgreSQL** instance
and running its tests there. Only the Monero wallet/daemon RPC transport is mocked; nothing
talked to a real `monerod` or `monero-wallet-rpc`.

## Summary

| Odoo | Result | Composition |
|------|--------|-------------|
| 18.0 | **65 / 65 pass** | 38 shipped tests + 27 adversarial probes (`tests/test_zz_audit_probes.py`) |
| 19.0 | **39 / 39 pass** | shipped tests only |
| 20.0 | **39 tests, all pass** (runner reported 41; see note) | shipped tests only |

Counts were re-checked by reading the test sources: 18.0 has 65 test methods (38 shipped +
27 probes); 19.0 and 20.0 each have 39 (26 in `test_payment_provider.py`, 12 in
`test_controllers.py`, 1 in `test_sales_order.py`). The one test 19.0/20.0 have beyond the 18.0
shipped 38 is `test_json_routes_use_jsonrpc_type` (class `TestMoneroRoutesTargetJsonRpc`).
An earlier Odoo run on 20.0 reported 41 passing; the two extra are not accounted for by any
test in the module (no inherited test classes, no tests outside `tests/`), so 39 is the
verified number and 41 the runner's unreconciled total.

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

## Not covered

* **Adversarial probes on 19.0 and 20.0.** They were not ported. On those versions the fixes are
  confirmed not to break the shipped suites, but guest checkout end-to-end, idempotency and ACL
  scoping were only directly exercised on 18.0.
* **POS frontend and website checkout JS.** No browser or POS session was run on any version.
* **Live Monero RPC.** Wallet and daemon calls are mocked. Exchange-rate fetches were blocked by
  the test sandbox network.

## Reproducing

From an Odoo checkout of the matching version, with `addons/<version>` on the addons path:

```bash
odoo -d test_monero -i payment_monero_rpc --test-tags /payment_monero_rpc --stop-after-init
```
