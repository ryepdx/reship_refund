from copy import copy
from openerp import SUPERUSER_ID
from openerp.osv import fields, osv, orm
import openerp.addons.decimal_precision as dp

class account_invoice(osv.osv):
    _inherit = "account.invoice"

    def _refund_cleanup_lines(self, cr, uid, lines, context=None):
        if context and 'refund_lines' in context:
            lines = [line for line in lines if line.id in context['refund_lines']]
        return super(account_invoice, self)._refund_cleanup_lines(cr, uid, lines, context=context)

    def _prepare_refund(self, cr, uid, invoice, **kwargs):
        data = super(account_invoice, self)._prepare_refund(cr, uid, invoice, **kwargs)
        context = kwargs.get("context", {})

        data['invoice_line'] = data.get('invoice_line', [])
        if 'refund_total' in context and data['invoice_line']:
            for x, y, line in data['invoice_line']:
                line['price_unit'] = 0

            new_line = copy(data['invoice_line'][0][2])
            new_line.update({
                'name': "Refund",
                'product_id': None,
                'quantity': 1,
                'price_unit': context['refund_total']
            })
            data['invoice_line'].append((0, 0, new_line))

        return data