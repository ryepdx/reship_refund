from openerp.osv import orm, fields
from openerp.tools.translate import _
from ..sale import sale_order

class wiz_reship_line(orm.TransientModel):
    _name = 'reship.wizard.line.reship'
    _columns = {
        "sale_line_id": fields.many2one('sale.order.line', 'Sale Order Line', readonly=True),
        "wizard_id": fields.many2one('reship.wizard', 'Wizard', readonly=True),
        "product_id": fields.related('product_id', 'sale_line_id', type="many2one",
                                     relation="product.product", string="Product", store=False),
        "quantity": fields.integer('Quantity')
    }
    _sql_constraints = [
        ('reship_line_unique', 'unique(sale_line_id, wizard_id)', 'Already reshipping this line!')
    ]
wiz_reship_line()


class wiz_refund_line(orm.TransientModel):
    _name = 'reship.wizard.line.refund'
    _columns = {
        "sale_line_id": fields.many2one('sale.order.line', 'Sale Order Line', readonly=True),
        "wizard_id": fields.many2one('reship.wizard', 'Wizard', readonly=True),
        "product_id": fields.related('product_id', 'sale_line_id', type="many2one",
                                     relation="product.product", string="Product", store=False),
        "quantity": fields.integer('Quantity')
    }
    _sql_constraints = [
        ('refund_line_unique', 'unique(sale_line_id, wizard_id)', 'Already refunding this line!')
    ]
wiz_refund_line()


class wiz_reship(orm.TransientModel):
    _name = 'reship.wizard'

    def _sale_order_lines(self, cr, uid, ids, field_names, arg, context):
        res = dict([(i, []) for i in ids])
        for wiz in self.browse(cr, uid, ids, context=context):
            reship = [l.sale_line_id.id for l in wiz.reship_lines]
            refund = [l.sale_line_id.id for l in wiz.refund_lines]
            res[wiz.id] = {
                'original_lines': [
                    l.id for l in wiz.sale_order_id.order_line if l.id not in reship and l.id not in refund
                ]
            }

        return res

    def _net_refund(self, cr, uid, ids, field_name, arg, context):
        res = dict([(i, 0.0) for i in ids])
        for wiz in self.browse(cr, uid, ids, context=context):
            refund_amount = sum([(l.quantity * l.sale_line_id.price_unit)
                                 if l.quantity else l.sale_line_id.price_subtotal for l in wiz.refund_lines
            ])
            new_amount = sum([l.price_subtotal for l in wiz.new_order_lines])
            res[wiz.id] = refund_amount - new_amount

        return res


    _columns = {
        'sale_order_id': fields.many2one('sale.order', 'Sale Order', readonly=True),
        'reason': sale_order._columns['reship_reason'],
        'original_lines': fields.function(_sale_order_lines, method=True, type='one2many',
                                          relation='sale.order.line', string='Original Sale', store=False,
                                          multi=True, readonly=True),
        'reship_lines': fields.one2many("reship.wizard.line.reship", 'wizard_id', 'Reship'),
        'refund_lines': fields.one2many("reship.wizard.line.refund", 'wizard_id', 'Refund'),
        'new_order_lines': fields.many2many("sale.order.line", 'reship_wizard_new_line',
                                            'line_id', 'wizard_id', 'Add'),
        'net_refund': fields.function(_net_refund, type="float", method=True,
                                      store=False, readonly=True, string="Net Refund")
    }

    def _sale_order_id(self, cr, uid, context):
        if context.get('active_model') == 'sale.order' and context.get('active_id'):
            return context.get('active_id')
        return None

    _defaults = {
        'sale_order_id': _sale_order_id
    }

    def add_line(self, cr, uid, ids, line_id, context=None):
        if not ids:
            return {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)
        sale_line = self.pool.get("sale.order.line").browse(cr, uid, line_id, context=context)

        if (wiz.net_refund - sale_line.price_subtotal) < 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'action_warn',
                'name': 'Error',
                'params': {
                   'title': 'Not enough refunded',
                   'text': 'Adding this line would result in additional charges for the customer!'
                }
            }

        reship_pool = self.pool.get("reship.wizard.line.reship")
        refund_pool = self.pool.get("reship.wizard.line.refund")
        reship_pool.unlink(cr, uid, reship_pool.search(cr, uid, [
            ('wizard_id', '=', wiz.id), ('sale_line_id', '=', line_id)]))
        refund_pool.unlink(cr, uid, refund_pool.search(cr, uid, [
            ('wizard_id', '=', wiz.id), ('sale_line_id', '=', line_id)]))
        self.write(cr, uid, wiz.id, {'new_order_lines': [(4, line_id)]}, context=context)

        wiz = self.browse(cr, uid, wiz_id, context=context)
        return {'value': {
            'new_order_lines': [l.id for l in wiz.new_order_lines],
            'refund_lines': [l.id for l in wiz.refund_lines],
            'reship_lines': [l.id for l in wiz.reship_lines],
            'original_lines': [l.id for l in wiz.original_lines],
        }}

    def refund_line(self, cr, uid, ids, line_id, quantity=None, context=None):
        if not ids:
            return {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)

        reship_line_ids = self.pool.get("reship.wizard.line.reship").search(
            cr, uid, [('wizard_id', '=', wiz.id), ('sale_line_id', '=', line_id)])
        self.write(cr, uid, wiz.id, {
            'new_order_lines': [(3, line_id)],
            'refund_lines': [(0, 0, {'sale_line_id': line_id, 'quantity': quantity})],
            'reship_lines': [(3, l) for l in reship_line_ids]
        }, context=context)

        wiz = self.browse(cr, uid, wiz_id, context=context)

        return {'value': {
            'new_order_lines': [l.id for l in wiz.new_order_lines],
            'refund_lines': [l.id for l in wiz.refund_lines],
            'reship_lines': [l.id for l in wiz.reship_lines],
            'original_lines': [l.id for l in wiz.original_lines],
        }}

    def reship_line(self, cr, uid, ids, line_id, quantity=None, context=None):
        if not ids:
            return {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)

        refund_line_ids = self.pool.get("reship.wizard.line.refund").search(
            cr, uid, [('wizard_id', '=', wiz.id), ('sale_line_id', '=', line_id)])
        self.write(cr, uid, wiz.id, {
            'new_order_lines': [(3, line_id)],
            'refund_lines': [(3, l) for l in refund_line_ids],
            'reship_lines': [(0, 0, {"sale_line_id": line_id, "quantity": quantity})]
        }, context=context)

        wiz = self.browse(cr, uid, wiz_id, context=context)

        return {'value': {
            'new_order_lines': [l.id for l in wiz.new_order_lines],
            'refund_lines': [l.id for l in wiz.refund_lines],
            'reship_lines': [l.id for l in wiz.reship_lines],
            'original_lines': [l.id for l in wiz.original_lines],
        }}

    def complete(self, cr, uid, ids, context=None):
        if context is None:
            context = {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        data = self.browse(cr, uid, wiz_id, context=context)
        if data.refund_lines and not data.sale_order_id.invoice_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'action_warn',
                'name': 'Refund failed',
                'params': {
                   'title': 'Failure',
                   'text': 'Cannot issue a refund on a sale order without an invoice.',
                   'sticky': True
                }
            }

        sale_lines = []
        sale_pool = self.pool.get('sale.order')
        line_pool = self.pool.get("sale.order.line")

        for line in data.reship_lines:
            sale_lines.append(line_pool.copy_data(cr, uid, line.sale_line_id.id, default={
                'product_uos_qty': line.quantity or line.sale_line_id.product_uos_qty,
                'product_uom_qty': line.quantity or line.sale_line_id.product_uom_qty,
                'discount': '1.0'
            }))

        for line in data.new_order_lines:
            sale_lines.append(line_pool.copy_data(cr, uid, line.id))

        if data.refund_lines:
            context['refund_total'] = data.net_refund
            context['refund_lines'] = dict([
                (il.id, l.quantity or il.quantity) for l in data.refund_lines for il in l.sale_line_id.invoice_lines
            ])
            refund_invoices = self.pool.get('account.invoice').refund(
                cr, uid, [data.sale_order_id.invoice_ids[0].id],
                description="Refund" + (" issued for: %s" % data.reason if data.reason else ""), context=context)

            if refund_invoices:
                sale_pool.write(cr, uid, data.sale_order_id.id, {
                    "invoice_ids": [(4, inv_id) for inv_id in refund_invoices]
                })

        if sale_lines:
            sale_id = sale_pool.reship(
                cr, uid, data.sale_order_id.id, reason=data.reason, copy_lines=False, context=context)
            sale_pool.write(cr, uid, sale_id, {'order_line': [(0, 0, line) for line in sale_lines]})

            view_ref = self.pool.get('ir.model.data').get_object_reference(cr, uid, 'sale', 'view_order_form')
            return {
                'type': 'ir.actions.act_window',
                'name': _('Sales Order'),
                'res_model': 'sale.order',
                'res_id': sale_id,
                'view_type': 'form',
                'view_mode': 'form',
                'view_id': view_ref and view_ref[1] or False,
                'target': 'current',
                'nodestroy': True,
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'action_info',
            'name': 'Refunded',
            'params': {
               'title': 'Success',
               'text': 'Refund processed. No new sale was created because no reships or exchanges were requested.',
               'sticky': False
            }
        }

wiz_reship()