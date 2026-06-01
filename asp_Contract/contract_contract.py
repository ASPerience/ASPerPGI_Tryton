# This file is part of ASPerience modules.
# The COPYRIGHT file at the top level of this repository contains the full copyright notices and license terms.
from typing import Sequence
import logging
from trytond.model import Workflow, ModelView, ModelSQL,fields,sequence_ordered
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If
from trytond.modules.company.model import CompanyMultiValueMixin
from trytond.modules.product.ir import price_decimal
from decimal import Decimal
from trytond.modules.currency.fields import Monetary
from trytond.modules.asp_Contract.tools import Tools
import datetime as dt
import calendar
from dateutil.relativedelta import relativedelta

price_digits = (16, price_decimal)


class SaleProductContract(ModelSQL):
    """ Sale - Contract Relation """
    __name__  = 'sale.sale-contract.contract'
    _table = 'sale_contract_contract_rel'

    sale = fields.Many2One('sale.sale', 'sale', required=True, ondelete='CASCADE')
    contract = fields.Many2One('contract.contract', 'contract', ondelete='CASCADE')



class Sale(metaclass=PoolMeta):
    """ Ajout de contrat à la vue Vente """
    __name__= 'sale.sale'

    contract = fields.Many2Many('sale.sale-contract.contract', 'sale', 'contract', "Contrat")



class ContractContract(Workflow, ModelSQL, ModelView, CompanyMultiValueMixin):
    'Sale contract'
    __name__ = 'contract.contract'

    read_only = { 'readonly': (Eval('state') != 'draft') }

    partner = fields.Many2One('party.party', 'Partenaire',
                required=True,
                # states = read_only, depends=['state'],
                domain = [('customer', '=', True)]
            )


    reference = fields.Char('Référence contrat')

    email = fields.Many2One('party.contact_mechanism', "E-mail", required=True,
        domain = [
            ('party', '=', Eval('partner')),
            ('type', '=', 'email')
        ])

    contact_address = fields.Many2One('party.address', 'Adresse de contact',
                        domain = [
                            ('party', '=', Eval('partner')),
                        ]
                    )
    invoice_address = fields.Many2One('party.address', 'Adresse de facturation',
                        domain = [
                            ('invoice', '=', True),
                            ('party', '=', Eval('partner')),
                        ],
                    required=True )

    contract = fields.Many2One('product.contract', 'Contrat', required=True)
    begin_date = fields.Date('Date de début')
    end_date = fields.Function(fields.Date('Date de fin prévue'), 'on_change_with_end_date')
    closure_date = fields.Date('Fermeture du contrat',
                    states={
                        'readonly': Eval('closure') == 'true'
                    }
                )
    closure = fields.Selection(
                [
                    ('true', 'true'),
                    ('false', 'false')
                ],
                'vérifier la date de cloture',
                # states={
                #     'required': (
                #         (Eval('closure_date') != '')
                #     ),
                # },
                # depends=['closure_date']
            )

    state = fields.Selection(
            [
                ('generated', 'Créé'),
                ('quote', 'Devis'),
                ('draft', 'Brouillon'),
                ('started', 'En cours'),
                ('stopped','En pause'),
                ('closed', 'Cloturé'),
                ('canceled', 'Annulé')
            ], 'State', readonly=True
        )

    initial_price_indicator = fields.Float('Indicateur de prix initial', digits=(16, 2), required=True)
    actual_price_indicator = fields.Float('Indicateur du prix actuel', digits=(16, 2))

    forecast_duration_months = fields.Function(
                                    fields.Integer('Durée Prévisionnelle en mois'),
                                    'on_change_with_forecast_duration_months'
                                )
    initial_duration_months = fields.Integer('Durée initiale en mois', required=True)

    renewal_duration_months = fields.Integer('Durée de renouvellement en mois', required=True)
    delay_notice_months = fields.Integer('Préavis de fin de contrat', required=True)
    billing_time_in_months = fields.Integer("Délai de facturation en mois", required=True)
    payment_term = fields.Many2One('account.invoice.payment_term', 'Condition de payement',
                    states={'readonly': Eval('state') != 'draft'},
                    required=True
                )


    contract_attributes = fields.One2Many('contract.contract.attribute', 'contract',
                            "Liste d'attributs"
                        )

    contract_invoice = fields.One2Many('contract.contract.invoice', 'contract',
                            "Liste de factures"
                        )


    billing_in_period_start = fields.Boolean('Facturation en début de période')


    # ---- Sont utilisées dans la vue Vente
    begin = fields.Function(fields.Char('Début de contrat'), 'set_begin')
    @fields.depends('begin_date')
    def set_begin(self, name=None):
        return self.begin_date.strftime('%d/%m/%Y')

    end = fields.Function(fields.Char('Fin de contrat'), 'set_end')
    @fields.depends('end_date')
    def set_end(self, name=None):
        return self.end_date.strftime('%d/%m/%Y')
    # ---- sale_contract_tree.xml > sale_form.xml

    @classmethod
    def default_closure(cls):
        return 'false'

    @classmethod
    def default_state(cls):
        return 'draft'


    @classmethod
    def default_begin_date(cls):
        return (dt.date.today() + relativedelta(months=1)).replace(day=1)


    @fields.depends('contract')
    def on_change_with_forecast_duration_months(self, name=None):
        if self.contract:
            return self.contract.duration_months

    @fields.depends('begin_date', 'initial_duration_months', 'renewal_duration_months')
    def on_change_with_end_date(self, name=None):
        today = dt.date.today()
        if self.initial_duration_months and self.begin_date:
            end_month = self.begin_date + relativedelta(months=self.initial_duration_months-1)
            last_day = calendar.monthrange(end_month.year, end_month.month)[1]
            end_date = end_month.replace(day=last_day)

            while end_date.strftime('%y%m%d') < today.strftime('%y%m%d'):
                end_date = end_date + relativedelta(months=self.renewal_duration_months)

            return end_date




    @classmethod
    def __setup__(cls):
        super(ContractContract, cls).__setup__()
        cls._transitions |= set((
            ('draft', 'generated'),
            ('generated', 'draft'),
            ('generated','quote'),
            ('generated','canceled'),
            ('quote', 'started'),
            ('quote', 'draft'),
            ('quote', 'canceled'),
            ('started', 'stopped'),
            ('started', 'canceled'),
            ('stopped', 'started'),
            ('stopped', 'canceled'),
            ('quote', 'canceled'),
            ('started', 'closed'),
            ('stopped', 'closed'),
            ('canceled', 'draft')
        ))


        cls._buttons.update({
            'draft': {
                'invisible': Eval('state').in_(['stopped', 'started', 'draft', 'closed']), #'canceled'
                'depends': ['state']
            },
            'generated': {
                'invisible': Eval('state').in_(['generated', 'quote', 'started', 'stopped', 'canceled', 'closed']),
                'depends': ['state']
            },
            'quote': {
                'invisible': Eval('state').in_(['draft', 'quote', 'started', 'stopped', 'canceled', 'closed']),
                'depends': ['state']
            },
            'started': {
                'invisible': Eval('state').in_(['generated', 'started', 'canceled', 'draft', 'closed']),
                'depends': ['state']
            },
            'stopped': {
                'invisible': Eval('state').in_(['stopped', 'draft', 'canceled', 'quote', 'generated', 'closed']),
                'depends': ['state']
            },
            'canceled': {
                'invisible': Eval('state').in_(['canceled', 'draft', 'closed']),
                'depends': ['state']
            },
            'recalculate': {
                'invisible': Eval('state').in_(['canceled', 'draft', 'closed']),
                'depends': ['state']
            },
            'closure_check': {
                'readonly': ~Eval('closure_date'),
                'invisible': Eval('closure').in_(['true']),
                'depends': ['closure_date', 'closure']
            },
            'cancel_closure': {
                'invisible': Eval('closure').in_(['false']),
                'depends': ['closure']
            }
        })


    @classmethod
    @ModelView.button
    @Workflow.transition('generated')
    def generated(cls, contract_sale):
        if contract_sale[0].actual_price_indicator:
            last_indicator = float(contract_sale[0].actual_price_indicator)
        else: last_indicator = contract_sale[0].initial_price_indicator

        coeff = last_indicator/contract_sale[0].initial_price_indicator

        if coeff > 1:
            rate = round(-(coeff-1)*100, 2)
        else:
            rate = round(100 - (coeff * 100), 2)

        if not contract_sale[0].actual_price_indicator:
            contract_sale[0].actual_price_indicator = float(contract_sale[0].initial_price_indicator)

        last_indicator = float(contract_sale[0].actual_price_indicator)

        ref_prefix = "CRTCT"
        contract_sale[0].reference = f"CRTCT{contract_sale[0].id:08d}"
        contract_sale[0].save()

        """Création des attributs du contract"""
        ProductAttribute = Pool().get('product.contract.attribute')
        product_attributes = ProductAttribute.search([('contract','=',contract_sale[0].contract)])
        ContractAttribute = Pool().get('contract.contract.attribute')

        exist_products = []
        for attribute in contract_sale[0].contract_attributes:
            exist_products.append(attribute.product.id)

        for attribute in product_attributes:
            if not attribute.product.id in exist_products:
                contract_attribute = ContractAttribute()
                contract_attribute.contract     = contract_sale[0]
                contract_attribute.attribute    = attribute.name
                contract_attribute.base_price   = attribute.list_price
                contract_attribute.uos          = attribute.uos
                contract_attribute.product      = attribute.product

            else:
                contract_attribute, = ContractAttribute.search([
                                        ('contract', '=', contract_sale[0]),
                                        ('product', '=', attribute.product)
                                    ])


            unit_price = contract_attribute.base_price
            contract_attribute.discount = rate
            contract_attribute.save()

        return True

    @classmethod
    @ModelView.button
    @Workflow.transition('quote')
    def quote(cls, contract_sale):
        sale = Tools.create_sale(contract_sale)
        Tools.create_sale_contract(contract_sale, sale)
        Tools.create_sale_line_and_tax(contract_sale, sale)

        return True


    @classmethod
    @ModelView.button
    @Workflow.transition('started')
    def started(cls, contract_sale, current_date=dt.date.today()):
        """ Dans cette état les facturations sont générées périodiquement """
        Tools.create_contract_invoice_line(contract_sale, current_date=current_date)
        if contract_sale[0].billing_in_period_start:
            ContractContractInvoice.create_invoice(contract_sale[0].contract_invoice)
            begin_date = current_date.replace(day=1)
            begin_next_period = begin_date + relativedelta(months=contract_sale[0].billing_time_in_months)
            Tools.create_contract_invoice_line(contract_sale, begin_next_period, current_date=current_date)
        return True


    @classmethod
    @ModelView.button
    @Workflow.transition('stopped')
    def stopped(cls, contract_sale):
        """ Dans cette état on arrête la génération périodique des factures """
        return True

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, contract_sale):
        return True


    @classmethod
    @ModelView.button
    @Workflow.transition('canceled')
    def canceled(cls, contract_sale):
        return True


    @classmethod
    @ModelView.button
    def closure_check(cls, contract_sale):
        contract_sale[0].closure = True

        def date_calculate(date, multiplier):
            return date + relativedelta(months=multiplier)

        closure_choice = contract_sale[0].closure_date
        InvoiceLine = Pool().get('contract.contract.invoice')
        billing_time_in_months = contract_sale[0].billing_time_in_months

        if closure_choice > contract_sale[0].end_date:
            multiplier = 1
            while closure_choice.strftime('%y-%m') > date_calculate(
                                                        contract_sale[0].end_date,
                                                        billing_time_in_months*multiplier
                                                    ).strftime('%y-%m'):
                multiplier += 1

            closure_date = date_calculate(contract_sale[0].end_date,billing_time_in_months*multiplier)
            last_day = calendar.monthrange(closure_date.year, closure_date.month)[1]
            closure_date = date_calculate(
                            contract_sale[0].end_date,billing_time_in_months*multiplier
                        ).replace(day=last_day)
        else:
            multiplier = 0
            invoice_lines = InvoiceLine.search(
                                [('contract', '=', contract_sale[0].id)],
                                order=[('number', 'DESC')]
                            )
            if invoice_lines:
                end_period = invoice_lines[0].period.split('=> ')[1]
                ref_date = dt.date(
                                2000+int(end_period.split('-')[2]),
                                int(end_period.split('-')[1]),
                                int(end_period.split('-')[0])
                            )

                if closure_choice.strftime('%y-%m') < date_calculate(
                                                            ref_date,
                                                            billing_time_in_months*multiplier
                                                        ).strftime('%y-%m'):
                    closure_date = date_calculate(ref_date,billing_time_in_months*multiplier)
                else:
                    while closure_choice.strftime('%y-%m') > date_calculate(
                                                                ref_date,
                                                                billing_time_in_months*multiplier
                                                            ).strftime('%y-%m'):
                        multiplier += 1

                    closure_date = date_calculate(ref_date,billing_time_in_months*multiplier)

                last_day = calendar.monthrange(closure_date.year, closure_date.month)[1]
                closure_date = date_calculate(
                                ref_date,billing_time_in_months*multiplier
                            ).replace(day=last_day)
            else:
                closure_date = contract_sale[0].end_date

        contract_sale[0].closure_date = closure_date
        contract_sale[0].closure = 'true'
        contract_sale[0].save()

        return True

    @classmethod
    @ModelView.button
    def cancel_closure(cls, contract_sale):
        contract_sale[0].closure_date = None
        contract_sale[0].closure = 'false'
        contract_sale[0].save()

    @classmethod
    @ModelView.button
    def recalculate(cls, contract_sale):
        """ Recalcule de la valeur prix actuel """
        if contract_sale[0].actual_price_indicator:
            last_indicator = float(contract_sale[0].actual_price_indicator)
        else: last_indicator = contract_sale[0].initial_price_indicator

        coeff = last_indicator/contract_sale[0].initial_price_indicator

        if coeff > 1: rate = round(-(coeff-1)*100, 2)
        else: rate = round(100 - (coeff * 100), 2)

        ContractAttribute = Pool().get('contract.contract.attribute')
        for attribute in contract_sale[0].contract_attributes:
            contract_attribute, = ContractAttribute.search([
                                    ('contract', '=', contract_sale[0]),
                                    ('product', '=', attribute.product)
                                ])
            if contract_attribute:
                unit_price = contract_attribute.base_price

                contract_attribute.discount = rate
                contract_attribute.actual_price = unit_price - (unit_price*rate/100)

                contract_attribute.save()


        """
            Modification du détail des lignes de facture en cours de traitement
            Modification de la facture si elle existe
        """
        InvoiceLine = Pool().get('contract.contract.invoice')
        invoice_line, = InvoiceLine.search([('contract', '=', contract_sale[0]), ('state', '=', 'in_progress')])

        attributes = [attribute for attribute in contract_sale[0].contract_attributes if attribute.changed]

        InvoiceLineDetail = Pool().get('contract.contract.invoice.detail')
        for attribute in attributes or []:
            attribute.changed = False
            attribute.save()

            detail = InvoiceLineDetail.search([('contract_invoice_line', '=', invoice_line), ('product', '=', attribute.product)])
            if detail:
                detail, = detail
                detail.quantity = attribute.quantity
                detail.price = attribute.actual_price
                detail.save()
            else:
                detail = InvoiceLineDetail(
                    product = attribute.product,
                    price = attribute.actual_price,
                    quantity = attribute.quantity,
                    contract_invoice_line = invoice_line,
                    attribute = attribute.attribute,
                    uos = attribute.uos
                ).save()

        if invoice_line.invoice:
            InvoiceLine.create_invoice([invoice_line])

        return True





class ContractContractAttribute(sequence_ordered(), ModelSQL, ModelView, CompanyMultiValueMixin):
    """ Attribute for contract """
    __name__ = 'contract.contract.attribute'

    contract     = fields.Many2One('contract.contract', "Contract", required=True, ondelete='CASCADE')
    attribute    = fields.Char('Attribut')
    quantity     = fields.Float('Quantité')
    uos          = fields.Many2One('product.uom', 'Unité')
    base_price   = fields.Float('Prix de base')
    discount     = fields.Float('Remise (%)')
    actual_price = fields.Function(fields.Float('Prix actuel', readonly=True), 'on_change_with_actual_price')
    changed      = fields.Boolean('changed')

    product      = fields.Many2One('product.product', "Product")


    @classmethod
    def default_changed(cls):
        return True

    @classmethod
    def default_quantity(cls):
        return 0


    @classmethod
    def default_discount(cls):
        return 0


    @classmethod
    def write(cls, *args):
        args = tuple({**element, "changed": True}
            if isinstance(element, dict) else element for element in args
        )
        super().write(*args)




    @fields.depends('base_price', 'discount')
    def on_change_with_actual_price(self, name=None):
        if self.base_price:
            return self.base_price - (self.base_price*self.discount/100)


    @fields.depends('product', 'attribute', 'base_price', 'uos', 'contract',
                    '_parent_contract.actual_price_indicator', '_parent_contract.initial_price_indicator',
                    methods=['on_change_with_actual_price'])
    def on_change_product(self):
        if not self.product: return
        if self.contract.actual_price_indicator:
            last_indicator = float(self.contract.actual_price_indicator)
        else:
            last_indicator = self.contract.initial_price_indicator

        coeff = last_indicator/self.contract.initial_price_indicator

        if coeff > 1: rate = round(-(coeff-1)*100, 2)
        else:         rate = round(100 - (coeff * 100), 2)
        self.discount = rate
        self.attribute = self.product.name
        self.base_price = self.product.list_price
        self.actual_price = self.base_price - (self.base_price*rate/100)
        self.uos = self.product.template.default_uom
        self.on_change_with_actual_price()



class ContractContractInvoice(sequence_ordered(), ModelSQL, ModelView, CompanyMultiValueMixin):
    """ Liste de factures du contrat """
    __name__ = "contract.contract.invoice"

    contract        = fields.Many2One('contract.contract', "Contract", ondelete='CASCADE')
    number          = fields.Integer("n°", required=True)
    detail          = fields.One2Many("contract.contract.invoice.detail", "contract_invoice_line","Detail")
    period          = fields.Char("Période", required=True)
    month           = fields.Char("Mois", required=True)
    invoice         = fields.Many2One('account.invoice', 'Facture')
    date_invoicing  = fields.Date("Date de facturation")
    invoice_state   = fields.Function(fields.Char("Statut"), 'on_change_with_invoice_state')
    state = fields.Selection(
            [
                ('in_progress', 'En cours'),
                ('finished', 'Terminé'),
            ], 'State', readonly=True
        )

    @classmethod
    def default_state(cls):
        return 'in_progress'


    @fields.depends('invoice')
    def on_change_with_invoice_state(self, name=None):
        state_list = [
            ('draft', "Brouillon"),
            ('validated', "Validée"),
            ('posted', "Postée"),
            ('paid', "payée"),
            ('cancelled', "Annulée")
        ]

        if self.invoice:
            for state in state_list:
                if self.invoice.state == state[0]:
                    value = state[1]
            return value



    @classmethod
    def __setup__(cls):
        super(ContractContractInvoice, cls).__setup__()

        cls._order.insert(0, ('number', 'DESC'))

        cls._buttons.update({
            'create_invoice': {
                'invisible': ~Eval('invoice_state').in_(['Brouillon', '']),
                'depends': ['invoice_state']
            }
        })

    @classmethod
    @ModelView.button
    def create_invoice(cls, contract_invoice):
        contract = contract_invoice[0].contract

        """ Récupération des lignes de la période. """
        period = contract_invoice[0].period
        InvoiceLine = Pool().get('contract.contract.invoice')
        lines = InvoiceLine.search([('period', '=', period), ('contract', '=', contract)], order=[('number', 'DESC')])

        if not contract_invoice[0].invoice:
            invoice = Tools.create_invoice([contract], contract_invoice, lines)
            Tools.create_invoice_line_and_tax(lines, invoice)
        elif contract_invoice[0].invoice.state == 'draft':
            Invoice = Pool().get('account.invoice')
            invoice, = Invoice.search([('id', '=', contract_invoice[0].invoice)])
            Tools.drop_invoice_line_and_tax(invoice)
            Tools.create_invoice_line_and_tax(lines, invoice)

        return True



class ContractContractInvoiceDetail(ModelSQL, ModelView):
    """ Détail de facturation d'un contrat """

    __name__="contract.contract.invoice.detail"

    contract_invoice_line   = fields.Many2One("contract.contract.invoice", "Ligne de facture")
    attribute               = fields.Char('Attribut')
    product                 = fields.Many2One('product.product', "Produit")
    quantity                = fields.Float("Quantité")
    price                   = fields.Float("Prix")
    uos                     = fields.Many2One('product.uom', 'Unité')
    description             = fields.Text("Description")
