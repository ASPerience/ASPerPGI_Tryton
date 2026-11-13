import base64
import logging
import os
from collections import namedtuple

import trytond.config as config
from cryptography.fernet import Fernet, MultiFernet
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import check_access, Transaction

logger = logging.getLogger(__name__)
_ = gettext

SecretSnapshot = namedtuple(
    'SecretSnapshot', ['id', 'name', 'value', 'use_custom_key'])


class EncryptedFieldsMixin:
    """Mixin pour modèles stockant des Char Fernet hors coffre.

    Les champs listés dans ``_instance_encrypted_fields`` sont rechiffrés
    par le wizard ``secret.rotate`` après rotation de la clé d'instance.
    """
    __slots__ = ()
    _instance_encrypted_fields = ()

CONFIG_SECTION = 'asp_secret_manager'


def _read_key_from_file(path):
    try:
        stat_result = os.stat(path)
    except OSError:
        logger.warning(
            "Impossible de lire le fichier de clé : %s", path, exc_info=True)
        raise UserError(gettext('asp_SecretManager.msg_key_file_unreadable'))

    mode = stat_result.st_mode & 0o777
    if mode & 0o077:
        raise UserError(
            gettext(
                'asp_SecretManager.msg_key_file_permissions', mode=oct(mode)))

    try:
        with open(path, 'r', encoding='utf-8') as key_file:
            key = key_file.read().strip()
    except OSError:
        logger.warning(
            "Impossible de lire le fichier de clé : %s", path, exc_info=True)
        raise UserError(gettext('asp_SecretManager.msg_key_file_unreadable'))

    return key


def _resolve_instance_key():
    key_file = config.get(CONFIG_SECTION, 'key_file')
    if key_file:
        return _read_key_from_file(key_file)

    key = config.get(CONFIG_SECTION, 'key')
    if key:
        return key.strip()

    raise UserError(_('asp_SecretManager.msg_key_source_not_configured'))


def _resolve_old_instance_key():
    """Ancienne clé d'instance ([asp_secret_manager] old_key), utilisée en
    déchiffrement seul pendant une rotation. Absente hors fenêtre de rotation."""
    old_key = config.get(CONFIG_SECTION, 'old_key')
    return old_key.strip() if old_key else None


def _resolve_instance_keys():
    """Clés d'instance dans l'ordre : primaire (chiffrement) puis old_key."""
    keys = [_resolve_instance_key()]
    old_key = _resolve_old_instance_key()
    if old_key and old_key not in keys:
        keys.append(old_key)
    return keys


def _is_canonical_fernet_token(value):
    try:
        raw = value.encode('ascii')
    except UnicodeEncodeError:
        return False
    try:
        decoded = base64.urlsafe_b64decode(
            raw + b'=' * (-len(raw) % 4))
    except Exception:
        return False
    reencoded = base64.urlsafe_b64encode(decoded).rstrip(b'=')
    return reencoded == raw.rstrip(b'=')


def _fernet_from_key(key):
    try:
        return Fernet(key.encode())
    except Exception:
        raise UserError(_('asp_SecretManager.msg_invalid_fernet_key_format'))


def _fernet_from_instance_key():
    return _fernet_from_key(_resolve_instance_key())


def _fernets_from_instance_keys():
    return [_fernet_from_key(key) for key in _resolve_instance_keys()]


def _multifernet_from_instance_keys():
    return MultiFernet(_fernets_from_instance_keys())


class _DefaultCipher:

    def __bool__(self):
        try:
            _resolve_instance_key()
            return True
        except UserError:
            return False

    def encrypt(self, data):
        return _multifernet_from_instance_keys().encrypt(data)

    def decrypt(self, token):
        return _multifernet_from_instance_keys().decrypt(token)

    def extract_timestamp(self, token):
        last_error = None
        for fernet in _fernets_from_instance_keys():
            try:
                return fernet.extract_timestamp(token)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise UserError(_('asp_SecretManager.msg_decrypt_failed_wrong_key'))


class SecretManager():

    @classmethod
    def _get_record(cls, secret_name):
        """Accès interne à l'enregistrement ORM (edit, journal)."""
        SecuritySecret = Pool().get('secret.secret')

        with check_access():
            return next(iter(SecuritySecret.search([
                ('name', '=', secret_name)
            ])), None)

    @classmethod
    def get(cls, secret_name):
        """Retourne un snapshot lecture seule du secret, ou None si absent.

        Les modifications passent par edit() ou Secret.write."""
        secret = cls._get_record(secret_name)
        if secret is None:
            return None
        return SecretSnapshot(
            id=secret.id,
            name=secret.name,
            value=secret.value,
            use_custom_key=secret.use_custom_key,
        )

    @classmethod
    def edit(cls, secret_name, key, new_value):
        ModelAccess = Pool().get('ir.model.access')
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        with check_access():
            ModelAccess.check('secret.secret', 'write')
            if not (secret_name):
                raise UserError(
                    _('asp_SecretManager.msg_secret_edit_name_required'))
            if not (new_value):
                raise UserError(_('asp_SecretManager.msg_new_value_required'))

            try:
                with Transaction().set_context(secret_log_channel='api'):
                    secret = cls._get_record(secret_name)
                    if not secret:
                        raise UserError(
                            _('asp_SecretManager.msg_secret_not_found'))
                    try:
                        if key:
                            CryptoManager.decrypt(secret.value, key)
                        elif secret.use_custom_key:
                            raise UserError(
                                _('asp_SecretManager.msg_encryption_key_required'))
                        else:
                            CryptoManager.decrypt(secret)
                    except UserError as exc:
                        message = exc.message
                        if message in (
                                _('asp_SecretManager.msg_personal_key_required'),
                                _('asp_SecretManager.msg_encryption_key_required'),
                                _('asp_SecretManager.msg_key_source_not_configured')):
                            failure_reason = 'key_missing'
                        elif message == _(
                                'asp_SecretManager.msg_invalid_fernet_key_format'):
                            failure_reason = 'invalid_key_format'
                        else:
                            failure_reason = 'decrypt_fail'
                        UsageLog.log_usage(
                            'reencrypt', outcome='failure', secret=secret,
                            failure_reason=failure_reason,
                            channel='api')
                        raise

                    encryption_key = key if key else None
                    if not cls.is_encrypted(new_value, encryption_key):
                        if key:
                            new_value = CryptoManager.encrypt(new_value, key)
                        elif secret.use_custom_key:
                            raise UserError(
                                _('asp_SecretManager.msg_encryption_key_required'))
                        else:
                            new_value = CryptoManager.encrypt(new_value)

                    write_values = {'value': new_value}
                    if secret.use_custom_key:
                        write_values['decryption_key'] = key
                    Secret.write([secret], write_values)
                    UsageLog.log_usage(
                        'reencrypt', secret=secret, channel='api')

            except UserError:
                raise

    @classmethod
    def save(cls, secret_name, value, personalized_key=None):
        ModelAccess = Pool().get('ir.model.access')
        Secret = Pool().get('secret.secret')
        with check_access():
            ModelAccess.check('secret.secret', 'create')
            with Transaction().set_context(secret_log_channel='api'):
                secrets = Secret.create([{
                    "name": secret_name,
                    "value": value,
                    "custom_key": personalized_key,
                    "use_custom_key": bool(personalized_key),
                }])
        return secrets[0] if secrets else None

    @classmethod
    def is_encrypted(cls, value, key=None):
        """Vérifie si une valeur est un jeton Fernet authentifié et de forme
        base64 urlsafe canonique avec la clé indiquée (clé d'instance si key
        omise)."""
        key = key or None
        if not value or not isinstance(value, str):
            return False

        if not _is_canonical_fernet_token(value):
            return False

        try:
            if key is not None:
                cipher = CryptoManager._get_cipher(key)
                cipher.extract_timestamp(value.encode())
            else:
                CryptoManager.default_cipher.extract_timestamp(value.encode())
            return True
        except Exception:
            return False


class CryptoManager:
    default_cipher = _DefaultCipher()

    @classmethod
    def _get_cipher(cls, key: str|None = None, use_default=False):
        if key:
            key = key.strip()
            try:
                return Fernet(key.encode())
            except Exception:
                raise UserError(
                    _('asp_SecretManager.msg_invalid_fernet_key_format'))

        if use_default:
            return _multifernet_from_instance_keys()

        raise UserError(_('asp_SecretManager.msg_key_required'))

    @classmethod
    def encrypt(cls, value: str, key: str|None = None) -> str:
        cipher = cls._get_cipher(key, use_default=(key is None))

        return cipher.encrypt(value.encode()).decode()

    @classmethod
    def decrypt(cls, secret, key: str|None = None) -> str:
        cipher = cls._get_cipher(key, use_default=(key is None))

        if secret is None:
            raise UserError(_('asp_SecretManager.msg_decrypt_failed_null_secret'))

        try:
            if hasattr(secret, "value"):
                val = secret.value
            else:
                val = str(secret)
            return cipher.decrypt(val.encode()).decode()
        except Exception:
            raise UserError(_('asp_SecretManager.msg_decrypt_failed_wrong_key'))

    @staticmethod
    def keygen() -> str:
        return Fernet.generate_key().decode()

    @classmethod
    def has_old_instance_key(cls) -> bool:
        return bool(_resolve_old_instance_key())

    @classmethod
    def is_encrypted_with_primary_key(cls, token: str) -> bool:
        """True si le jeton est signé par la clé d'instance primaire seule."""
        if not token or not isinstance(token, str):
            return False
        try:
            _fernet_from_instance_key().extract_timestamp(token.encode())
            return True
        except UserError:
            raise
        except Exception:
            return False

    @classmethod
    def rotate_to_primary_key(cls, token: str) -> str:
        """Rechiffre un jeton avec la clé primaire (timestamp d'origine conservé)."""
        try:
            return _multifernet_from_instance_keys().rotate(
                token.encode()).decode()
        except UserError:
            raise
        except Exception:
            raise UserError(_('asp_SecretManager.msg_decrypt_failed_wrong_key'))
