from openerp.osv import orm, fields
from openerp.tools.translate import _
from ..sale import sale_order


class wiz_reship(orm.TransientModel):
    _name = 'reship.wizard'

    def _sale_order_lines(self, cr, uid, ids, field_names, arg, context):
        res = dict([(i, []) for i in ids])
        for wiz in self.browse(cr, uid, ids, context=context):
            reship = [l.id for l in wiz.reship_lines]
            refund = [l.id for l in wiz.refund_lines]
            new = [l.id for l in wiz.new_lines]
            res[wiz.id] = {
                'original_lines': [
                    l.id for l in wiz.sale_order_id.order_line if l.id not in reship and l.id not in refund
                ],
                'preview': reship + new
            }

        return res

    _columns = {
        'sale_order_id': fields.many2one('sale.order', 'Sale Order', readonly=True),
        'reason': sale_order._columns['reship_reason'],
        'original_lines': fields.function(_sale_order_lines, method=True, type='one2many',
                                          relation='sale.order.line', string='Original Sale', store=False,
                                          multi=True, readonly=True),
        'reship_lines': fields.many2many("sale.order.line", 'reship_wizard_reship_line',
                                         'line_id', 'wizard_id', 'Reship'),
        'refund_lines': fields.many2many("sale.order.line", 'reship_wizard_refund_line',
                                         'line_id', 'wizard_id', 'Refund'),
        'new_lines': fields.many2many("sale.order.line", 'reship_wizard_new_line',
                                      'line_id', 'wizard_id', 'Add'),
        'preview': fields.function(_sale_order_lines, method=True, type='one2many',
                                   relation='sale.order.line', string='New Sale', store=False,
                                   multi=True, readonly=True),
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
        refund_amount = sum([l.price_subtotal for l in wiz.refund_lines])
        new_amount = sum([l.price_subtotal for l in wiz.new_lines]) + sale_line.price_subtotal

        if new_amount > refund_amount:
            return {
                'type': 'ir.actions.client',
                'tag': 'action_warn',
                'name': 'Error',
                'params': {
                   'title': 'Not enough refunded',
                   'text': 'Adding this line would result in additional charges for the customer!'
                }
            }

        self.write(cr, uid, wiz.id, {
            'reship_lines': [(3, line_id)],
            'refund_lines': [(3, line_id)],
            'new_lines': [(4, line_id)]
        }, context=context)

        wiz = self.browse(cr, uid, wiz_id, context=context)
        return {'value': {
            'new_lines': [l.id for l in wiz.new_lines],
            'refund_lines': [l.id for l in wiz.refund_lines],
            'reship_lines': [l.id for l in wiz.reship_lines],
            'preview': [l.id for l in wiz.preview],
            'original_lines': [l.id for l in wiz.original_lines],
        }}

    def refund_line(self, cr, uid, ids, line_id, context=None):
        if not ids:
            return {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)

        self.write(cr, uid, wiz.id, {
            'reship_lines': [(3, line_id)],
            'refund_lines': [(4, line_id)],
            'new_lines': [(3, line_id)]
        }, context=context)

        wiz = self.browse(cr, uid, wiz_id, context=context)

        return {'value': {
            'new_lines': [l.id for l in wiz.new_lines],
            'refund_lines': [l.id for l in wiz.refund_lines],
            'reship_lines': [l.id for l in wiz.reship_lines],
            'preview': [l.id for l in wiz.preview],
            'original_lines': [l.id for l in wiz.original_lines],
        }}

    def reship_line(self, cr, uid, ids, line_id, context=None):
        if not ids:
            return {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)

        self.write(cr, uid, wiz.id, {
            'reship_lines': [(4, line_id)],
            'refund_lines': [(3, line_id)],
            'new_lines': [(3, line_id)]
        }, context=context)

        wiz = self.browse(cr, uid, wiz_id, context=context)

        return {'value': {
            'new_lines': [l.id for l in wiz.new_lines],
            'refund_lines': [l.id for l in wiz.refund_lines],
            'reship_lines': [l.id for l in wiz.reship_lines],
            'preview': [l.id for l in wiz.preview],
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
            sale_lines.append(line_pool.copy_data(cr, uid, line.id, default={'discount': '1.0'}))

        for line in data.new_lines:
            sale_lines.append(line_pool.copy_data(cr, uid, line.id))

        if data.refund_lines:
            refund_amount = sum([l.price_subtotal for l in data.refund_lines])
            new_amount = sum([l.price_subtotal for l in data.new_lines])
            context['refund_total'] = refund_amount - new_amount
            context['refund_lines'] = [l.id for ol in data.refund_lines for l in ol.invoice_lines]
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