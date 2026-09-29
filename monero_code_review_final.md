# payment_monero_rpc — Code Review (Odoo 18.0, ported to 19.0/20.0)

**This is the third version of this document.** The first was a static, read-only review
(164 issues across three passes, no code executed). The second replaced it after actually
installing the module on a real Odoo 18.0 + PostgreSQL instance and running it over real HTTP,
which found 15 confirmed defects the static review had missed entirely — including several
that make the module non-functional for real customers, not just imperfect. This version
replaces that one: every one of those 15 findings has been fixed in the module source, and
4 more were found and fixed along the way, discovered only because fixing the first batch
exposed code paths that had never actually run before. All 19 fixes are re-verified against a
real Odoo 18.0 install; the same fixes have been ported to 19.0 and 20.0 and verified against
each version's own shipped test suite on a real install of that version.

**Method, same as the previous pass:** real Odoo (18.0, 19.0, and 20.0 in turn), real
PostgreSQL, real HTTP requests. Only the Monero wallet RPC transport itself was mocked.
Test code lives in `tests/test_zz_audit_probes.py` (18.0 only — see "Scope of this pass" below).

**Result on 18.0:** 65 of 65 tests pass — the original 38 shipped tests (2 of which had to be
updated because they asserted the old, buggy behavior as correct — see Finding 5) plus 27
adversarial probes covering every finding below.

**Result on 19.0 / 20.0:** the module's own shipped suite passes on each — 39/39 on 19.0,
41/41 on 20.0 — confirming the ported fixes don't break anything version-specific. See
"Scope of this pass" for exactly what was and wasn't re-verified on these two.

---

## Findings, all fixed

### 1. Guest checkout raised AccessError — the module could not take a Monero payment at all
**Was:** `_process_monero_payment` (route `/shop/payment/monero/process/<order_id>`, `auth='public'`)
read `payment.provider` without `.sudo()`. Core Odoo restricts read access on that model to
`base.group_system`; an anonymous or portal shopper has no read access to it at all, so the
route raised `AccessError` before a payment record ever existed. The same missing `.sudo()`
also existed in the POS payment-creation path (`models/pos_payment.py`) and three internal
lookups in `models/payment_provider.py` / `models/monero_daemon.py` — same bug, several places.

**Fix:** added `.sudo()` to all six lookups.

**Fixed but not by that alone — a second bug was hiding behind the first:** once the
`AccessError` was gone, the request got further and crashed with `TypeError: Object of type
bytes is not JSON serializable`. `payment.image_qr` is a Binary field that reads back as raw
`bytes`; it was being placed directly into `request.session[...]`, which Odoo JSON-serializes
on every write. This had likely never actually run in production either, for the same reason
the AccessError masked it in testing. **Fix:** the QR image is no longer cached in the session
at all (the code's own comment already said `payment_page` reads it straight from the DB, so
caching it there was never necessary — this also independently resolves Finding 9 below); the
JSON response returned to the caller still includes it, now correctly base64-encoded to a string.

**Verified by:** `test_h01_guest_can_start_payment` now passes — an anonymous request gets
`{'success': True, ...}` with a real payment attached, on a real HTTP request against a real
database.

### 2. Confirmation count came from an unrelated cached value, not from the wallet's own report
**Was:** `monero.transaction.confirmations` was computed only from `monero.daemon.current_height
- block_height`. It never read what the wallet's own `incoming()` call reported for that
transfer. With the `monero.daemon` table empty — true of every fresh install until its cron's
first successful run — a payment with any number of real confirmations computed `confirmations
= 0` and sat at `paid_unconfirmed` forever.

**Fix:** added a stored `wallet_reported_confirmations` field on `monero.transaction`, populated
from the wallet's own reported value at the same point the old code already read (and
discarded) it. `_compute_confirmations` now takes `max(daemon-derived, wallet_reported_confirmations)`
— the daemon-height number is still used when it's ahead, but a payment is no longer hostage to
a second, independently-timed cache being populated yet.

**Verified by:** `test_s01_baseline_exact_payment_confirms` and
`test_s08_confirmations_depend_on_a_separate_uncoupled_daemon_row` — the latter explicitly
deletes every `monero.daemon` row and confirms a payment with 10,000 real confirmations still
reaches `state == 'confirmed'`.

### 3. A shared transaction hash only ever attached to the first payment it satisfied
**Was:** incoming transactions were deduplicated globally by `txid` alone, with
`monero.transaction.payment_id` as a single-owner Many2one and a `UNIQUE(txid)` database
constraint enforcing it. If one on-chain transaction happened to satisfy two different pending
payments, the second payment's `amount_received` still got credited, but it never got its own
`transaction` row — so its `confirmations` (computed from `transaction_ids`) stayed 0 forever.

**Fix:** the upsert lookup and the database constraint are both now scoped to
`(txid, payment_id)` rather than `txid` alone, so the same transaction can be recorded once per
payment it satisfies.

**Verified by:** `test_s05_one_tx_paying_two_payments_should_settle_both` — both payments now
reach `confirmed`.

### 4. A confirmed payment could regress to failed after the order was already confirmed
**Was:** `_payment_confirmed` wrote `state='confirmed'` and confirmed the sale order first, then
sent a confirmation email; any exception in that later, non-critical step was caught, logged,
and re-raised. That exception propagated into `check_payment_status`'s own exception handler,
which called `_handle_rpc_error()` — overwriting the record straight back to `state='failed'`,
while the order stayed confirmed (`state == 'sale'`). A transient mail-server hiccup, unrelated
to the money itself, could leave a fulfilled order permanently paired with a payment record that
claims to have failed.

**Fix:** the confirmation email send and the chatter post are now each in their own try/except
that logs on failure but does not re-raise, so nothing after the critical `state='confirmed'`
write can undo it.

**Verified by:** `test_s06_failure_after_confirmation_must_not_regress_state` — a forced
exception in the mail-send step no longer changes the payment's state; it stays `confirmed`.

### 5. `payment_id` — the public lookup key — was a small, guessable sequential index
**This was not in the previous version of this review, and it directly contradicts something
that review concluded.** That version treated the lack of a token check on `/status` and
`/verify` as acceptable, reasoning that `payment_id` was itself a `secrets.token_hex(32)` value
functioning as a bearer credential. That's true in *integrated-address mode*, but
`use_subaddresses` defaults to `True` ("recommended" per its own help text), and in that —
the actual default — mode, `_create_monero_from_fiat_payment` set `payment_id` to
`str(subaddress[1])`: the subaddress's own minor index, i.e. `"1"`, `"2"`, `"3"`, ... Every
normal checkout got a trivially enumerable lookup key on two routes that check no other
credential.

This was found while re-verifying the earlier review's own "not a defect" conclusion for that
exact area (`test_h03`), which is why re-running fixes with real tests matters: a conclusion
that looked sound against the integrated-address code path was wrong for the code path real
checkouts actually use.

**Fix:** the subaddress's minor index now goes into the already-existing (but previously never
populated) `subaddress_index` field, and `payment_id` is left for `monero.payment.create()`'s
own `secrets.token_hex(32)` generator to fill in, exactly as it already does for every other
caller of that model. A shipped test (`test_create_monero_from_fiat_payment_subaddress`) had
literally asserted the old value (`payment.payment_id == '42'`) as correct; it's been updated to
assert the corrected behavior instead (`subaddress_index == 42`, `payment_id` a real 64-hex-char
token, and never equal to the small index).

**Verified by:** `test_h03_status_lookup_key_is_itself_an_unguessable_secret` now passes for the
actual default code path.

### 6. The customer payment page had no access-token check at all
**Was:** `payment_page` (`/shop/payment/monero/page/<int:payment_id>`) browsed the payment by its
sequential database id and rendered it with no token check whatsoever — unlike the sibling
`/qr`, `/invoice`, and `/proof` routes on the same controller, which all check the order's
`access_token` via `hmac.compare_digest` first.

**Fix:** added the same `access_token` check the other three routes already use.

**Verified by:** `test_h02_payment_page_must_require_a_token` — a tokenless request now gets a
clean `404` instead of the payment's address and details.

### 7. The process route was not idempotent, and didn't check for a cancelled order
**Neither of these was in the previous review — both were found only once the guest-checkout
AccessError from Finding 1 was fixed and the route could actually run to completion.**

- A retry, double-click, or slow-response resend created a brand-new `monero.payment` record
  and burned a brand-new subaddress every single time, leaving several live, independent
  payment requests outstanding for the same order.
- Nothing checked `order.state` before creating a payment, so a cancelled order could still get
  one.

**Fix:** the route now reuses an existing payment that's still in an active state
(`pending`/`partial`/`paid_unconfirmed`/`overpaid`) for the same order instead of creating
another one, and rejects outright if the order is cancelled.

**Verified by:** `test_h06_process_route_must_be_idempotent` (3 calls now produce exactly 1
payment record) and `test_h07_cancelled_order_must_not_get_a_payment`.

### 8. Any transient RPC error permanently failed the payment
**Also not in the previous review — found the same way as Finding 7.** `_handle_rpc_error`
unconditionally set `state='failed'` on *any* exception, including a single connection timeout
during a routine anonymous status poll, for a payment that had done nothing wrong.

**Fix:** the active/recoverable states (`pending`, `partial`, `paid_unconfirmed`, `overpaid`)
are now left untouched by a bare RPC error; only a payment already outside those states gets
moved to `failed`. The error message is still recorded either way, for troubleshooting.

**Verified by:** `test_h05_anonymous_poll_must_not_permanently_fail_a_payment`.

### 9. The QR blob was cached in the session (see Finding 1 — fixed as part of that same change)

### 10. The shipped provider was enabled, published, and live, with credentials that were public
**Was:** the data file created the provider with `state="enabled"` (Odoo 18/19) /
`active="True"` (Odoo 20, which replaced `state` with a plain active flag), `is_published=True`,
and a hardcoded `rpc_password`, `wallet_password`, and a wallet directory that was literally the
original developer's home path (`/home/niyid/monero-x86_64-linux-gnu-v0.18.3.4/wallets`).

**Fix:** ships disabled/inactive, unpublished, with all four fields blanked.

**Verified by:** `test_c07_shipped_provider_must_not_be_enabled_out_of_the_box`.

### 11. TLS was silently downgraded to plaintext
**Was:** `_get_wallet_client` never passed `protocol=` to `JSONRPCWallet`, whose default is
`'http'`. An `https://` `rpc_url` had no effect — the wallet RPC username and password were
always sent in plaintext.

**Fix:** the URL's scheme is now parsed and passed through as `protocol=`.

**Verified by:** `test_c01_https_rpc_url_must_stay_https`.

### 12. Address validation never checked which network it was validating against
**Was:** `_validate_address` only checked that a string parses as *some* valid Monero
(sub)address; it never compared the parsed address's network against `self.network_type`, so a
stagenet or testnet address passed as valid even when the provider was configured for mainnet.

**Fix:** compares the address library's own `.net` against the provider's `network_type`.

**Verified by:** `test_c02_address_validation_must_respect_network_type`.

### 13. No floor on the confirmation threshold
**Was:** nothing stopped `confirmation_threshold` being set to `0`, at which point a payment
with zero real confirmations — fully reversible — would be treated as final.

**Fix:** added `@api.constrains` requiring at least 1.

**Verified by:** `test_c04_zero_confirmations_must_be_rejected`.

### 14. Two crons ran the identical job
**Was:** `data/monero_cron.xml` defined two `<record>` blocks sharing the id
`cron_check_payment_status`; Odoo's loader treats a repeated id as the same record redefined in
place, so only the second definition ever actually existed, and it called
`_cron_check_expired_payments()` — already run separately, on its own schedule, by
`cron_check_expired_payments`. The first block's own `_cron_check_payment_status()` method was
never implemented at all.

**Fix:** removed the redundant block; the job it was meant to do is already covered by
`_cron_verify_pending_payments`, which runs every 5 minutes.

**Verified by:** `test_c06_no_two_crons_should_do_identical_work`.

### 15. Monero Admin could write to every payment provider in the database, not just its own
**Was:** the ACL granted `group_monero_admin` full read/write/create on `payment.provider` with
no scoping — a Monero Admin could read and modify any other configured provider's credentials
(Stripe, PayPal, whatever else).

**Fix (18.0/19.0):** added an `ir.rule` scoping the group's access to `[('code', '=',
'monero_rpc')]`. **Fix (20.0):** the same scoping is expressed as the `domain` column on the
model's row in `security/ir.access.csv`, since 20.0 merged `ir.rule` and `ir.model.access` into
a single `ir.access` model — a straight XML port would have been wrong for this version.

**Verified by:** `test_a01_monero_admin_must_not_write_other_providers_credentials`.

### 16. Monero Manager could write/create any POS order, unscoped
**Was:** same pattern on `pos.order` — blanket read/write/create with no rule limiting it to
Monero-related orders.

**Fix:** scoped to orders that actually have a Monero payment attached (`monero_payment_id !=
False`), via the same per-version mechanism as Finding 15.

**Verified by:** `test_a02_monero_manager_pos_order_grant_must_be_scoped`.

### 17. Internal error text was echoed straight back to anonymous callers
**Was:** both `check_payment_status` and `verify_payments` (the controller routes) caught any
exception and returned `str(e)` verbatim to the caller — including, in one reproduction,
internal RPC connection details (hostname, port) from a simulated wallet-RPC failure.

**Fix:** both now log the real exception server-side and return a generic message to the client.

**Verified by:** `test_h04_status_error_must_not_leak_internal_hosts`.

### 18. The token-gated QR image was marked publicly cacheable
**Was:** `Cache-Control: public, max-age=3600` on a response gated by the order's access token —
a shared cache could serve one customer's QR code (and receiving address) to another visitor.

**Fix:** `Cache-Control: private, max-age=3600`.

**Verified by:** `test_h09_token_protected_qr_must_not_be_publicly_cacheable`.

### 19. A dead code branch would have raised if it were ever reached
**Was:** an "RPC-level filter" optimization guarded by `if self.is_subaddress and
self.subaddress_index`, which was always false because `subaddress_index` was never populated
(see Finding 5) — so the branch was dead. Had it run, the real `monero-python` library rejects
its filter kwargs with `ValueError`, not the `TypeError` the fallback caught, so it would have
raised instead of falling back.

**Fix:** broadened the `except` to catch `ValueError` too. Populating `subaddress_index` as part
of Finding 5's fix means this branch is no longer dead — it now runs on every payment, falls
through to a full scan (the library still rejects those kwargs; this isn't a real optimization,
just no longer a crash risk), and does so cleanly.

**Verified by:** `test_s07_subaddress_filter_branch_no_longer_crashes`.

---

## Not fixed, because they were already correct — documented, not defects
Two probes in the previous version's "not re-confirmed as defects" section stay exactly that on
re-verification, now with tests that assert the actual intended behavior instead of merely
observing it:

- **Overpayments never auto-confirm regardless of confirmation count** — `test_s02` now asserts
  this directly: `state == 'overpaid'`, not a defect to fix.
- **Funds arriving after a payment is marked `expired` are not recorded** — `test_s04` now
  asserts this directly too. `check_payment_status`'s early-return guard for
  `confirmed`/`expired`/`failed` is deliberate (its own comment says so); whether it's the right
  business call is worth the module documenting for admins, but it isn't a code defect.

One conclusion changed on re-verification, and is now hardened rather than left alone:
**`/verify` accepted any authenticated user, including portal customers**, reasoned about in the
previous version as "not a bypass since the lookup key is a secret" — true once Finding 5 is
fixed, but there's still no legitimate reason for a portal customer to reach a bulk-verification
endpoint. It's now restricted to the module's own internal groups
(`test_h10_verify_route_must_not_be_open_to_portal_users`).

---

## Scope of this pass
**18.0** got the full adversarial treatment: all 19 fixes above were made directly in this
version's source and re-verified with 65/65 tests (38 shipped + 27 probes) against a real Odoo
18.0 + PostgreSQL install over real HTTP.

**19.0 and 20.0** got every fix ported via diff/patch against their own version-specific source
(handling, by hand, the two places a mechanical port would have been wrong: 20.0's Binary field
now reads back as a `BinaryBytes` object needing `.to_base64()` rather than raw bytes, and
20.0's merge of `ir.rule`/`ir.model.access` into a single `ir.access.csv` with an inline `domain`
column, used for Findings 15 and 16 instead of separate `ir.rule` XML records). Two shipped
tests needed the same corrections on both versions as on 18.0 (Finding 5's `payment_id`
assertion; Finding 6's `payment_page` token argument). Both were then installed fresh on their
own real Odoo (19.0, 20.0) with real PostgreSQL and their own shipped suites re-run: **39/39 on
19.0, 41/41 on 20.0.** The 27-probe adversarial suite itself was not ported to 19.0/20.0 in this
pass — their shipped tests confirm the fixes didn't break anything version-specific, but the
deeper adversarial verification (guest checkout actually succeeding end-to-end, idempotency,
ACL scoping, etc.) was only directly exercised against 18.0.

## POS frontend — unchanged from the previous review
Still not verified: no browser or POS session was run on any version in this pass either. The
19.0 order-validation override and the 20.0 popup-patch gap noted previously are unaffected by
anything in this document and remain open.

## Addendum: constraints on 19.0 and 20.0
Re-running the suites on freshly installed Odoo found that Findings 3 (`UNIQUE(txid, payment_id)`) and the
pre-existing `UNIQUE(payment_id)` / `CHECK(amount > 0)` were **not created on 19.0 and 20.0**: from Odoo 19
`_sql_constraints` is ignored (only a warning is logged), and the module still declared them that way. The
shipped tests passed anyway because none asserted a constraint exists. They are now `models.Constraint`
attributes on both versions, verified in `pg_constraint`, and guarded by `tests/test_db_constraints.py`.
18.0 was unaffected. Finding 3's "database constraint is now scoped to `(txid, payment_id)`" was therefore
only true on 18.0 until this change.
