# moneroodoo — Monero payments for Odoo

Self-hosted Monero (XMR) payments for Odoo website checkout and Point of Sale, talking to
your own `monerod` and `monero-wallet-rpc`. No third-party processor, no custodian.

## Layout

```
moneroodoo/
├── addons/
│   ├── 18.0/  payment_monero_rpc/   payment_monero_rpc-18.0.zip
│   ├── 19.0/  payment_monero_rpc/   payment_monero_rpc-19.0.zip
│   └── 20.0/  payment_monero_rpc/   payment_monero_rpc-20.0.zip
├── legacy/                          archived pre-15 modules (monero-rpc-odoo, -pos)
├── README.md                        this file
├── MIGRATION_NOTES.md               what changed per version, with evidence
├── TEST_RESULTS.md                  real install + test results, per version
├── monero_code_review_final.md      runtime security review: 19 findings, all fixed
├── monero_code_review_three_pass.md original static audit (164 issues), kept for history
└── moneroodoo-article.html          technical walkthrough of the module
```

Each version folder holds an independently installable module and a ready-to-upload zip.
Use exactly one series per Odoo install (the module name is the same in all three):

    addons_path = /opt/odoo/moneroodoo/addons/19.0,...

Or upload the zip for your series through Apps → Import Module / your deployment tooling.

## Status

| Odoo | Module | Tests on real Odoo (Odoo's own runner) | Server side | POS frontend overlay |
|---|---|---|---|---|
| 18.0 | 18.0.0.0.3 | 0 failed of 65 (38 shipped + 27 adversarial probes) | full | original (unchanged) |
| 19.0 | 19.0.1.0.0 | 0 failed of 41 (39 shipped + 2 database-constraint tests) | full | import paths updated; `_isOrderValid` hook needs retargeting (untested) |
| 20.0 | 20.0.1.0.0 | 0 failed of 43 (39 shipped + 2 constraint tests + 2 tests from Odoo's own `web` module) | full | not bundled (core removed `OnlinePaymentPopup`) |

Details, evidence and the list of bugs fixed in every series: `MIGRATION_NOTES.md`.
What was and wasn't exercised: `TEST_RESULTS.md`.

## Security review

The module has had two reviews, both kept in the repository:

* **Static, three passes** (`monero_code_review_three_pass.md`): 164 issues found and fixed by
  reading the Odoo 18 code, without running it.
* **Runtime** (`monero_code_review_final.md`): installing the module on real Odoo and PostgreSQL and
  driving it over real HTTP found 19 more defects the static review had missed. All 19 are fixed on
  every series. Among them: guest checkout could not complete a payment; the payment page had no
  access-token check; `payment_id` was a small sequential number; a single RPC timeout could
  permanently fail a valid payment; and, on 19.0 and 20.0, the database constraints were never
  created because Odoo 19 ignores `_sql_constraints`.

Known gaps:

* The 27 adversarial probes exist on 18.0 only. 19.0 and 20.0 run their shipped suites plus a
  test that the database constraints exist.
* No browser or POS session has been run, so the POS frontend and website checkout JavaScript are
  unverified on every series.
* Wallet and daemon calls are mocked in the tests; nothing has talked to a real `monerod` or
  `monero-wallet-rpc`. Try stagenet before mainnet.

## Requirements

Python packages `monero`, `qrcode`, `requests`; a reachable `monerod` and
`monero-wallet-rpc`; core `pos_online_payment` for POS.

## Testing

From an Odoo checkout of the matching version, with `addons/<version>` on the addons path:

    odoo-bin -d test_db -i payment_monero_rpc --test-enable --test-tags /payment_monero_rpc \
             --without-demo=all --stop-after-init
