# This file is part of ASPerience modules.  
# The COPYRIGHT file at the top level of this repository contains the full copyright notices and license terms.
from trytond.model import ModelSQL, ModelView, DictSchemaMixin, fields
from trytond.pool import PoolMeta
from trytond.pyson import Eval

__all__ = ['Template']

class Template(metaclass=PoolMeta):
    __name__ = 'product.template'
    contract = fields.Boolean('Contract', states={
            'readonly': ~Eval('active', True),
            'invisible': Eval('type', '') != 'service',
            }, depends=['active', 'type'])
    
    @classmethod
    def default_contract(cls):
        return False