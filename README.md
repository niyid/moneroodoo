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
├── MIGRATION_NOTES.md               what changed per version, with evidence
├── TEST_RESULTS.md                  real install + test results
└── README.md
```

Each version folder holds an independently installable module and a ready-to-upload zip.
Use exactly one series per Odoo install (the module name is the same in all three):

    addons_path = /opt/odoo/moneroodoo/addons/19.0,...

Or upload the zip for your series through Apps → Import Module / your deployment tooling.

## Status

| Odoo | Module | Installed & tested on real Odoo | Server side | POS frontend overlay |
|---|---|---|---|---|
| 18.0 | 18.0.0.0.3 | yes, 38 tests pass | full | original (unchanged) |
| 19.0 | 19.0.1.0.0 | yes, 39 tests pass | full | import paths updated; `_isOrderValid` hook needs retargeting (untested) |
| 20.0 | 20.0.1.0.0 | yes, 41 tests pass | full | not bundled (core removed `OnlinePaymentPopup`) |

Details, evidence and the list of bugs fixed in every branch: `MIGRATION_NOTES.md`.
What was and wasn't exercised: `TEST_RESULTS.md`.

## Requirements

Python packages `monero`, `qrcode`, `requests`; a reachable `monerod` and
`monero-wallet-rpc`; core `pos_online_payment` for POS.

## Testing

    odoo-bin -d test_db -i payment_monero_rpc --test-enable --test-tags /payment_monero_rpc --stop-after-init
