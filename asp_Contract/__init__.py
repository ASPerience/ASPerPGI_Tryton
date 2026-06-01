# The COPYRIGHT file at the top level of this repository contains the full copyright notices and license terms

from trytond.pool import Pool
from . import product_contract as pc
from . import contract_contract as cc
from . import cron

def register():
    Pool.register(
        pc.ContractAttribute,
        pc.Contract,
        cc.ContractContract,
        cc.ContractContractAttribute,
        cc.ContractContractInvoice,
        cc.ContractContractInvoiceDetail,
        cc.SaleProductContract,
        cc.Sale,
        cron.Cron,
        cron.ContractAdministration,
        module='asp_Contract', type_='model')
