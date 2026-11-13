import logging

from trytond.exceptions import UserError
from trytond.pool import Pool
from trytond.model import ModelSQL, ModelView, Unique, fields
from trytond.i18n import gettext
from trytond.pyson import Eval, Bool
from trytond.transaction import Transaction, check_access, without_check_access
from trytond.wizard import Wizard, StateView, StateTransition, Button

from .tools import SecretManager, CryptoManager, EncryptedFieldsMixin

_ = gettext
logger = logging.getLogger(__name__)


class Secret(ModelSQL, ModelView):
    __name__ = "secret.secret"
    __string__ = "Secret"

    name = fields.Char("Clé", required=True, strip=True,
        states={
            'readonly': Eval('id', -1) >= 0,
        }, depends=['id'])
    value = fields.Char("Valeur", required=True, strip=True,
        help="Saisir la valeur en clair : elle est chiffrée à l'enregistrement.",
        states={'invisible': Eval('id', -1) >= 0}, depends=['id'])
    use_custom_key = fields.Boolean(
        "Utiliser une clé personnelle ?",
        help="Cochez pour chiffrer ce secret avec une clé Fernet personnelle "
        "(générée via Administration → Secrets → Générer une clé) "
        "au lieu de la clé de l'instance.",
        states={'readonly': Eval('id', -1) >= 0}, depends=['id'])
    custom_key = fields.Function(
        fields.Char("Clé personnelle", strip=True,
            help="Clé Fernet générée via Administration → Secrets → Générer une clé. "
            "Obligatoire si « Utiliser une clé personnelle ? » est coché.",
            states={
                'invisible': (Eval('id', -1) >= 0) | ~Bool(Eval('use_custom_key')),
                'required': (Eval('id', -1) < 0) & Bool(Eval('use_custom_key')),
            }, depends=['id', 'use_custom_key']),
        'get_custom_key', setter='set_transient')
    decryption_key = fields.Function(
        fields.Char("Clé de déchiffrement", strip=True,
            help="Optionnel",
            states={'invisible': True}, depends=[]),
        'get_decryption_key', setter='set_transient')
    new_value = fields.Function(
        fields.Char("Nouvelle valeur", strip=True,
            states={'invisible': True}, depends=[]),
        'get_new_value', setter='set_transient')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('name_unique', Unique(t, t.name),
                'asp_SecretManager.msg_duplicate_secret_name'),
        ]
        cls._buttons.update({
            'show_value': {
                'invisible': Eval('id', -1) < 0,
                'depends': ['id'],
            },
            'start_edit': {
                'invisible': Eval('id', -1) < 0,
                'depends': ['id'],
            },
        })

    @classmethod
    def get_custom_key(cls, records, name):
        return {record.id: None for record in records}

    @classmethod
    def set_transient(cls, records, name, value):
        """Setter vide pour champs Function transitoires (custom_key, etc.).

        La valeur saisie est consommée par create/write : le chiffrement
        corrèle plusieurs champs, donc la persistance ne se fait pas ici.
        Tryton exige un setter pour que le champ ne soit pas readonly côté
        client.
        """
        pass

    @classmethod
    def get_decryption_key(cls, records, name):
        return {record.id: None for record in records}

    @classmethod
    def get_new_value(cls, records, name):
        return {record.id: None for record in records}

    @classmethod
    def _usage_log(cls, action, outcome='success', secret=None, secret_name=None,
            failure_reason=None, channel=None, use_custom_key=None):
        UsageLog = Pool().get('secret.usage.log')
        UsageLog.log_usage(
            action, outcome=outcome, secret=secret,
            secret_name=secret_name, failure_reason=failure_reason,
            channel=channel, use_custom_key=use_custom_key)

    @classmethod
    def _failure_reason_from_user_error(cls, exc):
        message = exc.message
        if message in (
                _('asp_SecretManager.msg_personal_key_required'),
                _('asp_SecretManager.msg_encryption_key_required'),
                _('asp_SecretManager.msg_key_source_not_configured')):
            return 'key_missing'
        if message == _('asp_SecretManager.msg_invalid_fernet_key_format'):
            return 'invalid_key_format'
        return 'decrypt_fail'

    @classmethod
    def _check_current_value(cls, record, decryption_key):
        try:
            record.get_value_decrypted(key=decryption_key or None)
        except UserError as exc:
            cls._usage_log(
                'reencrypt', outcome='failure', secret=record,
                failure_reason=cls._failure_reason_from_user_error(exc))
            raise

    @classmethod
    def _reencrypt_value(cls, record, value, decryption_key):
        try:
            encrypted = cls._encrypt_plain_value(
                value, record.use_custom_key, decryption_key)
        except UserError as exc:
            cls._usage_log(
                'reencrypt', outcome='failure', secret=record,
                failure_reason=cls._failure_reason_from_user_error(exc))
            raise
        return encrypted, encrypted != value

    @classmethod
    def _check_duplicate_name(cls, name, exclude_ids=None):
        if not name:
            return
        domain = [('name', '=', name)]
        if exclude_ids:
            domain.append(('id', 'not in', list(exclude_ids)))
        if cls.search(domain, limit=1):
            raise UserError(_('asp_SecretManager.msg_duplicate_secret_name'))

    @classmethod
    def create(cls, vlist):
        vlist = [v.copy() for v in vlist]
        for vals in vlist:
            custom_key = vals.get("custom_key")
            use_custom_key = vals.get("use_custom_key", False)
            if not vals.get("name"):
                raise UserError(_('asp_SecretManager.msg_secret_name_required'))
            if not vals.get("value"):
                raise UserError(_('asp_SecretManager.msg_secret_value_required'))
            if use_custom_key and not custom_key:
                cls._usage_log(
                    'encrypt', outcome='failure', secret_name=vals.get('name'),
                    failure_reason='key_missing', use_custom_key=True)
                raise UserError(_('asp_SecretManager.msg_personal_key_required'))
            cls._check_duplicate_name(vals["name"])
            try:
                vals["value"] = cls._encrypt_plain_value(
                    vals["value"], use_custom_key, custom_key)
            except UserError as exc:
                cls._usage_log(
                    'encrypt', outcome='failure',
                    secret_name=vals.get('name'),
                    failure_reason=cls._failure_reason_from_user_error(
                        exc),
                    use_custom_key=use_custom_key)
                raise
            vals.pop("custom_key", None)
        secrets = super().create(vlist)
        for secret in secrets:
            cls._usage_log('encrypt', secret=secret)
        return secrets

    @classmethod
    def _encrypt_plain_value(cls, value, use_custom_key, encryption_key):
        check_key = encryption_key if use_custom_key else None
        if SecretManager.is_encrypted(value, check_key):
            return value
        if use_custom_key:
            if not encryption_key:
                raise UserError(_('asp_SecretManager.msg_encryption_key_required'))
            return CryptoManager.encrypt(value, encryption_key)
        return CryptoManager.encrypt(value)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        new_args = []
        reencrypt_success = []
        for records, values in zip(actions, actions):
            values = values.copy()
            decryption_key = values.pop("decryption_key", None)
            new_value = values.pop("new_value", None)
            values.pop("custom_key", None)
            # Pop porteur : use_custom_key est immuable après création (SQL).
            values.pop("use_custom_key", None)

            if values.get('name'):
                cls._check_duplicate_name(
                    values['name'], exclude_ids=[r.id for r in records])

            if new_value:
                for record in records:
                    cls._check_current_value(record, decryption_key)
                if len(records) == 1:
                    record = records[0]
                    encrypted, changed = cls._reencrypt_value(
                        record, new_value, decryption_key)
                    values['value'] = encrypted
                    if changed:
                        reencrypt_success.append(record)
                else:
                    for record in records:
                        record_vals = dict(values)
                        encrypted, changed = cls._reencrypt_value(
                            record, new_value, decryption_key)
                        record_vals['value'] = encrypted
                        if changed:
                            reencrypt_success.append(record)
                        new_args.extend([[record], record_vals])
                    continue
            elif 'value' in values:
                if len(records) == 1:
                    record = records[0]
                    if record.use_custom_key:
                        cls._check_current_value(record, decryption_key)
                    encrypted, changed = cls._reencrypt_value(
                        record, values['value'], decryption_key)
                    values['value'] = encrypted
                    if changed:
                        reencrypt_success.append(record)
                else:
                    for record in records:
                        if record.use_custom_key:
                            cls._check_current_value(record, decryption_key)
                        record_vals = dict(values)
                        encrypted, changed = cls._reencrypt_value(
                            record, values['value'], decryption_key)
                        record_vals['value'] = encrypted
                        if changed:
                            reencrypt_success.append(record)
                        new_args.extend([[record], record_vals])
                    continue

            if values:
                new_args.extend([records, values])

        if not new_args:
            return
        result = super().write(*new_args)
        for record in reencrypt_success:
            cls._usage_log('reencrypt', secret=record)
        return result

    @classmethod
    def delete(cls, records):
        for record in records:
            cls._usage_log('delete', secret=record)
        UsageLog = Pool().get('secret.usage.log')
        record_ids = [record.id for record in records]
        logs = UsageLog.search([('secret', 'in', record_ids)])
        if logs:
            with without_check_access():
                UsageLog.write(logs, {'secret': None})
        return super().delete(records)

    def get_value_decrypted(self, key=None):
        if key:
            return CryptoManager.decrypt(self, key=key)
        if self.use_custom_key:
            raise UserError(_('asp_SecretManager.msg_encryption_key_required'))
        return CryptoManager.decrypt(self)

    @classmethod
    def show_decrypted_value(cls, record, decryption_key):
        try:
            decrypted = record.get_value_decrypted(key=decryption_key or None)
            cls._usage_log('show', secret=record)
            return decrypted
        except UserError as exc:
            cls._usage_log(
                'show', outcome='failure', secret=record,
                failure_reason=cls._failure_reason_from_user_error(exc))
            raise

    @classmethod
    def unlock_for_edit(cls, record, decryption_key):
        try:
            record.get_value_decrypted(key=decryption_key or None)
            cls._usage_log('unlock', secret=record)
        except UserError as exc:
            cls._usage_log(
                'unlock', outcome='failure', secret=record,
                failure_reason=cls._failure_reason_from_user_error(exc))
            raise

    @classmethod
    @ModelView.button_action('asp_SecretManager.act_show_value')
    def show_value(cls, records):
        pass

    @classmethod
    @ModelView.button_action('asp_SecretManager.act_edit_value')
    def start_edit(cls, records):
        pass

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        old_fs_id = 'user_admin_group_secret_ma,nager_admin'
        new_fs_id = 'user_admin_group_secret_manager_admin'
        old_records = ModelData.search([
            ('module', '=', module_name),
            ('fs_id', '=', old_fs_id),
        ], limit=1)
        if old_records:
            new_records = ModelData.search([
                ('module', '=', module_name),
                ('fs_id', '=', new_fs_id),
            ], limit=1)
            if not new_records:
                ModelData.write(old_records, {'fs_id': new_fs_id})
        old_fs_id = 'wizard_genererate_key_group'
        new_fs_id = 'wizard_generate_key_group'
        old_records = ModelData.search([
            ('module', '=', module_name),
            ('fs_id', '=', old_fs_id),
        ], limit=1)
        if old_records:
            new_records = ModelData.search([
                ('module', '=', module_name),
                ('fs_id', '=', new_fs_id),
            ], limit=1)
            if not new_records:
                ModelData.write(old_records, {'fs_id': new_fs_id})
        Group = pool.get('res.group')
        Translation = pool.get('ir.translation')
        group_table = Group.__table__()
        translation_table = Translation.__table__()
        cursor = Transaction().connection.cursor()
        fixes = (
            ('group_secret_manager', 'Gestionnaire de secrets',
                ('Secret Manager', 'SecretManager')),
            ('group_secret_manager_admin', 'Administration des secrets',
                ('Secret Manager Administration',)),
        )
        for fs_id, french_name, old_names in fixes:
            model_data_records = ModelData.search([
                ('module', '=', module_name),
                ('fs_id', '=', fs_id),
                ('model', '=', 'res.group'),
            ], limit=1)
            if not model_data_records:
                continue
            db_id = model_data_records[0].db_id
            if not db_id:
                continue
            cursor.execute(*group_table.update(
                [group_table.name], [french_name],
                where=(group_table.id == db_id)
                & group_table.name.in_(old_names)))
            cursor.execute(*translation_table.delete(
                where=(translation_table.res_id == db_id)
                & (translation_table.name == 'res.group,name')
                & (translation_table.type == 'model')))


class SessionSecretGuardMixin:
    _sensitive_fields = {}
    _sensitive_input_states = ()

    @classmethod
    def execute(cls, session_id, data, state_name):
        data = {
            k: dict(v) if isinstance(v, dict) else v
            for k, v in data.items()
        }
        if state_name not in cls._sensitive_input_states:
            for state, sensitive_fields in cls._sensitive_fields.items():
                state_data = data.get(state)
                if isinstance(state_data, dict):
                    for field in sensitive_fields:
                        state_data.pop(field, None)
        return super().execute(session_id, data, state_name)

    def _save(self):
        saved = []
        try:
            for state_name, sensitive_fields in self.__class__._sensitive_fields.items():
                state = self.states.get(state_name)
                if not isinstance(state, StateView):
                    continue
                view = getattr(self, state_name, None)
                if view is None:
                    continue
                for field_name in sensitive_fields:
                    if field_name in view._values:
                        saved.append((
                                view, field_name,
                                view._values._pop(field_name, None)))
            super()._save()
        finally:
            for view, field_name, value in saved:
                if value is not None:
                    view._values[field_name] = value


class GenerateKeyStart(ModelView):
    """Formulaire de départ du wizard de génération de clé Fernet."""
    __name__ = 'secret.generate.start'
    __string__ = "Générer une clé"

    key = fields.Char("Clé générée", readonly=True)


class GenerateKey(SessionSecretGuardMixin, Wizard):
    """Assistant de génération d'une clé Fernet."""
    __name__ = 'secret.generate'
    _sensitive_fields = {'start': ('key',)}
    _sensitive_input_states = ()

    start = StateView(
        'secret.generate.start',
        'asp_SecretManager.generate_key_view',
        [
            Button("Fermer", 'end', 'tryton-close'),
        ]
    )

    def default_start(self, fields):
        key = CryptoManager.keygen()
        return {
            'key': key
        }


class ShowValueAsk(ModelView):
    """Saisie de la clé de déchiffrement pour l'assistant Afficher."""
    __name__ = 'secret.show.ask'
    __string__ = "Afficher la valeur"

    use_custom_key = fields.Boolean(
        "Utiliser une clé personnelle ?",
        readonly=True,
        states={'invisible': True})
    decryption_key = fields.Char("Clé de déchiffrement", strip=True,
        help="Optionnel",
        states={
            'invisible': ~Bool(Eval('use_custom_key')),
            'required': Bool(Eval('use_custom_key')),
        }, depends=['use_custom_key'])


class ShowValueResult(ModelView):
    """Résultat du wizard d'affichage de secret."""
    __name__ = 'secret.show.result'
    __string__ = "Valeur du secret"

    decrypted_value = fields.Char("Valeur déchiffrée", readonly=True)


class ShowValue(SessionSecretGuardMixin, Wizard):
    """Assistant d'affichage de la valeur d'un secret."""
    __name__ = 'secret.show'
    _sensitive_fields = {
        'ask': ('decryption_key',),
        'result': ('decrypted_value',),
    }
    _sensitive_input_states = ('show',)

    start = StateTransition()
    ask = StateView(
        'secret.show.ask',
        'asp_SecretManager.show_value_ask_view',
        [
            Button("Annuler", 'end', 'tryton-cancel'),
            Button("Afficher", 'show', 'tryton-ok', default=True),
        ]
    )
    show = StateTransition()
    result = StateView(
        'secret.show.result',
        'asp_SecretManager.show_value_result_view',
        [
            Button("Fermer", 'end', 'tryton-close'),
        ]
    )

    def transition_start(self):
        Secret = Pool().get('secret.secret')
        record = self.record
        if record.use_custom_key:
            return 'ask'
        decrypted = Secret.show_decrypted_value(record, None)
        self.result.decrypted_value = decrypted
        return 'result'

    def default_ask(self, fields):
        record = self.record
        defaults = {}
        if 'use_custom_key' in fields:
            defaults['use_custom_key'] = record.use_custom_key
        return defaults

    def transition_show(self):
        Secret = Pool().get('secret.secret')
        record = self.record
        decrypted = Secret.show_decrypted_value(
            record, self.ask.decryption_key or None)
        self.result.decrypted_value = decrypted
        return 'result'

    def default_result(self, fields):
        return {
            'decrypted_value': self.result.decrypted_value,
        }


class EditValueStart(ModelView):
    """Formulaire de départ du wizard de modification de secret."""
    __name__ = 'secret.edit.start'
    __string__ = "Modifier la valeur"

    use_custom_key = fields.Boolean(
        "Utiliser une clé personnelle ?",
        readonly=True,
        states={'invisible': True})
    decryption_key = fields.Char("Clé de déchiffrement", strip=True,
        help="Optionnel",
        states={
            'invisible': ~Bool(Eval('use_custom_key')),
            'required': Bool(Eval('use_custom_key')),
        }, depends=['use_custom_key'])
    new_value = fields.Char("Nouvelle valeur", required=True, strip=True)


class EditValue(SessionSecretGuardMixin, Wizard):
    """Assistant de modification de la valeur d'un secret."""
    __name__ = 'secret.edit'
    _sensitive_fields = {'start': ('decryption_key', 'new_value')}
    _sensitive_input_states = ('save',)

    start = StateView(
        'secret.edit.start',
        'asp_SecretManager.edit_value_start_view',
        [
            Button("Annuler", 'end', 'tryton-cancel'),
            Button("Enregistrer", 'save', 'tryton-save', default=True),
        ]
    )
    save = StateTransition()

    def default_start(self, fields):
        record = self.record
        defaults = {}
        if 'use_custom_key' in fields:
            defaults['use_custom_key'] = record.use_custom_key
        return defaults

    def transition_save(self):
        ModelAccess = Pool().get('ir.model.access')
        with check_access():
            ModelAccess.check('secret.secret', 'write')

        Secret = Pool().get('secret.secret')
        record = self.record
        decryption_key = self.start.decryption_key or None
        Secret.unlock_for_edit(record, decryption_key)
        values = {
            'new_value': self.start.new_value,
            'decryption_key': decryption_key,
        }
        Secret.write([record], values)
        return 'end'


class RotateKeyStart(ModelView):
    """Formulaire de départ du wizard de rechiffrement des secrets d'instance."""
    __name__ = 'secret.rotate.start'
    __string__ = "Rechiffrer les secrets"

    secret_count = fields.Integer(
        "Secrets concernés", readonly=True)
    encrypted_field_count = fields.Integer(
        "Champs métier concernés", readonly=True)
    custom_key_count = fields.Integer(
        "Secrets à clé personnelle (ignorés)", readonly=True)
    old_key_configured = fields.Boolean(
        "Ancienne clé configurée", readonly=True)


class RotateKeyResult(ModelView):
    """Résultat du wizard de rechiffrement des secrets d'instance."""
    __name__ = 'secret.rotate.result'
    __string__ = "Rechiffrement terminé"

    rotated_count = fields.Integer("Secrets rechiffrés", readonly=True)
    already_current_count = fields.Integer("Déjà à jour", readonly=True)
    custom_key_count = fields.Integer(
        "Ignorés (clé personnelle)", readonly=True)
    failed_count = fields.Integer("En échec", readonly=True)
    failed_names = fields.Text("Secrets en échec", readonly=True)


class RotateKey(Wizard):
    """Assistant de rechiffrement des secrets d'instance."""
    __name__ = 'secret.rotate'

    start = StateView(
        'secret.rotate.start',
        'asp_SecretManager.rotate_key_start_view',
        [
            Button("Annuler", 'end', 'tryton-cancel'),
            Button("Rechiffrer", 'rotate', 'tryton-ok', default=True),
        ]
    )
    rotate = StateTransition()
    result = StateView(
        'secret.rotate.result',
        'asp_SecretManager.rotate_key_result_view',
        [
            Button("Fermer", 'end', 'tryton-close'),
        ]
    )

    def default_start(self, fields):
        Secret = Pool().get('secret.secret')
        return {
            'secret_count': Secret.search_count([
                ('use_custom_key', '=', False),
            ]),
            'encrypted_field_count': self._count_instance_encrypted_fields(),
            'custom_key_count': Secret.search_count([
                ('use_custom_key', '=', True),
            ]),
            'old_key_configured': CryptoManager.has_old_instance_key(),
        }

    @classmethod
    def _iter_instance_encrypted_models(cls):
        for name, Model in Pool().iterobject():
            if name == 'secret.secret':
                continue
            if not issubclass(Model, EncryptedFieldsMixin):
                continue
            field_names = []
            for fname in Model._instance_encrypted_fields:
                field = Model._fields.get(fname)
                if field is None:
                    logger.warning(
                        'Rotation clé instance : champ inconnu %s.%s',
                        Model.__name__, fname)
                    continue
                if field._type != 'char':
                    logger.warning(
                        'Rotation clé instance : champ non-Char %s.%s',
                        Model.__name__, fname)
                    continue
                field_names.append(fname)
            if field_names:
                yield Model, tuple(field_names)

    def _count_instance_encrypted_fields(self):
        count = 0
        with without_check_access():
            for Model, field_names in self._iter_instance_encrypted_models():
                for record in Model.search([]):
                    for fname in field_names:
                        value = getattr(record, fname, None)
                        if value not in (None, ''):
                            count += 1
        return count

    def _rotate_instance_encrypted_fields(self):
        rotated = 0
        already = 0
        failed = 0
        failed_names = []
        with without_check_access():
            for Model, field_names in self._iter_instance_encrypted_models():
                write_args = []
                for record in Model.search([]):
                    for fname in field_names:
                        value = getattr(record, fname, None)
                        if value in (None, ''):
                            continue
                        if CryptoManager.is_encrypted_with_primary_key(value):
                            already += 1
                            continue
                        try:
                            new_token = CryptoManager.rotate_to_primary_key(
                                value)
                        except UserError:
                            failed += 1
                            failed_names.append(
                                '%s.%s (id=%s)' % (
                                    Model.__name__, fname, record.id))
                            logger.warning(
                                'Rotation clé instance : champ métier en '
                                'échec %s.%s (id=%s)',
                                Model.__name__, fname, record.id)
                            continue
                        write_args.extend([
                            [record], {fname: new_token}])
                        rotated += 1
                if write_args:
                    Model.write(*write_args)
        return rotated, already, failed, failed_names

    def transition_rotate(self):
        ModelAccess = Pool().get('ir.model.access')
        with check_access():
            ModelAccess.check('secret.secret', 'write')

        Secret = Pool().get('secret.secret')
        rotated = 0
        already = 0
        failed = 0
        failed_names = []
        custom_key_count = Secret.search_count([
            ('use_custom_key', '=', True),
        ])
        write_args = []
        for secret in Secret.search([('use_custom_key', '=', False)]):
            if not secret.value:
                failed += 1
                failed_names.append('%s (id=%s)' % (secret.name, secret.id))
                Secret._usage_log(
                    'rotate', outcome='failure', secret=secret)
                logger.warning(
                    'Rotation clé instance : secret en échec (valeur vide) '
                    '%s (id=%s)', secret.name, secret.id)
                continue
            if CryptoManager.is_encrypted_with_primary_key(secret.value):
                already += 1
                continue
            try:
                new_value = CryptoManager.rotate_to_primary_key(secret.value)
            except UserError as exc:
                failed += 1
                failed_names.append('%s (id=%s)' % (secret.name, secret.id))
                Secret._usage_log(
                    'rotate', outcome='failure', secret=secret,
                    failure_reason=Secret._failure_reason_from_user_error(exc))
                logger.warning(
                    'Rotation clé instance : secret en échec (déchiffrement) '
                    '%s (id=%s)', secret.name, secret.id)
                continue
            write_args.extend([[secret], {'value': new_value}])
            rotated += 1
        if write_args:
            Secret.write(*write_args)
            for i in range(0, len(write_args), 2):
                secret, = write_args[i]
                Secret._usage_log('rotate', secret=secret)
        inst_rotated, inst_already, inst_failed, inst_failed_names = (
            self._rotate_instance_encrypted_fields())
        rotated += inst_rotated
        already += inst_already
        failed += inst_failed
        failed_names.extend(inst_failed_names)
        self.result.rotated_count = rotated
        self.result.already_current_count = already
        self.result.custom_key_count = custom_key_count
        self.result.failed_count = failed
        self.result.failed_names = '\n'.join(failed_names) if failed_names else ''
        return 'result'

    def default_result(self, fields):
        return {
            'rotated_count': self.result.rotated_count,
            'already_current_count': self.result.already_current_count,
            'custom_key_count': self.result.custom_key_count,
            'failed_count': self.result.failed_count,
            'failed_names': self.result.failed_names,
        }
