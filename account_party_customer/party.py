# This file is part of ASPerPGI for Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.model import fields
from trytond.pyson import Eval
from trytond.pool import PoolMeta
from trytond.modules.company.model import CompanyMultiValueMixin

class Party(CompanyMultiValueMixin, metaclass=PoolMeta):
    __name__ = 'party.party'
    account_receivable = fields.MultiValue(fields.Many2One(
            'account.account', "Account Receivable",
            domain=[
                ('closed', '!=', True),
                ('type.receivable', '=', True),
                ('party_required', '=', True),
                ('company', '=', Eval('context', {}).get('company', -1)),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company')
                    | ~Eval('customer',False),
                }))

    customer_tax_rule = fields.MultiValue(fields.Many2One(
            'account.tax.rule', "Customer Tax Rule",
            domain=[
                ('company', '=', Eval('context', {}).get('company', -1)),
                ('kind', 'in', ['sale', 'both']),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company')
                    | ~Eval('customer',False),
                }, help='Apply this rule on taxes when party is customer.'))
    receivable = fields.Function(fields.Numeric('Receivable',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
            states={
                'invisible': ~Eval('customer',False),
                }
            ),
            'get_receivable_payable', searcher='search_receivable_payable')
    receivable_today = fields.Function(fields.Numeric('Receivable Today',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
            states={
                'invisible': ~Eval('customer',False),
                }
            ),
            'get_receivable_payable', searcher='search_receivable_payable')

    @classmethod
    def view_attributes(cls):
        
        return super().view_attributes() + [
            ('//group[@id="customer_account"]', 'states', {'invisible': Eval('customer'),}),
            ('//group[@id="customer_tax"]', 'states', {'invisible': Eval('customer'),}),
            ]