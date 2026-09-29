from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMoneroDbConstraints(TransactionCase):
    """The declared table constraints must exist in the database.

    On Odoo 20 `_sql_constraints` is silently ignored, so a constraint that is
    declared the old way is never created and nothing else would notice.
    """

    def _constraint_defs(self, table):
        self.env.cr.execute(
            """SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
               WHERE conrelid = %s::regclass AND contype IN ('u', 'c')""",
            [table],
        )
        return dict(self.env.cr.fetchall())

    def test_transaction_txid_payment_unique_exists(self):
        defs = self._constraint_defs('monero_transaction')
        self.assertTrue(
            any('UNIQUE (txid, payment_id)' in d for d in defs.values()),
            "UNIQUE(txid, payment_id) missing from monero_transaction: %s" % defs)

    def test_payment_constraints_exist(self):
        defs = self._constraint_defs('monero_payment')
        self.assertTrue(
            any('UNIQUE (payment_id)' in d for d in defs.values()),
            "UNIQUE(payment_id) missing from monero_payment: %s" % defs)
        self.assertTrue(
            any('CHECK' in d and 'amount' in d for d in defs.values()),
            "CHECK(amount > 0) missing from monero_payment: %s" % defs)
