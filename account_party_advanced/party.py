# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from decimal import Decimal

from sql import Literal, Null
from sql.aggregate import Sum
from sql.conditionals import Coalesce

from trytond import backend
from trytond.i18n import gettext
from trytond.model import ModelSQL, fields
from trytond.pyson import Eval, If
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond.tools import reduce_ids, grouped_slice
from trytond.tools.multivalue import migrate_property
from trytond.modules.company.model import (
    CompanyMultiValueMixin, CompanyValueMixin)
from trytond.modules.party.exceptions import EraseError

from .exceptions import AccountMissing

account_names = [
    'account_payable', 'account_receivable',
    'customer_tax_rule', 'supplier_tax_rule']


class Party(CompanyMultiValueMixin, metaclass=PoolMeta):
    __name__ = 'party.party'
    account_payable = fields.MultiValue(fields.Many2One(
            'account.account', "Account Payable",
            domain=[
                ('closed', '!=', True),
                ('type.payable', '=', True),
                ('party_required', '=', True),
                ('company', '=', Eval('context', {}).get('company', -1)),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company') and ('supplier','=',False),
                }))
    account_receivable = fields.MultiValue(fields.Many2One(
            'account.account', "Account Receivable",
            domain=[
                ('closed', '!=', True),
                ('type.receivable', '=', True),
                ('party_required', '=', True),
                ('company', '=', Eval('context', {}).get('company', -1)),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company') and ('customer','=',False),
                }))
    customer_tax_rule = fields.MultiValue(fields.Many2One(
            'account.tax.rule', "Customer Tax Rule",
            domain=[
                ('company', '=', Eval('context', {}).get('company', -1)),
                ('kind', 'in', ['sale', 'both']),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company') and ('customer','=',False),
                }, help='Apply this rule on taxes when party is customer.'))
    supplier_tax_rule = fields.MultiValue(fields.Many2One(
            'account.tax.rule', "Supplier Tax Rule",
            domain=[
                ('company', '=', Eval('context', {}).get('company', -1)),
                ('kind', 'in', ['purchase', 'both']),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company') and ('supplier','=',False),
                }, help='Apply this rule on taxes when party is supplier.'))
    receivable = fields.Function(fields.Numeric('Receivable',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']),
            states={
                'invisible': ('customer','=',False),
            },
            'get_receivable_payable', searcher='search_receivable_payable')
    payable = fields.Function(fields.Numeric('Payable',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']),
            states={
                'invisible': ('supplier','=',False),
            },
            'get_receivable_payable', searcher='search_receivable_payable')
    receivable_today = fields.Function(fields.Numeric('Receivable Today',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']),
            states={
                'invisible': ('customer','=',False),
            },
            'get_receivable_payable', searcher='search_receivable_payable')
    payable_today = fields.Function(fields.Numeric('Payable Today',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']),
            states={
                'invisible': ('supplier','=',False),
            },
            'get_receivable_payable', searcher='search_receivable_payable')


