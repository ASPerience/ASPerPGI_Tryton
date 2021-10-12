# The COPYRIGHT file at the top level of this repository contains the full copyright notices and license terms

from trytond.pool import Pool
#from . import template
from . import product_contract

def register():
    Pool.register(
#        template.Template,
        product_contract.ContractAttribute,
        product_contract.Contract,
        module='contract', type_='model')
