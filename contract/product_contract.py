# This file is part of ASPerience modules.  
# The COPYRIGHT file at the top level of this repository contains the full copyright notices and license terms.
from typing import Sequence
from trytond.model import ModelView, ModelSQL,fields,sequence_ordered
from trytond.pyson import Eval
from trytond.modules.company.model import CompanyMultiValueMixin
from trytond.modules.product.ir import price_decimal
price_digits = (16, price_decimal)

class Contract(ModelSQL, ModelView,CompanyMultiValueMixin):
    'Product base for contracts'
    __name__ = 'product.contract'
    code = fields.Char("Code", required=True, select=True)
    name = fields.Char(
        "Name", size=None, required=True, translate=True, select=True)
    duration_months = fields.Integer("Duration", required=True, help="Months")
    contract_attributes = fields.One2Many('product.contract.attribute', 'contract', 'Contract attributes')

    @classmethod
    def default_duration_months(cls):
        return 12

class ContractAttribute(sequence_ordered(),ModelSQL, ModelView):
    'Attributes base for contracts'
    __name__ = 'product.contract.attribute'
    contract = fields.Many2One('product.contract', "Contract", required=True, ondelete='CASCADE')
    name = fields.Char('Attribute ', size=128, required=True)
    comment = fields.Text("Comment for sale order", translate=True)
    uos = fields.Many2One('product.uom', 'Unit of Sale')
    applicable_type = fields.Selection([('list_price','List price'), ('code','Python Code')], 
             'Use of list price or formula', required=True)
    calculate = fields.Selection([('plan_before','Plan. Invoice on start of period'), 
                                    ('plan_after','Plan. Invoice at the end of period'),
                                    ('avg','Average use at the end of period'),
                                    ('sum','Sum of use at the end of period')],
            'Consumption calculation ', required=True)
    python_compute = fields.Text("Python Code", states={
            'invisible': Eval('applicable_type', '') != 'code',
            }, depends=['applicable_type'])
    product = fields.Many2One('product.product', "Product", required=True)
    list_price = fields.Function(fields.Numeric('List Price',
        digits=price_digits), 'get_price_uos')
    cost_price = fields.Function(fields.Numeric(
            "Cost Price", digits=price_digits,
            help="The amount it costs to purchase or make the product, "
            "or carry out the service."),
        'get_price_uos')


    @staticmethod
    def get_price_uos(attributes, name):
        logging
        Uom = Pool().get('product.uom')
        res = {}
        field = name[:-4]
        for attribute in attributes:
            price = getattr(attribute, field)
            if attribute.product.uos != attribute.uos:
                res[attribute.id] = Uom.compute_price(
                    attribute.product.uos, price, attribute.uos)
            else:
                res[attribute.id] = price
        return res
    @classmethod
    def default_applicable_type(cls):
        return 'list_price'
    @classmethod
    def default_calculate(cls):
        return 'plan_before'
