from trytond.pool import PoolMeta


class Cron(metaclass=PoolMeta):
    __name__ = 'ir.cron'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        method = (
            'secret.usage.log|purge_old_entries',
            "Purge du journal d'usage des secrets",
        )
        if method not in cls.method.selection:
            cls.method.selection.append(method)
