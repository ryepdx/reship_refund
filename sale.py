from copy import copy
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv, orm
import openerp.addons.decimal_precision as dp

class sale_order(osv.osv):
    _inherit = 'sale.order'

    def _get_payment_methods(self, *args, **kwargs):
        methods = super(sale_order, self)._columns['payment_method'].selection
        if "no_charge" not in dict(methods):
            methods += [("no_charge", "No Charge")]
        return methods

    def _amount_all(self, cr, uid, ids, field_name, arg, context=None):
        no_charge_ids = self.search(
            cr, uid, [('id', 'in', ids), ('payment_method', '=', 'no_charge')], context=context)

        charge_ids = list(set(ids) - set(no_charge_ids))
        res = super(sale_order, self)._amount_all(cr, uid, charge_ids, field_name, arg, context=context)

        for no_charge_id in no_charge_ids:
            res[no_charge_id] = {'amount_untaxed': 0, 'amount_tax': 0, 'amount_total': 0}
        return res

    def _sale_order_amount_all_columns(_amount_all):
        amount_all_cols = [(k, c) for sc in osv.Model.__subclasses__() for (k, c) in sc._columns.iteritems()
                             if sc.__dict__.get('_inherit') == 'sale.order' and hasattr(c, '_fnct')
                             and c._fnct.__name__ == "_amount_all"]
        columns = {}
        for name, column in amount_all_cols:
            if name not in columns:
                columns[name] = copy(column)
                columns[name]._fnct = _amount_all
                columns[name].store = dict([(k, (s[0], s[1] + ['payment_method'], s[2]))
                                            for k, s in columns[name].store.iteritems()])
                continue

            for key, store in column.store.iteritems():
                if key not in columns[name].store:
                    columns[name].store[key] = store
                else:
                    columns[name].store[key][1] = list(set(columns[name].store[key][1] + store[1]))

        return columns

    _columns = dict([('payment_method', fields.selection(_get_payment_methods, 'Payment Method')),
                     ('reship_reason', fields.selection(
                         [('quality', 'Item Quality'), ('wrong', 'Wrong Item'), ('damaged', 'Damaged Item')],
                         'Reason for Reship'))] + _sale_order_amount_all_columns(_amount_all).items())

    def reship(self, cr, uid, ids, copy_lines=True, reason=None, context=None):
        reship_rate_id = self.pool.get('ir.model.data').get_object(
            cr, uid, 'reship_refund', 'shipping_rate_reship')
        reship_rate_id = reship_rate_id.id if reship_rate_id else None
        reship_values = {
            "name": self.pool.get('ir.sequence').get(cr, uid, 'sale.order'),
            "reship_reason": reason,
            "invoice_ids": [],
            "picking_ids": [],
            "client_order_ref": '',
            "state": "draft",
            "payment_method": "no_charge",
            "ship_method_id": reship_rate_id,
            "shipcharge": 0
        }

        sale_data = self.copy_data(cr, uid, ids, default=reship_values)
        sale_id = self.create(cr, uid, sale_data, context=context)

        if not copy_lines:
            line_pool = self.pool.get('sale.order.line')
            line_pool.unlink(cr, uid, line_pool.search(cr, uid, [('order_id', '=', sale_id)]))

        return sale_id

sale_order()