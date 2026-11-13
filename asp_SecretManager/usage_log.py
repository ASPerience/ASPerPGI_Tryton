import datetime
import logging

from dateutil.relativedelta import relativedelta
from trytond.model import ModelSQL, ModelView, fields
from trytond.transaction import Transaction, without_check_access

logger = logging.getLogger(__name__)


def _utcnow_naive():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class SecretUsageLog(ModelSQL, ModelView):
    """Journal append-only des créations, lectures et modifications de secrets."""
    __name__ = 'secret.usage.log'
    __string__ = "Journal d'usage"

    date = fields.DateTime("Date", required=True, readonly=True)
    user = fields.Many2One(
        'res.user', "Utilisateur", readonly=True, ondelete='SET NULL')
    secret = fields.Many2One(
        'secret.secret', "Secret", readonly=True, ondelete='SET NULL')
    secret_name = fields.Char("Nom du secret", readonly=True)
    use_custom_key = fields.Boolean("Clé personnelle utilisée", readonly=True)
    action = fields.Selection([
        ('encrypt', "Chiffrement"),
        ('reencrypt', "Rechiffrement"),
        ('show', "Affichage"),
        ('unlock', "Déverrouillage"),
        ('delete', "Suppression"),
        ('rotate', "Rotation"),
        ], "Action", required=True, readonly=True)
    outcome = fields.Selection([
        ('success', "Succès"),
        ('failure', "Échec"),
        ], "Résultat", required=True, readonly=True)
    failure_reason = fields.Selection([
        (None, ''),
        ('decrypt_fail', "Déchiffrement impossible"),
        ('key_missing', "Clé absente"),
        ('invalid_key_format', "Format de clé invalide"),
        ], "Motif d'échec", readonly=True)
    channel = fields.Selection([
        ('ui', "Interface"),
        ('api', "API"),
        ], "Canal", required=True, readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order.insert(0, ('date', 'DESC'))

    @classmethod
    def _must_isolate(cls, outcome):
        if outcome == 'failure':
            return True
        if Transaction().readonly:
            return True
        return False

    @classmethod
    def purge_old_entries(cls):
        """Supprime les lignes de journal datant de plus d'un an."""
        cutoff = _utcnow_naive() - relativedelta(years=1)
        old = cls.search([('date', '<', cutoff)])
        if old:
            cls.delete(old)

    @classmethod
    def log_usage(cls, action, outcome='success', secret=None, secret_name=None,
            failure_reason=None, channel=None, use_custom_key=None):
        try:
            if channel is None:
                channel = Transaction().context.get('secret_log_channel', 'ui')
            if secret_name is None and secret is not None:
                secret_name = secret.name
            if use_custom_key is None:
                if secret is not None:
                    use_custom_key = secret.use_custom_key
                else:
                    use_custom_key = False
            user = Transaction().user or None
            if user == 0:
                user = None
            secret_id = None
            if secret is not None and secret.id and secret.id > 0:
                secret_id = secret.id
            values = {
                'date': _utcnow_naive(),
                'user': user,
                'secret': secret_id,
                'secret_name': secret_name or '',
                'use_custom_key': use_custom_key,
                'action': action,
                'outcome': outcome,
                'failure_reason': failure_reason,
                'channel': channel,
            }

            def _create():
                with without_check_access():
                    cls.create([values])

            if cls._must_isolate(outcome):
                with Transaction().new_transaction(autocommit=True):
                    _create()
            else:
                _create()
        except Exception:
            logger.warning(
                "Échec de journalisation du secret "
                "(action=%s, outcome=%s)",
                action, outcome, exc_info=True)
