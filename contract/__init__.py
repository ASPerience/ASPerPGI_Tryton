# The COPYRIGHT file at the top level of this repository contains the full copyright notices and license terms

from trytond.pool import Pool
from .product import *
#from .product_contract import *

def register():
    Pool.register(
        UomCategory,
        Uom,
        Category,
        Template,
        Product,
        ProductListPrice,
        ProductCostPriceMethod,  # before ProductCostPrice for migration
        ProductCostPrice,
        TemplateCategory,
        TemplateCategoryAll,
        Configuration,
        ConfigurationDefaultCostPriceMethod,
        module='contract', type_='model')
