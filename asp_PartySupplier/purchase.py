# This file is part of ASPerPGI for Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.model import ModelView, ModelSQL, fields
from trytond.pool import Pool,PoolMeta
from trytond.pyson import Eval



class FilterParty(metaclass=PoolMeta):
    "Party filter"

    __name__ = 'purchase.purchase'

    @classmethod
    def __setup__(cls):
        super(FilterParty, cls).__setup__()

        cls.party.domain = [('supplier', '=', True)]
