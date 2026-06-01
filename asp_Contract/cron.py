from trytond.pool import PoolMeta, Pool
from trytond.model import ModelSQL
from trytond.modules.asp_Contract.tools import Tools
from dateutil.relativedelta import relativedelta

import datetime as dt

class Cron(metaclass=PoolMeta):
    __name__ = 'ir.cron'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.method.selection.append(
            ('contract.administration|get_contracts', "Gestion des contrats")
        )

class ContractAdministration(ModelSQL):
    """ Gestion des contrats """

    __name__ = 'contract.administration'


    @classmethod
    def pool_gets(cls):
        cls.Contract = Pool().get('contract.contract')
        cls.ContractInvoiceLine = Pool().get('contract.contract.invoice')


    @classmethod
    def get_contracts(cls):
        cls.pool_gets()
        today = dt.date.today().replace(day=1)
        # today = dt.date(2024, 1, 1)
        contracts = cls.Contract.search([('state', '=', 'started')])

        time_delta = dt.timedelta(days=1)
        end_period_searched = (today - time_delta).strftime('%d-%m-%y')
        lines_list = []
        for contract in contracts or []:
            if contract.closure_date:
                if contract.closure_date.strftime('%d-%m-%y') == end_period_searched:
                    """Cloture des contrats"""
                    contract.state = 'closed'
                    contract.save()

            lines = cls.get_invoice_line(contract, end_period_searched)
            if lines: lines_list.append(lines)

        cls.invoices_creation(lines_list)


    @classmethod
    def get_invoice_line(cls, contract, end_period_searched):
        invoice_line_list = []

        lines = cls.ContractInvoiceLine.search(
                [('state', '=', 'in_progress'), ('contract', '=', contract)],
                order=[('number', 'DESC')]
            )
        if not lines: return False

        for line in lines or []:
            start, end = line.period.split(' => ')
            start = dt.datetime.strptime(start, '%d-%m-%y')
            day_before_start = (start - dt.timedelta(days=1)).strftime('%d-%m-%y')
            billing_date = day_before_start if contract.billing_in_period_start else end
            if end_period_searched == billing_date:
                print(line)
                line.state = 'finished'
                line.save()

                if contract.state == 'started':
                    Tools.create_contract_invoice_line([contract])

                if contract.billing_in_period_start:
                    begin_date = start.replace(day=1)
                    begin_next_period = begin_date + relativedelta(months=contract.billing_time_in_months)
                    Tools.create_contract_invoice_line([contract], begin_next_period)

                invoice_line_list.append(line)

        return invoice_line_list



    @classmethod
    def invoices_creation(cls, lines_list):
        for lines in lines_list:
            if not lines[0].invoice:
                invoice = Tools.create_invoice([lines[0].contract], [lines[0]], lines)
                Tools.create_invoice_line_and_tax(lines, invoice)
            elif lines[0].invoice.state == 'draft':
                Invoice = Pool().get('account.invoice')
                invoice, = Invoice.search([('id', '=', lines[0].invoice)])
                Tools.drop_invoice_line_and_tax(invoice)
                Tools.create_invoice_line_and_tax(lines, invoice)
