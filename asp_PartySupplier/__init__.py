# This file is part of ASPerPGI for Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import party
from . import purchase

def register():
    Pool.register(
        purchase.FilterParty,
        party.Party,
        module='asp_PartySupplier', type_='model')
    Pool.register(
        party.OpenSuppliers,
        module='asp_PartySupplier', type_='wizard')
