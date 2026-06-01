from trytond.pool import Pool
from decimal import Decimal
import datetime as dt
from dateutil.relativedelta import relativedelta
import calendar


class Tools:

    @classmethod
    def month_list(cls):
        return {
            'Janvier': 1, 'Février': 2, 'Mars': 3, 'Avril': 4, 'Mai': 5, 'Juin': 6, 'Juillet': 7,
            'Août': 8, 'Septembre': 9, 'Octobre': 10, 'Novembre': 11, 'Décembre': 12
        }

    @classmethod
    def month_translate(cls, month):
        months = [
            'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet',
            'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'
        ]
        return months[month-1]

    @classmethod
    def create_contract_invoice_line(cls, contract_sale, begin_period=None, current_date=dt.date.today()):
        line_quantity = contract_sale[0].billing_time_in_months
        nb_line = 0
        if not begin_period:
            first_day = contract_sale[0].begin_date.strftime('%d')
            today = current_date.replace(day=int(first_day))
            if today < contract_sale[0].begin_date:
                start_period = contract_sale[0].begin_date
            else: start_period = today
        else: start_period = begin_period

        """ end_month """
        end_period = start_period + relativedelta(months=line_quantity-1)
        last_day = calendar.monthrange(end_period.year, end_period.month)[1]
        end_period = end_period.replace(day=last_day)
        """ ---------- """

        while nb_line < line_quantity:
            month = start_period + relativedelta(months=nb_line)
            str_month = cls.month_translate(int(month.strftime('%m')))
            year = month.strftime('%Y')

            date = f"{str_month} {year}"

            ContractInvoice = Pool().get('contract.contract.invoice')
            """ calcul number """
            contract_lines = ContractInvoice.search([('contract', '=', contract_sale[0])])
            number = len(contract_lines)+1

            contract_invoice = ContractInvoice()
            period = f"{start_period.strftime('%d-%m-%y')} => {end_period.strftime('%d-%m-%y')}"
            """ check if exist """
            contract_invoice_exist = ContractInvoice.search([
                                        ('month', '=', date),
                                        ('contract', '=', contract_sale[0])
                                    ])

            if not contract_invoice_exist:
                contract_invoice.contract = contract_sale[0]
                contract_invoice.period   = period
                contract_invoice.month    = date
                contract_invoice.number   = number
                contract_invoice.state = 'finished' if contract_sale[0].billing_in_period_start and not begin_period else 'in_progress'

                contract_invoice.save()

                ContractAttribute = Pool().get('contract.contract.attribute')
                contract_attributes = ContractAttribute.search([('contract', '=', contract_sale[0])])

                cls.create_contract_invoice_line_detail(contract_attributes, contract_invoice)

            nb_line += 1

        return contract_invoice

    @classmethod
    def create_contract_invoice_line_detail(cls, contract_attributes, contract_invoice):
        ContractInvoiceDetail = Pool().get('contract.contract.invoice.detail')
        for attribute in contract_attributes:
            invoice_detail = ContractInvoiceDetail()
            invoice_detail.product = attribute.product
            invoice_detail.price = attribute.actual_price
            invoice_detail.quantity = attribute.quantity
            invoice_detail.contract_invoice_line = contract_invoice
            invoice_detail.attribute = attribute.attribute
            invoice_detail.uos = attribute.uos

            invoice_detail.save()


    @classmethod
    def create_invoice(cls, contract_sale, contract_invoice, lines):
        begin_month_str     = contract_invoice[0].period.split(' => ')[0]
        begin_month_date    = dt.datetime.strptime(begin_month_str, "%d-%m-%y").date()
        end_month_str       = contract_invoice[0].period.split(' => ')[1]
        end_month_date      = dt.datetime.strptime(end_month_str, "%d-%m-%y").date()
        period = f"[{contract_invoice[0].period}]"

        """ Génération de facture du contrat pour le mois en cours """
        Invoice = Pool().get('account.invoice')
        invoice = Invoice()

        invoice.party = contract_sale[0].partner
        invoice.account, = Pool().get('account.account').search([('code', '=', '411100')])
        invoice.invoice_address = contract_sale[0].invoice_address
        invoice.type = 'out'
        invoice.journal, = Pool().get('account.journal').search([('code', '=', 'VEN')])
        invoice.currency = 1
        invoice.company = 1
        invoice.description = f"{contract_sale[0].contract.name} {period}"
        invoice.reference = f"{contract_sale[0].reference}-{contract_invoice[0].number:03d}"
        invoice.payment_term = contract_sale[0].payment_term
        invoice.invoice_date = end_month_date if not contract_sale[0].billing_in_period_start else begin_month_date
        invoice.save()


        """ compléter la ligne de facture """
        for line in lines:
            ContractInvoice = Pool().get('contract.contract.invoice')
            contract_invoice, = ContractInvoice.search([
                                    ('id', '=', line)
                                ])

            contract_invoice.invoice = invoice
            contract_invoice.date_invoicing = invoice.invoice_date

            contract_invoice.save()

        return invoice



    @classmethod
    def create_invoice_line_and_tax(cls, lines, invoice):
        ContractAttribute = Pool().get('contract.contract.attribute')
        # contract_attributes = ContractAttribute.search([('contract','=',contract_sale[0])])
        InvoiceLine = Pool().get('account.invoice.line')
        InvoiceLineTax = Pool().get('account.invoice.line-account.tax')
        TaxLine = Pool().get('account.invoice.tax')
        for line in lines:
            tax_list = {}
            for attribute in line.detail:
                if attribute.quantity != 0:
                    invoice_line = InvoiceLine()
                    invoice_line.account = attribute.product.template.account_category.account_revenue
                    invoice_line.invoice = invoice
                    invoice_line.note = f"[{line.month}] {attribute.attribute}"
                    invoice_line.product = attribute.product
                    invoice_line.quantity = attribute.quantity
                    invoice_line.unit = attribute.uos
                    invoice_line.description = attribute.description
                    invoice_line.unit_price = round(Decimal(attribute.price), 2)
                    invoice_line.save()

                    account_tax = attribute.product.account_category

                    while account_tax.parent:
                        account_tax = account_tax.parent

                    tax = InvoiceLineTax()
                    tax.line = invoice_line
                    tax.tax = account_tax.customer_taxes[0]
                    tax.save()

                    if tax.tax.description not in tax_list.keys():
                        tax_list[tax.tax.description] = {
                            'tax': tax.tax,
                            'description': tax.tax.description,
                            'base': invoice_line.unit_price * Decimal(invoice_line.quantity),
                            'account': invoice_line.account
                        }
                    else:
                        tax_list[tax.tax.description]['base'] = tax_list[tax.tax.description]['base'] + invoice_line.unit_price * Decimal(invoice_line.quantity)

            for key, value in tax_list.items():
                tax_line = TaxLine()
                tax_line.invoice = invoice
                tax_line.tax = value['tax']
                tax_line.description = value['description']
                tax_line.base = round(value['base'], 2)
                tax_line.amount = round(value['base'] * value['tax'].rate, 2)
                tax_line.legal_notice = value['tax'].legal_notice
                tax_line.account = value['tax'].invoice_account
                tax_line.manual = False

                tax_line.save()

    @classmethod
    def drop_invoice_line_and_tax(cls, invoice):
        InvoiceLine = Pool().get('account.invoice.line')
        InvoiceLineTax = Pool().get('account.invoice.line-account.tax')
        TaxLine = Pool().get('account.invoice.tax')

        """ Suppression des lignes et taxes de la facture """
        invoice_lines = InvoiceLine.search([('invoice', '=', invoice)])

        for line in invoice_lines:
            line_tax_rels = InvoiceLineTax.search([('line', '=', line)])
            InvoiceLineTax.delete(line_tax_rels)

        tax_lines = TaxLine.search([('invoice', '=', invoice)])
        TaxLine.delete(tax_lines)

        InvoiceLine.delete(invoice_lines)


        # for rel in line_tax_rel:
        #     tax = rel.tax

    @classmethod
    def create_sale(cls, contract_sale):
        Sale = Pool().get('sale.sale')
        sale = Sale()
        sale.party = contract_sale[0].partner
        sale.contact = contract_sale[0].email
        sale.invoice_address = contract_sale[0].invoice_address
        sale.description = f"{contract_sale[0].contract.name} du {contract_sale[0].begin_date.strftime('%d/%m/%Y')} au {contract_sale[0].end_date.strftime('%d/%m/%Y')}"
        sale.reference = contract_sale[0].reference
        sale.payment_term = contract_sale[0].payment_term
        sale.save()

        return sale


    @classmethod
    def create_sale_line_and_tax(cls, contract_sale, sale):
        ContractAttribute = Pool().get('contract.contract.attribute')
        contract_attributes = ContractAttribute.search([('contract','=',contract_sale[0])])
        Line = Pool().get('sale.line')
        LineTax = Pool().get('sale.line-account.tax')

        for attribute in contract_attributes:
            line = Line()
            line.sale = sale
            line.note = attribute.attribute
            line.product = attribute.product
            line.quantity = attribute.quantity
            line.unit = attribute.uos
            line.base_price = round(Decimal(attribute.actual_price), 2)
            line.unit_price = round(Decimal(attribute.actual_price), 2)
            line.save()

            account_tax = attribute.product.account_category
            while account_tax.parent:
                account_tax = account_tax.parent


            tax = LineTax()
            tax.line = line
            tax.tax = account_tax.customer_taxes[0]
            tax.save()

    @classmethod
    def create_sale_contract(cls, contract_sale, sale):
        SaleContract = Pool().get('sale.sale-contract.contract')

        sale_contract = SaleContract()
        sale_contract.sale = sale
        sale_contract.contract = contract_sale[0]
        sale_contract.save()
