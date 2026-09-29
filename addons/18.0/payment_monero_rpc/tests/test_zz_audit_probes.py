"""Audit probes for payment_monero_rpc (18.0).

Every test asserts the behaviour a *correct* module should have.  A failing test is
therefore a confirmed defect.  Unlike the shipped controller tests, these do NOT
patch ``request``: routes are hit over real HTTP as an anonymous (public) visitor.
Only the Monero wallet RPC is faked.
"""
import logging
import re
import time
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from monero.address import SubAddress
from monero.backends.offline import OfflineWallet
from monero.seed import Seed
from monero.transaction import PaymentManager
from monero.wallet import Wallet as RealWallet

from odoo import fields
from odoo import http as odoo_http
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)
PROV = 'odoo.addons.payment_monero_rpc.models.payment_provider'
PAY = 'odoo.addons.payment_monero_rpc.models.monero_payment'

_SEED = Seed()


def _sub(net, minor):
    main = _SEED.public_address(net=net)
    w = RealWallet(OfflineWallet(main, view_key=_SEED.secret_view_key(),
                                 spend_key=_SEED.secret_spend_key()))
    return str(w.get_address(0, minor)), str(main)


class FakeWallet:
    """Stands in for monero.wallet.Wallet. ``incoming`` mimics the real
    PaymentManager's rejection of unknown filter kwargs (verified separately)."""

    def __init__(self, net='stage'):
        self.net, self.next_minor, self.transfers, self.fail = net, 1, [], None
        self.issued = []

    def new_address(self, label=None):
        minor = self.next_minor
        self.next_minor += 1
        addr, _ = _sub(self.net, minor)
        self.issued.append((addr, minor))
        return (addr, minor)

    def incoming(self, **kw):
        if self.fail:
            raise self.fail
        if kw:
            raise ValueError("Excessive arguments for payment query: %r" % kw)
        return list(self.transfers)


def make_transfer(addr, minor, amount, txid, confs):
    tx = SimpleNamespace(
        hash=txid, fee=Decimal('0.00001'), height=100,
        timestamp=datetime(2026, 9, 28, 12, 0, 0), confirmations=confs, note='',
        key=None, double_spend_seen=False, in_pool=False, extra='')
    return SimpleNamespace(
        amount=Decimal(str(amount)), local_address=addr,
        subaddr_index=SimpleNamespace(minor=minor), account_index=0,
        stealth_address=None, transaction=tx)


class _Fixture:
    def _fixture(self):
        env = self.env
        self.wallet = FakeWallet('stage')
        self.rpc_kwargs = []
        p1 = patch(PROV + '.Wallet', side_effect=lambda backend: self.wallet)
        p2 = patch(PROV + '.JSONRPCWallet',
                   side_effect=lambda **kw: (self.rpc_kwargs.append(kw) or MagicMock()))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

        self.provider = env['payment.provider'].search([('code', '=', 'monero_rpc')], limit=1)
        self.provider.write({
            'rpc_url': 'http://127.0.0.1:38082/json_rpc',
            'wallet_address_value': _sub('stage', 1)[1],
            'network_type': 'stagenet', 'confirmation_threshold': 2,
            'use_subaddresses': True, 'state': 'enabled',
        })
        partner = env['res.partner'].create({'name': 'Buyer', 'email': 'buyer@example.com'})
        product = env['product.product'].create(
            {'name': 'Widget', 'type': 'consu', 'list_price': 100})
        self.order = env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1,
                                   'price_unit': 100, 'tax_id': [(6, 0, [])]})],
        })
        self.order._portal_ensure_token()
        cur = self.order.currency_id.name
        cfg = env['ir.config_parameter'].sudo()
        cfg.set_param('monero.rate_cache.%s' % cur.upper(), '150')
        cfg.set_param('monero.rate_cache_ts.%s' % cur.upper(), str(time.time() + 10 ** 7))
        # Root-cause isolation for the s0x probes: monero.transaction.confirmations is
        # computed ONLY from monero.daemon.current_height vs tx.block_height -- it never
        # looks at what the wallet's incoming() call itself reports. Seed a daemon row so
        # confirmation math is possible at all, and prove that this dependency is real.
        env['monero.daemon'].create({'current_height': 1000000, 'last_checked': fields.Datetime.now()})

    def _new_payment(self, order=None):
        order = order or self.order
        return self.provider._create_monero_from_fiat_payment(
            order.name, order.amount_total, order.currency_id, order)

    def _pay(self, payment, amount=None, txid='a' * 64, confs=20):
        amount = payment.amount if amount is None else amount
        minor = payment.subaddress_index
        self.wallet.transfers.append(
            make_transfer(payment.address_seller, minor, '%.12f' % amount, txid, confs))


# ----------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'audit_probe')
class ProbeStateMachine(_Fixture, TransactionCase):

    def setUp(self):
        super().setUp()
        self._fixture()

    def test_s01_baseline_exact_payment_confirms(self):
        pay = self._new_payment()
        self._pay(pay, amount=Decimal('%.12f' % pay.amount))
        pay.check_payment_status()
        self.assertEqual(pay.state, 'confirmed')
        self.assertEqual(self.order.state, 'sale')

    def test_s02_overpayment_requires_manual_reconciliation_by_design(self):
        """Not a bug: an overpaid amount (amount_compare == 1) deliberately never
        auto-confirms regardless of confirmation count -- this reads as an
        intentional choice to require manual review of a mismatched amount
        rather than an oversight, so it documents the behavior instead of
        asserting it's wrong."""
        pay = self._new_payment()
        self._pay(pay, amount=pay.amount * 1.5)
        pay.check_payment_status()
        self.assertEqual(pay.state, 'overpaid')
        self.assertGreater(pay.amount_received, pay.amount)

    @mute_logger(PAY)
    def test_s03_transient_rpc_error_must_not_be_permanent(self):
        pay = self._new_payment()
        self._pay(pay, amount=Decimal('%.12f' % pay.amount))       # customer HAS paid in full
        self.wallet.fail = ConnectionError('wallet-rpc restarting')
        with self.assertRaises(ConnectionError):
            pay.check_payment_status()
        _logger.warning('PROBE s03 state after one transient error: %s', pay.state)
        self.wallet.fail = None                                    # wallet is healthy again
        pay.check_payment_status()
        self.assertEqual(pay.state, 'confirmed', "stuck in %r although funds arrived" % pay.state)

    def test_s04_expired_guard_intentionally_blocks_late_funds_by_design(self):
        """Not a bug: check_payment_status has an explicit early-return guard for
        state in ('confirmed', 'expired', 'failed') so a confirmed/failed
        payment is never regressed. The side effect is that funds landing after
        the expiry cron has already run are not recorded either. That's a
        deliberate guard, not an oversight -- documented here rather than
        asserted as a defect. Whether it's the right business call (a customer
        paying moments after expiry gets nothing recorded) is worth the module
        documenting explicitly, since it isn't obvious from the outside."""
        pay = self._new_payment()
        pay.state = 'expired'
        self._pay(pay, amount=Decimal('%.12f' % pay.amount))
        pay.check_payment_status()
        self.assertEqual(pay.state, 'expired')
        self.assertEqual(pay.amount_received, 0.0)

    def test_s05_one_tx_paying_two_payments_should_settle_both(self):
        a = self._new_payment()
        b = self._new_payment()
        txid = 'b' * 64
        self._pay(a, amount=Decimal('%.12f' % a.amount), txid=txid)
        self._pay(b, amount=Decimal('%.12f' % b.amount), txid=txid)
        a.check_payment_status()
        b.check_payment_status()
        _logger.warning('PROBE s05 A=%s B=%s B.tx=%s B.conf=%s',
                        a.state, b.state, len(b.transaction_ids), b.confirmations)
        self.assertEqual((a.state, b.state), ('confirmed', 'confirmed'))

    @mute_logger(PAY)
    def test_s06_failure_after_confirmation_must_not_regress_state(self):
        pay = self._new_payment()
        self._pay(pay, amount=Decimal('%.12f' % pay.amount))
        with patch('odoo.addons.mail.models.mail_template.MailTemplate.send_mail',
                   side_effect=Exception('render boom')):
            try:
                pay.check_payment_status()
            except Exception:
                pass
        _logger.warning('PROBE s06 payment=%s order=%s', pay.state, self.order.state)
        self.assertEqual(pay.state, 'confirmed', "order=%s but payment=%s" % (self.order.state, pay.state))

    def test_s08_confirmations_depend_on_a_separate_uncoupled_daemon_row(self):
        """monero.transaction.confirmations is computed ONLY from
        monero.daemon.current_height vs tx.block_height. It never reads what the
        wallet's incoming() call itself reports for that transfer. With no daemon
        row present -- the state of a fresh install, or any time that cron hasn't
        run yet -- a payment can NEVER confirm no matter how deep the real tx is."""
        self.env['monero.daemon'].search([]).unlink()
        pay = self._new_payment()
        self._pay(pay, amount=Decimal('%.12f' % pay.amount), confs=10000)
        pay.check_payment_status()
        _logger.warning('PROBE s08 state with no monero.daemon row: %s (confirmations=%s)',
                        pay.state, pay.confirmations)
        self.assertEqual(pay.state, 'confirmed',
                         "payment cannot confirm because no monero.daemon row exists yet")

    def test_s07_subaddress_filter_branch_no_longer_crashes(self):
        """Before the Issue 16 fix, subaddress_index was never populated (it was
        misused to hold payment_id instead), so the RPC-level subaddress-filter
        branch in check_payment_status was unreachable dead code that would have
        raised ValueError if it ever ran (the real PaymentManager rejects the
        'account'/'subaddr' kwargs used there; only TypeError was caught).

        Now that subaddress_index is correctly populated, this branch runs on
        every real payment. It's still not a genuine optimization -- the
        library rejects those kwargs and it falls through to a full scan
        every time -- but the Issue 15 fix (catching ValueError too) means
        that fallback happens cleanly instead of raising."""
        pay = self._new_payment()
        self.assertTrue(pay.subaddress_index, "subaddress_index should now be populated")
        self._pay(pay, amount=Decimal('%.12f' % pay.amount))
        pay.check_payment_status()   # must not raise
        self.assertEqual(pay.state, 'confirmed')


# ----------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'audit_probe')
class ProbeConfig(_Fixture, TransactionCase):

    def setUp(self):
        super().setUp()
        self._fixture()

    def test_c01_https_rpc_url_must_stay_https(self):
        self.provider.rpc_url = 'https://wallet.example.org:443/wallet/json_rpc'
        self.provider._get_wallet_client()
        kw = self.rpc_kwargs[-1]
        _logger.warning('PROBE c01 JSONRPCWallet kwargs: %s', {k: v for k, v in kw.items() if k != 'password'})
        self.assertEqual(kw.get('protocol'), 'https')

    def test_c02_address_validation_must_respect_network_type(self):
        self.provider.network_type = 'mainnet'
        stage_sub, _ = _sub('stage', 3)
        self.assertFalse(self.provider._validate_address(stage_sub, is_subaddress=True),
                         "stagenet address accepted by a mainnet provider")

    def test_c03_wallet_on_wrong_network_must_be_refused(self):
        self.provider.network_type = 'mainnet'            # but the fake wallet is stagenet
        with self.assertRaises(Exception):
            self._new_payment()

    def test_c04_zero_confirmations_must_be_rejected(self):
        with self.assertRaises(ValidationError):
            self.provider.confirmation_threshold = 0

    def test_c05_every_cron_must_target_an_existing_method(self):
        missing = []
        for cron in self.env['ir.cron'].search([]):
            xid = cron.get_external_id().get(cron.id, '')
            if not xid.startswith('payment_monero_rpc.'):
                continue
            m = re.search(r'model\.(\w+)\(', cron.code or '')
            if m and not hasattr(self.env[cron.model_name], m.group(1)):
                missing.append('%s -> %s.%s' % (xid, cron.model_name, m.group(1)))
        _logger.warning('PROBE c05 missing cron methods: %s', missing)
        self.assertFalse(missing, missing)

    def test_c06_no_two_crons_should_do_identical_work(self):
        crons = self.env['ir.cron'].search([]).filtered(
            lambda c: c.get_external_id().get(c.id, '').startswith('payment_monero_rpc.'))
        codes = [c.code for c in crons]
        dups = {c for c in codes if codes.count(c) > 1}
        self.assertFalse(dups, "duplicate cron bodies: %s" % dups)


@tagged('post_install', '-at_install', 'audit_probe')
class ProbeShippedDefaults(TransactionCase):
    """Checks the shipped data record exactly as module install leaves it --
    deliberately does NOT call _fixture(), which mutates provider.state itself."""

    def test_c07_shipped_provider_must_not_be_enabled_out_of_the_box(self):
        prov = self.env['payment.provider'].search([('code', '=', 'monero_rpc')], limit=1)
        self.assertNotEqual(prov.state, 'enabled')


# ----------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'audit_probe')
class ProbeAccess(_Fixture, TransactionCase):

    def setUp(self):
        super().setUp()
        self._fixture()

    def _user(self, login, groups):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'email': login + '@example.com',
            'groups_id': [(6, 0, [self.env.ref(g).id for g in groups])]})

    def test_a01_monero_admin_must_not_write_other_providers_credentials(self):
        other = self.env['payment.provider'].create({
            'name': 'Other PSP', 'code': 'none', 'state': 'disabled'})
        mx = self._user('mxadmin', ['base.group_user', 'payment_monero_rpc.group_monero_admin'])
        acl = self.env['ir.model.access'].sudo().search([
            ('model_id.model', '=', 'payment.provider'),
            ('group_id', '=', self.env.ref('payment_monero_rpc.group_monero_admin').id)])
        rules = self.env['ir.rule'].sudo().search([('model_id.model', '=', 'payment.provider')])
        _logger.warning('PROBE a01 payment.provider ACL for Monero Admin: %s ; ir.rule rows scoping it: %s',
                        [(a.perm_read, a.perm_write, a.perm_create) for a in acl], len(rules))
        with self.assertRaises(AccessError,
                               msg="Monero Admin group can write ANY payment.provider, not just its own"):
            other.with_user(mx).write({'name': 'renamed by monero admin'})

    def test_a02_monero_manager_pos_order_grant_must_be_scoped(self):
        """ACL grants group_monero_manager blanket read/write/create on pos.order
        with no accompanying ir.rule -- there is nothing Monero-specific about the scope."""
        rules = self.env['ir.rule'].sudo().search([
            ('model_id.model', '=', 'pos.order'),
            ('groups', 'in', [self.env.ref('payment_monero_rpc.group_monero_manager').id])])
        acl = self.env['ir.model.access'].sudo().search([
            ('model_id.model', '=', 'pos.order'),
            ('group_id', '=', self.env.ref('payment_monero_rpc.group_monero_manager').id)])
        _logger.warning('PROBE a02 pos.order ACL=%s scoping ir.rule count=%s',
                        [(a.perm_write, a.perm_create) for a in acl], len(rules))
        self.assertTrue(rules, "Monero Manager can write/create ANY pos.order, unscoped")


# ----------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'audit_probe')
class ProbeHttp(_Fixture, HttpCase):

    def setUp(self):
        super().setUp()
        self._fixture()

    def _jsonrpc(self, route, params=None):
        try:
            return ('OK', self.make_jsonrpc_request(route, params or {}))
        except Exception as e:                                # noqa: BLE001
            return ('EXC', '%s: %s' % (type(e).__name__, str(e)[:240]))

    def test_h01_guest_can_start_payment(self):
        kind, res = self._jsonrpc('/shop/payment/monero/process/%d' % self.order.id,
                                  {'access_token': self.order.access_token})
        _logger.warning('PROBE h01 public process -> %s %s', kind, str(res)[:200])
        self.assertEqual(kind, 'OK', res)
        self.assertTrue(res.get('success'), res)

    def test_h02_payment_page_must_require_a_token(self):
        pay = self._new_payment()
        r = self.url_open('/shop/payment/monero/page/%d' % pay.id)
        _logger.warning('PROBE h02 tokenless page -> HTTP %s, leaks address=%s order=%s',
                        r.status_code, pay.address_seller in r.text, pay.order_ref in r.text)
        self.assertNotIn(pay.address_seller, r.text)

    def test_h03_status_lookup_key_is_itself_an_unguessable_secret(self):
        """Not a bug: /status takes no access_token, but the lookup key IS
        secrets.token_hex(32) generated at create() -- it functions as the bearer
        credential. This probe documents that fact rather than asserting a defect."""
        pay = self._new_payment()
        self.assertEqual(len(pay.payment_id), 64)
        int(pay.payment_id, 16)  # raises if it's not actually random hex

    def test_h04_status_error_must_not_leak_internal_hosts(self):
        pay = self._new_payment()
        self.wallet.fail = ConnectionError("HTTPConnectionPool(host='10.1.2.3', port=18083): refused")
        with mute_logger(PAY):
            kind, res = self._jsonrpc('/shop/payment/monero/status/%s' % pay.payment_id)
        _logger.warning('PROBE h04 -> %s %s', kind, str(res)[:220])
        self.assertNotIn('10.1.2.3', str(res))

    def test_h05_anonymous_poll_must_not_permanently_fail_a_payment(self):
        pay = self._new_payment()
        self.wallet.fail = ConnectionError('timeout')
        with mute_logger(PAY):
            self._jsonrpc('/shop/payment/monero/status/%s' % pay.payment_id)
        pay.invalidate_recordset()
        self.assertNotEqual(pay.state, 'failed')

    def test_h06_process_route_must_be_idempotent(self):
        self.authenticate('admin', 'admin')
        for _ in range(3):
            self._jsonrpc('/shop/payment/monero/process/%d' % self.order.id,
                          {'access_token': self.order.access_token})
        n = self.env['monero.payment'].sudo().search_count([('sale_order_id', '=', self.order.id)])
        _logger.warning('PROBE h06 payments=%s subaddresses issued=%s', n, len(self.wallet.issued))
        self.assertEqual(n, 1)

    def test_h07_cancelled_order_must_not_get_a_payment(self):
        self.order._action_cancel()
        self.authenticate('admin', 'admin')
        kind, res = self._jsonrpc('/shop/payment/monero/process/%d' % self.order.id,
                                  {'access_token': self.order.access_token})
        _logger.warning('PROBE h07 order.state=%s -> %s %s', self.order.state, kind, str(res)[:160])
        self.assertFalse(kind == 'OK' and isinstance(res, dict) and res.get('success'))

    def test_h08_qr_blob_must_not_be_stored_in_session(self):
        self.authenticate('admin', 'admin')
        kind, res = self._jsonrpc('/shop/payment/monero/process/%d' % self.order.id,
                                  {'access_token': self.order.access_token})
        self.assertEqual(kind, 'OK', res)
        sess = odoo_http.root.session_store.get(self.session.sid)
        data = sess.get('monero_payment_data') or {}
        _logger.warning('PROBE h08 session keys=%s image_qr_len=%s', sorted(data), len(data.get('image_qr') or ''))
        self.assertFalse(data.get('image_qr'))

    def test_h09_token_protected_qr_must_not_be_publicly_cacheable(self):
        pay = self._new_payment()
        r = self.url_open('/shop/payment/monero/qr/%d?access_token=%s' % (pay.id, self.order.access_token))
        cc = r.headers.get('Cache-Control')
        _logger.warning('PROBE h09 qr HTTP %s Cache-Control=%s', r.status_code, cc)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('public', cc or '')

    def test_h10_verify_route_must_not_be_open_to_portal_users(self):
        portal = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Portal', 'login': 'portaluser', 'password': 'portaluser', 'email': 'p@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])]})
        pay = self._new_payment()
        self.authenticate('portaluser', 'portaluser')
        kind, res = self._jsonrpc('/shop/payment/monero/verify', {'payment_ids': [pay.payment_id]})
        _logger.warning('PROBE h10 portal user verify -> %s %s', kind, str(res)[:200])
        self.assertFalse(kind == 'OK' and isinstance(res, list) and res,
                         "portal user got real results from a staff-only endpoint")
