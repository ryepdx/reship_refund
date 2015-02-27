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

        refund_discount_orders = self.browse(cr, uid, self.search(
            cr, uid, [('id', 'in', ids), ('refund_discount', '!=', 0)], context=context))
        for order in refund_discount_orders:
            res[order.id]['amount_total'] = max(0, res[order.id]['amount_total'] + order.refund_discount)

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

    def _invoice_get_order(invpool, cr, uid, ids, context=None):
        return invpool.pool.get('sale.order').search(cr, uid, [('refund_invoice_ids', 'in', ids)], context=context)

    _columns = dict([('payment_method', fields.selection(_get_payment_methods, 'Payment Method')),
                     ('reship_reason', fields.selection(
                         [('quality', 'Item Quality'), ('wrong', 'Wrong Item'), ('damaged', 'Damaged Item')],
                         'Reason for Reship')),
                        ('refund_invoice_ids', fields.many2many(
                            'account.invoice', 'sale_order_refund_invoice_rel', 'order_id',
                            'invoice_id', 'Invoice Lines', readonly=True)),
                        ('refund_discount', fields.float('Refund Discount', readonly=True,
                            digits_compute=dp.get_precision('Account')))
                     ] + _sale_order_amount_all_columns(_amount_all).items())

    def reship(self, cr, uid, ids, copy_lines=True, reason=None, default={}, context=None):
        reship_rate_id = self.pool.get('ir.model.data').get_object(
            cr, uid, 'reship_refund', 'shipping_rate_reship')
        reship_rate_id = reship_rate_id.id if reship_rate_id else None
        default.update({
            "name": self.pool.get('ir.sequence').get(cr, uid, 'sale.order'),
            "reship_reason": reason,
            "invoice_ids": [],
            "picking_ids": [],
            "client_order_ref": '',
            "state": "draft",
            "ship_method_id": reship_rate_id,
            "shipcharge": 0
        })

        sale_data = self.copy_data(cr, uid, ids, default=default)
        sale_id = self.create(cr, uid, sale_data, context=context)

        if not copy_lines:
            line_pool = self.pool.get('sale.order.line')
            line_pool.unlink(cr, uid, line_pool.search(cr, uid, [('order_id', '=', sale_id)]))

        return sale_id

sale_order()

class sale_order_line(osv.osv):
    _inherit = "sale.order.line"

    def _out_move(self, cr, uid, ids, field_name, arg, context):
        res = {}
        for line in self.browse(cr, uid, ids, context=context):
            out_moves = sorted([m for m in line.move_ids if m.type == 'out'], key=lambda x: x.id)
            in_moves = [m for m in line.move_ids if m.type == 'in']
            res[line.id] = out_moves[-1] if len(out_moves) > len(in_moves) else None
        return res

    _columns = {
        'out_move': fields.function(_out_move, type="many2one", method=True,
                                    store=False, readonly=True, string="Outgoing Move")
    }