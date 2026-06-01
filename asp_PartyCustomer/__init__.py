# This file is part of ASPerPGI for Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import party
from . import sale

def register():
    Pool.register(
        sale.FilterParty,
        party.Party,
        module='asp_PartyCustomer', type_='model')
    Pool.register(
        party.OpenCustomers,
        module='asp_PartyCustomer', type_='wizard')
