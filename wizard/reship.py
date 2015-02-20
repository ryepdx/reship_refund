from openerp.osv import orm, fields
from openerp.tools.translate import _
from ..sale import sale_order
import openerp.addons.decimal_precision as dp

class _wiz_line(object):
    _columns = {
        "selected": fields.boolean("Selected"),
        "sale_line_id": fields.many2one('sale.order.line', 'Sale Order Line', readonly=True),
        "wizard_id": fields.many2one('reship.wizard', 'Wizard', readonly=True),
        "product_id": fields.related('sale_line_id', 'product_id', type="many2one",
                                     relation="product.product", string="Product", store=False, readonly=True),
        "quantity": fields.integer('Quantity')
    }

    def onchange_quantity(self, cr, uid, ids, quantity, context=None):
        for line in self.browse(cr, uid, ids, context=context):
            max_quantity = line.sale_line_id.product_uom_qty
            if quantity > max_quantity:
                return {
                    'warning': {
                        'title': 'Invalid Quantity',
                        'message': 'Original sale only had %s!' % str(int(max_quantity))
                    },
                    'value': {'quantity': max_quantity}
                }
        return True


class wiz_reship_line(_wiz_line, orm.TransientModel):
    _name = 'reship.wizard.line.reship'
    _columns = _wiz_line._columns
    _sql_constraints = [
        ('reship_line_unique', 'unique(sale_line_id, wizard_id)', 'Already reshipping this line!')
    ]

wiz_reship_line()


class wiz_refund_line(orm.TransientModel, _wiz_line):
    _name = 'reship.wizard.line.refund'
    _columns = _wiz_line._columns
    _sql_constraints = [
        ('refund_line_unique', 'unique(sale_line_id, wizard_id)', 'Already refunding this line!')
    ]

wiz_refund_line()


class wiz_new_line(orm.TransientModel):
    _name = 'reship.wizard.line.new'
    _inherit= 'sale.order.line'
    _columns = {
        'order_id': fields.many2one('sale.order', 'Order Reference', required=False),
        'wizard_id': fields.many2one('reship.wizard', 'Wizard', readonly=True),
    }

    def _sale_order_id(self, cr, uid, context):
        sale_order_id = None
        if context.get('active_model') == 'reship.wizard' and context.get('active_id'):
            wiz = self.pool.get("reship.wizard").browse(cr, uid, context.get('active_id'))
            if wiz:
                sale_order_id = wiz.sale_order_id.id
        return sale_order_id

    _defaults = {
        "order_id": _sale_order_id
    }


class wiz_original_line(orm.TransientModel):
    _name = 'reship.wizard.line.original'
    _columns = {
        "sale_line_id": fields.many2one('sale.order.line', 'Sale Order Line', readonly=True),
        "wizard_id": fields.many2one('reship.wizard', 'Wizard', readonly=True),
        "selected": fields.boolean("Selected"),
        "state": fields.related('sale_line_id', 'state', type="selection", string="Status", store=False, readonly=True),
        "product_id": fields.related('sale_line_id', 'product_id',  type="many2one",
                                     relation="product.product", string="Product", store=False, readonly=True),
        "product_uom_qty": fields.related('sale_line_id', 'product_uom_qty', type="float", string="Quantity",
                                          store=False, readonly=True),
        "product_uom": fields.related('sale_line_id', 'product_uom', type="many2one",
                                      relation="product.uom", string="UOM", store=False, readonly=True),
    }
    _sql_constraints = [
        ('original_line_unique', 'unique(sale_line_id, wizard_id)', 'Already have this line!')
    ]
wiz_original_line()


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
            res[wiz.id] = wiz.gross_refund - sum([l.price_subtotal for l in wiz.new_order_lines])

        return res

    def _gross_refund(self, cr, uid, ids, field_name, arg, context):
        res = dict([(i, 0.0) for i in ids])
        for wiz in self.browse(cr, uid, ids, context=context):
            res[wiz.id] = sum([(l.quantity * l.sale_line_id.price_unit)
                                 if l.quantity else l.sale_line_id.price_subtotal for l in wiz.refund_lines
            ])

        return res

    _columns = {
        'error_message': fields.text('Error', readonly=1),
        'sale_order_id': fields.many2one('sale.order', 'Sale Order', readonly=True),
        'partner_id': fields.related('sale_order_id', 'partner_id', type='many2one', relation='res.partner',
                                     string='Customer', store=False, readonly=True),
        'invoice_exists': fields.related('sale_order_id', 'invoice_exists', type='boolean',
                                         string='Invoice Exists', store=False, readonly=True),
        'pricelist_id': fields.related('sale_order_id', 'pricelist_id', type='many2one', relation='product.pricelist',
                                       string='Pricelist', store=False, readonly=True),
        'shop_id': fields.related('sale_order_id', 'shop_id', type='many2one', relation='sale.shop',
                                  string='Shop', store=False, readonly=True),
        'date_order': fields.related('sale_order_id', 'date_order', type='date',
                                     string='Date', store=False, readonly=True),
        'fiscal_position': fields.related('sale_order_id', 'fiscal_position', type='many2one',
                                          relation='account.fiscal.position', string='Fiscal Position',
                                          store=False, readonly=True),
        'reason': sale_order._columns['reship_reason'],
        'original_lines': fields.one2many("reship.wizard.line.original", 'wizard_id', 'Original'),
        'reship_lines': fields.one2many("reship.wizard.line.reship", 'wizard_id', 'Reship'),
        'refund_lines': fields.one2many("reship.wizard.line.refund", 'wizard_id', 'Refund'),
        'new_order_lines': fields.one2many("reship.wizard.line.new", 'wizard_id', 'Create'),
        'net_refund': fields.function(_net_refund, type="float", method=True,
                                      store=False, readonly=True, string="Net Refund"),
        'gross_refund': fields.function(_gross_refund, type="float", method=True,
                                        store=False, readonly=True, string="Gross Refund")
    }

    def _sale_order_id(self, cr, uid, context):
        if context.get('active_model') == 'sale.order' and context.get('active_id'):
            return context.get('active_id')
        return None

    def _original_lines(self, cr, uid, context):
        sale = None
        if context.get('active_model') == 'sale.order' and context.get('active_id'):
            sale = self.pool.get("sale.order").browse(cr, uid, context.get('active_id'), context=context)

        if sale:
            lines = []
            for l in sale.order_line:
                lines.append({'sale_line_id': l.id, 'product_id': l.product_id.id,
                              'product_uom': l.product_uom.id, 'product_uom_qty': l.product_uom_qty,
                              'state': l.state, 'selected': False})

            return lines
        return None

    def _sale_order(fieldname):
        def _field(self, cr, uid, context):
            sale_id = self._sale_order_id(cr, uid, context)
            if not sale_id:
                return None

            sale = self.pool.get("sale.order").browse(cr, uid, sale_id)
            if not sale:
                return None

            if hasattr(sale, fieldname):
                value = getattr(sale, fieldname)
                if hasattr(value, "id"):
                    value = value.id

                return value

        return _field

    _defaults = {
        'sale_order_id': _sale_order_id,
        'original_lines': _original_lines,
        'partner_id': _sale_order("partner_id"),
        'pricelist_id': _sale_order("pricelist_id"),
        'shop_id': _sale_order("shop_id"),
        'date_order': _sale_order("date_order"),
        'fiscal_position': _sale_order("fiscal_position"),
    }

    def refund_line(self, cr, uid, ids, line_ids, quantity=None, context=None):
        return self._reship_refund_line(cr, uid, ids, line_ids, type="refund", context=context)

    def refund_lines(self, cr, uid, ids, context=None):
        return self._reship_refund_lines(cr, uid, ids, type="refund", context=context)

    def reship_line(self, cr, uid, ids, line_ids, quantity=None, context=None):
        return self._reship_refund_line(cr, uid, ids, line_ids, type="reship", context=context)

    def reship_lines(self, cr, uid, ids, context=None):
        return self._reship_refund_lines(cr, uid, ids, type="reship", context=context)

    def cancel_refund_lines(self, cr, uid, ids, context=None):
        return self._cancel_reship_refund_lines(cr, uid, ids, type="refund", context=context)

    def cancel_reship_lines(self, cr, uid, ids, context=None):
        return self._cancel_reship_refund_lines(cr, uid, ids, type="reship", context=context)

    def complete(self, cr, uid, ids, context=None):
        if context is None:
            context = {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        data = self.browse(cr, uid, wiz_id, context=context)
        error = None
        if data.refund_lines and not data.sale_order_id.invoice_ids:
            error = 'Cannot issue a refund on a sale order without an invoice.'

        if data.net_refund < 0:
            error = 'Total cost of new items exceeds amount being refunded!'

        if error:
            self.write(cr, uid, wiz_id, {'error_message': error})
            return {
                'name': _("Reship/Refund"),
                'view_mode': 'form',
                'view_type': 'form',
                'res_id': wiz_id,
                'res_model': 'reship.wizard',
                'type': 'ir.actions.act_window',
                'nodestroy': True,
                'target': 'new',
            }

        sale_lines = []
        sale_pool = self.pool.get('sale.order')
        so_line_pool = self.pool.get("sale.order.line")

        for line in data.reship_lines:
            sale_lines.append(so_line_pool.copy_data(cr, uid, line.sale_line_id.id, default={
                'product_uos_qty': line.quantity or line.sale_line_id.product_uos_qty,
                'product_uom_qty': line.quantity or line.sale_line_id.product_uom_qty,
                'discount': 100.0
            }))

        new_line_pool = self.pool.get("reship.wizard.line.new")
        new_line_columns = new_line_pool._all_columns.keys()
        so_line_columns = self.pool.get("sale.order.line")._all_columns.keys()
        extra_columns = [c for c in new_line_columns if c not in so_line_columns]

        for line in data.new_order_lines:
            sale_line = new_line_pool.copy_data(cr, uid, line.id)
            for column in extra_columns:
                if column in sale_line:
                    del sale_line[column]

            sale_lines.append(sale_line)

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


    def _reship_refund_line(self, cr, uid, ids, line_ids, type="reship", context=None):
        if not ids:
            return {}

        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)

        if not isinstance(line_ids, list):
            line_ids = [line_ids]

        original_pool = self.pool.get('reship.wizard.line.original')
        original_pool.unlink(cr, uid, original_pool.search(cr, uid, [('sale_line_id', 'in', line_ids)]))

        opposing = 'refund' if type == 'reship' else 'reship'
        opposing_line_ids = self.pool.get("reship.wizard.line.%s" % opposing).search(
            cr, uid, [('wizard_id', '=', wiz.id), ('sale_line_id', 'in', line_ids)])

        self.write(cr, uid, wiz.id, {
            'new_order_lines': [(3, line_id) for line_id in line_ids],
            ('%s_lines' % opposing): [(3, l) for l in opposing_line_ids],
            ('%s_lines' % type): [
                (0, 0, {"sale_line_id": line.id, "quantity": line.product_uom_qty})
                for line in self.pool.get("sale.order.line").browse(cr, uid, line_ids, context=context)]
        }, context=context)


    def _reship_refund_lines(self, cr, uid, ids, type="reship", context=None):
        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)
        func = self.reship_line if type == "reship" else self.refund_line
        func(cr, uid, wiz_id, [l.sale_line_id.id for l in wiz.original_lines if l.selected], context=context)

        return {
            'name': _("Reship/Refund"),
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': wiz_id,
            'res_model': 'reship.wizard',
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'new',
        }


    def _cancel_reship_refund_lines(self, cr, uid, ids, type="reship", context=None):
        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        wiz = self.browse(cr, uid, wiz_id, context=context)
        restore_lines = wiz.reship_lines if type == "reship" else wiz.refund_lines
        self.write(cr, uid, wiz_id, {
            ('%s_lines' % type): [(3, l.id) for l in restore_lines if l.selected],
            'original_lines': [
                (0, 0, {"sale_line_id": l.sale_line_id.id}) for l in restore_lines if l.selected
            ]
        })

        return {
            'name': _("Reship/Refund"),
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': wiz_id,
            'res_model': 'reship.wizard',
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'new',
        }

wiz_reship()