# This file is part of ASPerPGI for Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import logging
from trytond.i18n import gettext
from trytond.model import fields
from trytond.pool import PoolMeta,Pool
from trytond.wizard import Wizard, StateAction
from trytond.pyson import PYSONEncoder

class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    supplier = fields.Boolean('Supplier',
        help="Check this box if the party is a supplier.")

class OpenSuppliers(Wizard):
    'Open Suppliers'
    __name__ = 'party_supplier.open_suppliers'
    start_state = 'open_'
    open_ = StateAction('party_supplier.act_party_form')

    def do_open_(self, action):
        pool = Pool()
        Party = pool.get('party.party')
        parties = Party.search(['supplier','=',True])
        action['res_id'] = []
        for party in parties:
            action['res_id'].append(party.id)
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', action['res_id'])])
        return action, {}

    def transition_open_(self):
        return 'end'