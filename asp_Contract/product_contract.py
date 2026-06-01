# This file is part of ASPerience modules.
# The COPYRIGHT file at the top level of this repository contains the full copyright notices and license terms.
from typing import Sequence
import logging
from trytond.model import ModelView, ModelSQL,fields,sequence_ordered
from trytond.pool import Pool
from trytond.pyson import Eval, If
from trytond.modules.company.model import CompanyMultiValueMixin
from trytond.modules.product.ir import price_decimal
price_digits = (16, price_decimal)



class Contract(ModelSQL, ModelView,CompanyMultiValueMixin):
    'Product base for contracts'
    __name__ = 'product.contract'
    code = fields.Char("Code", required=True)
    name = fields.Char(
        "Nom", size=None, required=True, translate=True)
    duration_months = fields.Integer("Durée", required=True, help="Mois")
    contract_attributes = fields.One2Many('product.contract.attribute', 'contract', 'Contract attributes')
    description = fields.Text("Description", translate=True)


    @classmethod
    def default_duration_months(cls):
        return 12




class ContractAttribute(sequence_ordered(),ModelSQL, ModelView,CompanyMultiValueMixin):
    'Attributes base for contracts'
    __name__ = 'product.contract.attribute'
    contract = fields.Many2One('product.contract', "Contrat", required=True, ondelete='CASCADE')
    name = fields.Char('Attribut', size=128, required=True, depends=['product'])
    comment = fields.Text("Commentaire pour ordre de vente", translate=True, depends=['product'])
    uos = fields.Many2One('product.uom', 'Unité de vente',required=True, depends=['product'])

    ### Je ne comprends pas l'utilité de ce champs ###
    calculate = fields.Selection([('plan_before','Facture en début de période'),        # Plan. Invoice on start of period
                                    ('plan_after','Facture en fin de période'),         # Plan. Invoice at the end of period
                                    ('avg','Consommation moyenne en fin de période'),   # Average use at the end of period
                                    ('sum',"Somme d'utilisation en fin de période")],   # Sum of use at the end of period
                            'Calcul de consommation', required=True)           # Consumption calculation

    ### Voir quel est le besoin afin de trouver une solution plus adapté ###
    applicable_type = fields.Selection(
                        [('list_price','Prix listé'), ('code','Code python')],
                        'Prix catalogue ou formule', required=True
                    )
    python_compute = fields.Text("Python Code", states={
            'invisible': Eval('applicable_type', '') != 'code',
            }, depends=['applicable_type'])
    product = fields.Many2One('product.product', "Product", required=True,
                domain=[
                    If(Eval('active'), ('active', '=', True), ()),
                ]
            )
    list_price = fields.Function(
                    fields.Numeric('Prix de vente', digits=price_digits),
                    'on_change_with_list_price'
                )
    cost_price = fields.Function(
                    fields.Numeric("Prix de revient", digits=price_digits),
                    'on_change_with_cost_price'
                )

    @fields.depends('product')
    def on_change_product(self):
        result = {}
        if not self.product:
            return
        self.name = self.product.name
        self.uos = self.product.default_uom
        self.comment = self.product.description

    @fields.depends('uos','product')
    def on_change_with_list_price(self, name=None):
        return self.get_price_uos(self,name or 'list_price')

    @fields.depends('uos','product')
    def on_change_with_cost_price(self, name=None):
        return self.get_price_uos(self,name or 'cost_price')

    @staticmethod
    def get_price_uos(attribute, name):
        pool = Pool()
        Uom = pool.get('product.uom')
        if attribute.product:
            price = getattr(attribute.product, name)
            if attribute.uos and attribute.product.default_uom != attribute.uos:
                return Uom.compute_price(
                    attribute.product.default_uom, price, attribute.uos)
            else:
                return price

    @classmethod
    def default_applicable_type(cls):
        return 'list_price'

    @classmethod
    def default_calculate(cls):
        return 'plan_before'
