import time
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT
from openerp.osv import orm, osv, fields
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

    def _amount_line(self, cr, uid, ids, field_name, arg, context=None):
        tax_obj = self.pool.get('account.tax')
        cur_obj = self.pool.get('res.currency')
        res = {}
        if context is None:
            context = {}
        for line in self.browse(cr, uid, ids, context=context):
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = tax_obj.compute_all(cr, uid, line.tax_id, price, line.product_uom_qty, line.product_id, line.order_id.partner_id)
            cur = line.order_id.pricelist_id.currency_id
            res[line.id] = cur_obj.round(cr, uid, cur, taxes['total'])
        return res

    def _get_uom_id(self, cr, uid, *args):
        try:
            proxy = self.pool.get('ir.model.data')
            result = proxy.get_object_reference(cr, uid, 'product', 'product_uom_unit')
            return result[1]
        except Exception, ex:
            return False

    def _fnct_line_invoiced(self, cr, uid, ids, field_name, args, context=None):
        res = dict.fromkeys(ids, False)
        for this in self.browse(cr, uid, ids, context=context):
            res[this.id] = this.invoice_lines and \
                all(iline.invoice_id.state != 'cancel' for iline in this.invoice_lines)
        return res

    def _order_lines_from_invoice(self, cr, uid, ids, context=None):
        # direct access to the m2m table is the less convoluted way to achieve this (and is ok ACL-wise)
        cr.execute("""SELECT DISTINCT sol.id FROM sale_order_invoice_rel rel JOIN
                                                  sale_order_line sol ON (sol.order_id = rel.order_id)
                                    WHERE rel.invoice_id = ANY(%s)""", (list(ids),))
        return [i[0] for i in cr.fetchall()]

    _columns = {
        'order_id': fields.related('wizard_id', 'sale_order_id', type="many2one",
                                   relation="sale.order", string="Sale Order", store=False, readonly=True),
        'wizard_id': fields.many2one('reship.wizard', 'Wizard', readonly=True),
        'name': fields.text('Description', required=True, readonly=True, states={'draft': [('readonly', False)]}),
        'sequence': fields.integer('Sequence', help="Gives the sequence order when displaying a list of sales order lines."),
        'product_id': fields.many2one('product.product', 'Product', domain=[('sale_ok', '=', True)], change_default=True),
        'invoice_lines': fields.many2many('account.invoice.line', 'sale_order_line_invoice_rel', 'order_line_id', 'invoice_id', 'Invoice Lines', readonly=True),
        'invoiced': fields.function(_fnct_line_invoiced, string='Invoiced', type='boolean',
            store={
                'account.invoice': (_order_lines_from_invoice, ['state'], 10),
                'sale.order.line': (lambda self,cr,uid,ids,ctx=None: ids, ['invoice_lines'], 10)}),
        'price_unit': fields.float('Unit Price', required=True, digits_compute= dp.get_precision('Product Price'), readonly=True, states={'draft': [('readonly', False)]}),
        'type': fields.selection([('make_to_stock', 'from stock'), ('make_to_order', 'on order')], 'Procurement Method', required=True, readonly=True, states={'draft': [('readonly', False)]},
         help="From stock: When needed, the product is taken from the stock or we wait for replenishment.\nOn order: When needed, the product is purchased or produced."),
        'price_subtotal': fields.function(_amount_line, string='Subtotal', digits_compute= dp.get_precision('Account')),
        'tax_id': fields.many2many('account.tax', 'sale_order_tax', 'order_line_id', 'tax_id', 'Taxes', readonly=True, states={'draft': [('readonly', False)]}),
        'address_allotment_id': fields.many2one('res.partner', 'Allotment Partner',help="A partner to whom the particular product needs to be allotted."),
        'product_uom_qty': fields.float('Quantity', digits_compute= dp.get_precision('Product UoS'), required=True, readonly=True, states={'draft': [('readonly', False)]}),
        'product_uom': fields.many2one('product.uom', 'Unit of Measure ', required=True, readonly=True, states={'draft': [('readonly', False)]}),
        'product_uos_qty': fields.float('Quantity (UoS)' ,digits_compute= dp.get_precision('Product UoS'), readonly=True, states={'draft': [('readonly', False)]}),
        'product_uos': fields.many2one('product.uom', 'Product UoS'),
        'discount': fields.float('Discount (%)', digits_compute= dp.get_precision('Discount'), readonly=True, states={'draft': [('readonly', False)]}),
        'th_weight': fields.float('Weight', readonly=True, states={'draft': [('readonly', False)]}),
        'state': fields.selection([('cancel', 'Cancelled'),('draft', 'Draft'),('confirmed', 'Confirmed'),('exception', 'Exception'),('done', 'Done')], 'Status', required=True, readonly=True,
                help='* The \'Draft\' status is set when the related sales order in draft status. \
                    \n* The \'Confirmed\' status is set when the related sales order is confirmed. \
                    \n* The \'Exception\' status is set when the related sales order is set as exception. \
                    \n* The \'Done\' status is set when the sales order line has been picked. \
                    \n* The \'Cancelled\' status is set when a user cancel the sales order related.'),
        'order_partner_id': fields.related('order_id', 'partner_id', type='many2one', relation='res.partner', store=True, string='Customer'),
        'salesman_id':fields.related('order_id', 'user_id', type='many2one', relation='res.users', store=True, string='Salesperson'),
        'company_id': fields.related('order_id', 'company_id', type='many2one', relation='res.company', string='Company', store=True, readonly=True),
    }
    _defaults = {
        'product_uom' : _get_uom_id,
        'discount': 0.0,
        'product_uom_qty': 1,
        'product_uos_qty': 1,
        'sequence': 10,
        'state': 'draft',
        'type': 'make_to_stock',
        'price_unit': 0.0,
    }

    def product_id_change(self, cr, uid, ids, pricelist, product, qty=0,
            uom=False, qty_uos=0, uos=False, name='', partner_id=False,
            lang=False, update_tax=True, date_order=False, packaging=False, fiscal_position=False, flag=False, context=None):
        context = context or {}
        lang = lang or context.get('lang',False)
        if not partner_id:
            raise osv.except_osv(_('No Customer Defined!'), _('Before choosing a product,\n select a customer in the sales form.'))
        warning = {}
        product_uom_obj = self.pool.get('product.uom')
        partner_obj = self.pool.get('res.partner')
        product_obj = self.pool.get('product.product')
        context = {'lang': lang, 'partner_id': partner_id}
        if partner_id:
            lang = partner_obj.browse(cr, uid, partner_id).lang
        context_partner = {'lang': lang, 'partner_id': partner_id}

        if not product:
            return {'value': {'th_weight': 0,
                'product_uos_qty': qty}, 'domain': {'product_uom': [],
                   'product_uos': []}}
        if not date_order:
            date_order = time.strftime(DEFAULT_SERVER_DATE_FORMAT)

        result = {}
        warning_msgs = ''
        product_obj = product_obj.browse(cr, uid, product, context=context_partner)

        uom2 = False
        if uom:
            uom2 = product_uom_obj.browse(cr, uid, uom)
            if product_obj.uom_id.category_id.id != uom2.category_id.id:
                uom = False
        if uos:
            if product_obj.uos_id:
                uos2 = product_uom_obj.browse(cr, uid, uos)
                if product_obj.uos_id.category_id.id != uos2.category_id.id:
                    uos = False
            else:
                uos = False
        fpos = fiscal_position and self.pool.get('account.fiscal.position').browse(cr, uid, fiscal_position) or False
        if update_tax: #The quantity only have changed
            result['tax_id'] = self.pool.get('account.fiscal.position').map_tax(cr, uid, fpos, product_obj.taxes_id)

        if not flag:
            result['name'] = self.pool.get('product.product').name_get(cr, uid, [product_obj.id], context=context_partner)[0][1]
            if product_obj.description_sale:
                result['name'] += '\n'+product_obj.description_sale
        domain = {}
        if (not uom) and (not uos):
            result['product_uom'] = product_obj.uom_id.id
            if product_obj.uos_id:
                result['product_uos'] = product_obj.uos_id.id
                result['product_uos_qty'] = qty * product_obj.uos_coeff
                uos_category_id = product_obj.uos_id.category_id.id
            else:
                result['product_uos'] = False
                result['product_uos_qty'] = qty
                uos_category_id = False
            result['th_weight'] = qty * product_obj.weight
            domain = {'product_uom':
                        [('category_id', '=', product_obj.uom_id.category_id.id)],
                        'product_uos':
                        [('category_id', '=', uos_category_id)]}
        elif uos and not uom: # only happens if uom is False
            result['product_uom'] = product_obj.uom_id and product_obj.uom_id.id
            result['product_uom_qty'] = qty_uos / product_obj.uos_coeff
            result['th_weight'] = result['product_uom_qty'] * product_obj.weight
        elif uom: # whether uos is set or not
            default_uom = product_obj.uom_id and product_obj.uom_id.id
            q = product_uom_obj._compute_qty(cr, uid, uom, qty, default_uom)
            if product_obj.uos_id:
                result['product_uos'] = product_obj.uos_id.id
                result['product_uos_qty'] = qty * product_obj.uos_coeff
            else:
                result['product_uos'] = False
                result['product_uos_qty'] = qty
            result['th_weight'] = q * product_obj.weight        # Round the quantity up

        if not uom2:
            uom2 = product_obj.uom_id
        # get unit price

        if not pricelist:
            warn_msg = _('You have to select a pricelist or a customer in the sales form !\n'
                    'Please set one before choosing a product.')
            warning_msgs += _("No Pricelist ! : ") + warn_msg +"\n\n"
        else:
            price = self.pool.get('product.pricelist').price_get(cr, uid, [pricelist],
                    product, qty or 1.0, partner_id, {
                        'uom': uom or result.get('product_uom'),
                        'date': date_order,
                        })[pricelist]
            if price is False:
                warn_msg = _("Cannot find a pricelist line matching this product and quantity.\n"
                        "You have to change either the product, the quantity or the pricelist.")

                warning_msgs += _("No valid pricelist line found ! :") + warn_msg +"\n\n"
            else:
                result.update({'price_unit': price})
        if warning_msgs:
            warning = {
                       'title': _('Configuration Error!'),
                       'message' : warning_msgs
                    }
        return {'value': result, 'domain': domain, 'warning': warning}

    def product_uom_change(self, cursor, user, ids, pricelist, product, qty=0,
            uom=False, qty_uos=0, uos=False, name='', partner_id=False,
            lang=False, update_tax=True, date_order=False, context=None):
        context = context or {}
        lang = lang or ('lang' in context and context['lang'])
        if not uom:
            return {'value': {'price_unit': 0.0, 'product_uom' : uom or False}}
        return self.product_id_change(cursor, user, ids, pricelist, product,
                qty=qty, uom=uom, qty_uos=qty_uos, uos=uos, name=name,
                partner_id=partner_id, lang=lang, update_tax=update_tax,
                date_order=date_order, context=context)


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

    def select_all_original(self, cr, uid, ids, context=None):
        return self._select_all(cr, uid, ids, type="original", context=context)

    def select_all_reship(self, cr, uid, ids, context=None):
        return self._select_all(cr, uid, ids, type="reship", context=context)

    def select_all_refund(self, cr, uid, ids, context=None):
        return self._select_all(cr, uid, ids, type="refund", context=context)

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

    def _select_all(self, cr, uid, ids, type="reship", context=None):
        wiz_id = ids
        if isinstance(ids, list):
            wiz_id = ids[0]

        pool = self.pool.get("reship.wizard.line.%s" % type)
        pool.write(cr, uid, pool.search(cr, uid, [('wizard_id', '=', wiz_id)]), {"selected": True})

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