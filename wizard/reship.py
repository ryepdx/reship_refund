from openerp.osv import orm, fields
from openerp.tools.translate import _
from ..sale import sale_order

class wiz_reship(orm.TransientModel):
    _name = 'reship.wizard'
    _columns = {
        'sale_order_id': fields.many2one('sale.order', 'Sale Order'),
        'reason': sale_order._columns['reship_reason'],
        'copy_lines': fields.boolean('Copy all order lines'),
    }

    def _sale_order_id(self, cr, uid, context):
        if context.get('active_model') == 'sale.order' and context.get('active_id'):
            return context.get('active_id')
        return None

    _defaults = {
        'copy_lines': True,
        'sale_order_id': _sale_order_id
    }

    def reship(self, cr, uid, ids, context=None):
        if context is None:
            context = {}

        data = self.browse(cr, uid, ids[0], context=context)
        sale_id = self.pool.get('sale.order').reship(
            cr, uid, data.sale_order_id.id, reason=data.reason, copy_lines=data.copy_lines, context=context)

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

wiz_reship()