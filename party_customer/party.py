# This file is part of ASPerPGI for Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.i18n import gettext
from trytond.model import fields
from trytond.pool import PoolMeta
from trytond.wizard import Wizard, StateAction, StateView, StateTransition, \
    Button

class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    customer = fields.Boolean('Customer',
        help="Check this box if the party is a customer.")

class OpenSupplier(Wizard):
    'Open Suppliers'
    __name__ = 'purchase.open_supplier'
    start_state = 'open_'
    open_ = StateAction('party.act_party_form')

    def do_open_(self, action):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Wizard = pool.get('ir.action.wizard')
        Purchase = pool.get('purchase.purchase')
        cursor = Transaction().connection.cursor()
        purchase = Purchase.__table__()

        cursor.execute(*purchase.select(purchase.party,
                group_by=purchase.party))
        supplier_ids = [line[0] for line in cursor.fetchall()]
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', supplier_ids)])
        wizard = Wizard(ModelData.get_id('purchase', 'act_open_supplier'))
        action['name'] = wizard.name
        return action, {}
