import os
import tempfile
import uuid

import trytond.config as config
from trytond.exceptions import UserError
from trytond.pool import Pool
from trytond.i18n import gettext
from trytond.tests.test_tryton import ModuleTestCase, with_transaction
from trytond.transaction import Transaction

from trytond.modules.asp_SecretManager.secret import RotateKey
from trytond.modules.asp_SecretManager.tools import CryptoManager, SecretManager

_ = gettext


def _unique_secret_name(prefix='test_secret'):
    return f'{prefix}_{uuid.uuid4().hex}'


_CONFIG_SECTION = 'asp_secret_manager'
_CONFIG_OPTIONS = ('key', 'key_file', 'old_key')


def _ensure_config_section():
    if not config.has_section(_CONFIG_SECTION):
        config.add_section(_CONFIG_SECTION)


def _remove_config_option(option):
    _ensure_config_section()
    if config._config.has_option(_CONFIG_SECTION, option):
        config._config.remove_option(_CONFIG_SECTION, option)
        config._cache_clear()


def _clear_instance_key_config():
    for option in _CONFIG_OPTIONS:
        _remove_config_option(option)


def _restore_instance_key_config(saved):
    _ensure_config_section()
    for option, value in (
            ('key', saved['key']),
            ('key_file', saved['key_file']),
            ('old_key', saved['old_key'])):
        if value is None:
            _remove_config_option(option)
        else:
            config.set(_CONFIG_SECTION, option, value)


class AspSecretManagerTestCase(ModuleTestCase):
    "Tests du module asp_SecretManager"
    module = 'asp_SecretManager'

    def setUp(self):
        super().setUp()
        self._saved_key_config = {
            'key': config.get(_CONFIG_SECTION, 'key'),
            'key_file': config.get(_CONFIG_SECTION, 'key_file'),
            'old_key': config.get(_CONFIG_SECTION, 'old_key'),
        }
        _ensure_config_section()
        config.set(_CONFIG_SECTION, 'key', CryptoManager.keygen())
        _remove_config_option('key_file')
        _remove_config_option('old_key')
        self.addCleanup(_restore_instance_key_config, self._saved_key_config)

    def _write_key_file(self, mode=0o600):
        key = CryptoManager.keygen()
        fd, path = tempfile.mkstemp()
        os.close(fd)
        with open(path, 'w', encoding='utf-8') as key_file:
            key_file.write(key)
        os.chmod(path, mode)
        self.addCleanup(os.unlink, path)
        return path, key

    def _run_rotate_wizard(self):
        Wizard = Pool().get('secret.rotate', type='wizard')
        session_id, _, _ = Wizard.create()
        result = Wizard.execute(session_id, {}, 'rotate')
        return result['view']['defaults']

    def _secret_wizard_context(self, secret):
        return {
            'active_model': 'secret.secret',
            'active_id': secret.id,
            'active_ids': [secret.id],
        }

    def _session_data_str(self, session_id):
        Session = Pool().get('ir.session.wizard')
        session_data = Session(session_id).data
        if isinstance(session_data, bytes):
            session_data = session_data.decode('utf-8')
        return session_data

    def _run_show_wizard(self, secret, decryption_key=None, state='show'):
        Wizard = Pool().get('secret.show', type='wizard')
        with Transaction().set_context(**self._secret_wizard_context(secret)):
            session_id, _, _ = Wizard.create()
            result = Wizard.execute(session_id, {}, 'start')
            if secret.use_custom_key:
                ask_data = dict(result['view']['defaults'])
                if decryption_key is not None:
                    ask_data['decryption_key'] = decryption_key
                result = Wizard.execute(session_id, {'ask': ask_data}, state)
            return session_id, result

    def _run_edit_wizard(self, secret, new_value, decryption_key=None):
        Wizard = Pool().get('secret.edit', type='wizard')
        with Transaction().set_context(**self._secret_wizard_context(secret)):
            session_id, _, _ = Wizard.create()
            result = Wizard.execute(session_id, {}, 'start')
            start_data = dict(result['view']['defaults'])
            start_data['new_value'] = new_value
            if decryption_key is not None:
                start_data['decryption_key'] = decryption_key
            result = Wizard.execute(session_id, {'start': start_data}, 'save')
        return session_id, result

    @with_transaction()
    def test_create_encrypts_plain_value_with_custom_key(self):
        "Création avec clé personnelle : valeur chiffrée et déchiffrable"
        Secret = Pool().get('secret.secret')
        plain_value = 'clair'
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        self.assertNotEqual(secret.value, plain_value)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), plain_value)

    @with_transaction()
    def test_create_custom_key_not_returned_on_read(self):
        "Après création, custom_key n'est jamais renvoyé au client"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'clair',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        read_values, = Secret.read([secret.id], ['custom_key'])
        self.assertIsNone(read_values['custom_key'])

        browsed = Secret(secret.id)
        self.assertIsNone(browsed.custom_key)

    @with_transaction()
    def test_create_duplicate_name_raises_user_error(self):
        "Deuxième création avec le même nom : UserError"
        Secret = Pool().get('secret.secret')
        name = _unique_secret_name()
        custom_key = CryptoManager.keygen()
        Secret.create([{
            'name': name,
            'value': 'premier',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        with self.assertRaises(UserError):
            Secret.create([{
                'name': name,
                'value': 'deuxieme',
                'custom_key': custom_key,
                'use_custom_key': True,
            }])

    @with_transaction()
    def test_create_empty_value_raises_user_error(self):
        "Valeur absente ou vide à la création : UserError"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()

        with self.assertRaises(UserError):
            Secret.create([{
                'name': _unique_secret_name(),
                'custom_key': custom_key,
                'use_custom_key': True,
            }])

        with self.assertRaises(UserError):
            Secret.create([{
                'name': _unique_secret_name(),
                'value': '',
                'custom_key': custom_key,
                'use_custom_key': True,
            }])

    @with_transaction()
    def test_create_custom_key_required_when_use_custom_key(self):
        "Clé personnelle cochée sans clé : UserError explicite"
        Secret = Pool().get('secret.secret')

        with self.assertRaises(UserError) as cm:
            Secret.create([{
                'name': _unique_secret_name(),
                'value': 'clair',
                'use_custom_key': True,
            }])

        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_personal_key_required'))

    @with_transaction()
    def test_secret_manager_get_unknown_name_returns_none(self):
        "SecretManager.get sur un nom inexistant : None (pas une liste vide)"
        name = _unique_secret_name('missing')

        result = SecretManager.get(name)

        self.assertIsNone(result)

    @with_transaction()
    def test_secret_manager_edit_unknown_name_raises_not_found(self):
        "SecretManager.edit avec un nom inexistant : UserError msg_secret_not_found"
        name = _unique_secret_name('missing')

        with self.assertRaises(UserError) as cm:
            SecretManager.edit(name, None, 'nouvelle_valeur')

        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_secret_not_found'))

    @with_transaction()
    def test_secret_manager_edit_empty_name_raises_name_required(self):
        "SecretManager.edit sans nom : UserError msg_secret_edit_name_required"
        with self.assertRaises(UserError) as cm:
            SecretManager.edit('', None, 'nouvelle_valeur')

        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_secret_edit_name_required'))

    @with_transaction()
    def test_secret_manager_edit_empty_new_value_raises(self):
        "SecretManager.edit sans new_value : UserError msg_new_value_required"
        name = _unique_secret_name()
        SecretManager.save(name, 'valeur-initiale')

        with self.assertRaises(UserError) as cm:
            SecretManager.edit(name, None, '')

        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_new_value_required'))

    @with_transaction()
    def test_secret_manager_save_no_double_encryption(self):
        "SecretManager.save chiffre une seule fois la valeur en clair"
        plain_value = 'clair'
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret = SecretManager.save(name, plain_value, personalized_key=custom_key)

        self.assertIsNotNone(secret)
        self.assertNotEqual(secret.value, plain_value)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), plain_value)

    @with_transaction()
    def test_is_encrypted_plain_value_is_false(self):
        "Valeur en clair ou vide : is_encrypted renvoie False"
        self.assertFalse(SecretManager.is_encrypted('clair'))
        self.assertFalse(SecretManager.is_encrypted(''))
        self.assertFalse(SecretManager.is_encrypted(None))

    @with_transaction()
    def test_is_encrypted_instance_token_without_key(self):
        "Jeton chiffré avec la clé d'instance : True sans key"
        encrypted = CryptoManager.encrypt('secret')
        self.assertTrue(SecretManager.is_encrypted(encrypted))

    @with_transaction()
    def test_is_encrypted_custom_key_requires_matching_key(self):
        "Jeton clé perso : False sans key, True avec bonne key, False avec mauvaise key"
        custom_key = CryptoManager.keygen()
        wrong_key = CryptoManager.keygen()
        encrypted = CryptoManager.encrypt('secret', custom_key)

        self.assertFalse(SecretManager.is_encrypted(encrypted))
        self.assertTrue(SecretManager.is_encrypted(encrypted, custom_key))
        self.assertFalse(SecretManager.is_encrypted(encrypted, wrong_key))

    @with_transaction()
    def test_is_encrypted_non_string_types_return_false(self):
        "Types non str (int, bytes, list) : is_encrypted renvoie False"
        self.assertFalse(SecretManager.is_encrypted(42))
        self.assertFalse(SecretManager.is_encrypted(b'gAAAAABtoken'))
        self.assertFalse(SecretManager.is_encrypted(['token']))

    @with_transaction()
    def test_is_encrypted_corrupted_token_returns_false(self):
        "Jeton tronqué, altéré ou pseudo-Fernet : is_encrypted renvoie False"
        encrypted = CryptoManager.encrypt('secret')
        mid = len(encrypted) // 2
        corrupted = (
            encrypted[:mid]
            + ('A' if encrypted[mid] != 'A' else 'B')
            + encrypted[mid + 1:]
        )

        self.assertFalse(SecretManager.is_encrypted(encrypted[:-8]))
        self.assertFalse(SecretManager.is_encrypted(encrypted + 'x'))
        self.assertFalse(SecretManager.is_encrypted(corrupted))
        self.assertFalse(
            SecretManager.is_encrypted('gAAAAABinvalid_fernet_like_token=='))

    @with_transaction()
    def test_create_preencrypted_custom_key_no_double_encryption(self):
        "Création avec valeur déjà chiffrée (clé perso) : pas de double chiffrement"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        plain_value = 'deja_chiffre'
        encrypted = CryptoManager.encrypt(plain_value, custom_key)
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': encrypted,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        self.assertEqual(secret.value, encrypted)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), plain_value)

    @with_transaction()
    def test_write_preencrypted_custom_key_no_double_encryption(self):
        "write new_value déjà chiffrée (clé perso) : pas de double chiffrement"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()
        new_plain = 'nouveau'
        new_encrypted = CryptoManager.encrypt(new_plain, custom_key)

        secret, = Secret.create([{
            'name': name,
            'value': 'initial',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        Secret.write([secret], {
            'new_value': new_encrypted,
            'decryption_key': custom_key,
        })

        secret = Secret(secret.id)
        self.assertEqual(secret.value, new_encrypted)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), new_plain)

    @with_transaction()
    def test_create_with_default_key(self):
        "Création sans clé personnelle : déchiffrement avec la clé d'instance"
        config.set('asp_secret_manager', 'key', CryptoManager.keygen())

        Secret = Pool().get('secret.secret')
        plain_value = 'clair_defaut'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
        }])

        self.assertNotEqual(secret.value, plain_value)
        self.assertEqual(CryptoManager.decrypt(secret), plain_value)

    @with_transaction()
    def test_create_custom_key_ignored_when_use_custom_key_false(self):
        "Clé personnelle renseignée sans case cochée : chiffrement clé d'instance"
        Secret = Pool().get('secret.secret')
        plain_value = 'clair'
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': False,
        }])

        self.assertFalse(secret.use_custom_key)
        self.assertNotEqual(secret.value, plain_value)
        self.assertEqual(secret.get_value_decrypted(), plain_value)

    @with_transaction()
    def test_use_custom_key_persists(self):
        "use_custom_key=True est persisté en base"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'clair',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        self.assertTrue(Secret(secret.id).use_custom_key)

    @with_transaction()
    def test_write_use_custom_key_immutable(self):
        "write use_custom_key=False ignoré : use_custom_key reste True"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()
        new_name = _unique_secret_name('renamed')

        secret, = Secret.create([{
            'name': name,
            'value': 'clair',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        Secret.write([secret], {
            'use_custom_key': False,
            'name': new_name,
        })

        secret = Secret(secret.id)
        self.assertTrue(secret.use_custom_key)
        self.assertEqual(secret.name, new_name)

    @with_transaction()
    def test_get_value_decrypted_without_key_default_cipher(self):
        "Création sans clé perso : get_value_decrypted() sans argument"
        config.set('asp_secret_manager', 'key', CryptoManager.keygen())

        Secret = Pool().get('secret.secret')
        plain_value = 'clair_sans_cle'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
        }])

        self.assertEqual(secret.get_value_decrypted(), plain_value)

    @with_transaction()
    def test_show_wizard_displays_decrypted_value(self):
        "Assistant Afficher : valeur déchiffrée dans l'écran résultat"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        plain_value = 'visible'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        session_id, result = self._run_show_wizard(secret, custom_key)

        self.assertEqual(
            result['view']['defaults']['decrypted_value'], plain_value)
        Wizard = Pool().get('secret.show', type='wizard')
        Wizard.delete(session_id)

        "write decryption_key seul : write_date inchangé"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'clair',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        write_date_before, = Secret.read([secret.id], ['write_date'])
        self.assertIsNone(write_date_before['write_date'])

        Secret.write([secret], {'decryption_key': custom_key})

        write_date_after, = Secret.read([secret.id], ['write_date'])
        self.assertIsNone(write_date_after['write_date'])

    @with_transaction()
    def test_write_empty_values_is_no_op(self):
        "write sans valeurs : pas d'erreur, write_date inchangé"
        Secret = Pool().get('secret.secret')
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'clair',
        }])

        write_date_before, = Secret.read([secret.id], ['write_date'])
        self.assertIsNone(write_date_before['write_date'])

        Secret.write([secret], {})

        write_date_after, = Secret.read([secret.id], ['write_date'])
        self.assertIsNone(write_date_after['write_date'])

    @with_transaction()
    def test_write_only_decryption_key_is_no_op(self):
        "write new_value + bonne clé : value change, name inchangé"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()
        old_plain = 'ancien'
        new_plain = 'nouveau'

        secret, = Secret.create([{
            'name': name,
            'value': old_plain,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        Secret.write([secret], {
            'new_value': new_plain,
            'decryption_key': custom_key,
        })

        secret = Secret(secret.id)
        self.assertEqual(name, secret.name)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), new_plain)

    @with_transaction()
    def test_write_rename_secret(self):
        "write rename name : retrouvable sous le nouveau nom"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        old_name = _unique_secret_name('old')
        new_name = _unique_secret_name('new')

        secret, = Secret.create([{
            'name': old_name,
            'value': 'valeur',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        Secret.write([secret], {'name': new_name})

        self.assertFalse(Secret.search([('name', '=', old_name)]))
        self.assertTrue(Secret.search([('name', '=', new_name)]))

    @with_transaction()
    def test_get_value_decrypted_custom_key_without_key_raises(self):
        "get_value_decrypted() sans clé si use_custom_key=True : UserError"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'secret',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        with self.assertRaises(UserError) as cm:
            secret.get_value_decrypted()

        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_encryption_key_required'))

    @with_transaction()
    def test_crypto_manager_empty_key_raises_key_required(self):
        "CryptoManager avec key='' : UserError msg_key_required"
        with self.assertRaises(UserError) as cm:
            CryptoManager.encrypt('secret', '')

        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_key_required'))

    @with_transaction()
    def test_write_new_value_wrong_key_raises(self):
        "write new_value + mauvaise clé : UserError, value inchangée"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        wrong_key = CryptoManager.keygen()
        name = _unique_secret_name()
        plain_value = 'inchangé'

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        old_ciphertext = secret.value

        with self.assertRaises(UserError):
            Secret.write([secret], {
                'new_value': 'tentative',
                'decryption_key': wrong_key,
            })

        secret = Secret(secret.id)
        self.assertEqual(secret.value, old_ciphertext)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), plain_value)

    @with_transaction()
    def test_write_rename_to_existing_name_raises(self):
        "write rename vers name existant : UserError"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        existing_name = _unique_secret_name('existing')
        other_name = _unique_secret_name('other')

        Secret.create([{
            'name': existing_name,
            'value': 'premier',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        secret, = Secret.create([{
            'name': other_name,
            'value': 'deuxieme',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        with self.assertRaises(UserError):
            Secret.write([secret], {'name': existing_name})

    @with_transaction()
    def test_ui_fields_not_sql_columns(self):
        "Champs UI Function non persistés en SQL"
        Secret = Pool().get('secret.secret')
        table = Secret.__table_handler__('asp_SecretManager')

        for column in (
                'decryption_key', 'new_value', 'custom_key'):
            self.assertFalse(table.column_exist(column))

    @with_transaction()
    def test_write_new_value_stored_encrypted(self):
        "Après write new_value, la valeur SQL n'est pas en clair"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()
        new_plain = 'secret_chiffre'

        secret, = Secret.create([{
            'name': name,
            'value': 'initial',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        Secret.write([secret], {
            'new_value': new_plain,
            'decryption_key': custom_key,
        })

        secret = Secret(secret.id)
        self.assertNotEqual(secret.value, new_plain)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), new_plain)

    @with_transaction()
    def test_config_key_encrypt_decrypt(self):
        "Clé via config.set : aller-retour encrypt/decrypt"
        key = CryptoManager.keygen()
        config.set('asp_secret_manager', 'key', key)

        encrypted = CryptoManager.encrypt('plain')
        self.assertEqual(CryptoManager.decrypt(encrypted), 'plain')

    @with_transaction()
    def test_key_file_permissions_ok(self):
        "key_file en chmod 0600 : chiffrement OK"
        path, key = self._write_key_file(0o600)
        config.set('asp_secret_manager', 'key_file', path)

        encrypted = CryptoManager.encrypt('secret')
        self.assertEqual(CryptoManager.decrypt(encrypted), 'secret')

    @with_transaction()
    def test_key_file_permissions_too_open_raises(self):
        "key_file en chmod 0644 : UserError (droits trop permissifs)"
        path, key = self._write_key_file(0o644)
        config.set('asp_secret_manager', 'key_file', path)

        with self.assertRaises(UserError) as cm:
            CryptoManager.encrypt('secret')
        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_key_file_permissions', mode=oct(0o644)))

    @with_transaction()
    def test_key_file_missing_raises_user_error(self):
        "key_file inexistant : UserError, pas FileNotFoundError"
        path = os.path.join(
            tempfile.gettempdir(),
            f'asp_secret_manager_missing_{uuid.uuid4().hex}')
        config.set('asp_secret_manager', 'key_file', path)

        with self.assertLogs(
                'trytond.modules.asp_SecretManager.tools',
                level='WARNING') as log_ctx:
            with self.assertRaises(UserError) as cm:
                CryptoManager.encrypt('secret')
        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_key_file_unreadable'))
        self.assertIn(path, '\n'.join(log_ctx.output))

    @with_transaction()
    def test_no_key_source_default_cipher_falsy(self):
        "Aucune source de clé : default_cipher falsy et encrypt → UserError"
        _clear_instance_key_config()
        self.assertFalse(CryptoManager.default_cipher)
        with self.assertRaises(UserError):
            CryptoManager.encrypt('x')

    @with_transaction()
    def test_default_cipher_extract_timestamp(self):
        "Garde-fou consommateurs : extract_timestamp sur jeton produit"
        config.set('asp_secret_manager', 'key', CryptoManager.keygen())

        encrypted = CryptoManager.encrypt('token_test')
        timestamp = CryptoManager.default_cipher.extract_timestamp(
            encrypted.encode())
        self.assertIsNotNone(timestamp)

    @with_transaction()
    def test_decrypt_with_old_key(self):
        "Secret créé sous K1 : déchiffrable avec key=K2 et old_key=K1"
        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        config.set(_CONFIG_SECTION, 'key', k1)
        encrypted = CryptoManager.encrypt('secret')
        config.set(_CONFIG_SECTION, 'key', k2)
        config.set(_CONFIG_SECTION, 'old_key', k1)

        self.assertEqual(CryptoManager.decrypt(encrypted), 'secret')

    @with_transaction()
    def test_is_encrypted_true_for_old_key_token(self):
        "Jeton K1 avec old_key configurée : is_encrypted True"
        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        config.set(_CONFIG_SECTION, 'key', k1)
        encrypted = CryptoManager.encrypt('secret')
        config.set(_CONFIG_SECTION, 'key', k2)
        config.set(_CONFIG_SECTION, 'old_key', k1)

        self.assertTrue(SecretManager.is_encrypted(encrypted))

    @with_transaction()
    def test_extract_timestamp_old_key_token(self):
        "extract_timestamp OK sur un jeton signé par old_key"
        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        config.set(_CONFIG_SECTION, 'key', k1)
        encrypted = CryptoManager.encrypt('secret')
        config.set(_CONFIG_SECTION, 'key', k2)
        config.set(_CONFIG_SECTION, 'old_key', k1)

        timestamp = CryptoManager.default_cipher.extract_timestamp(
            encrypted.encode())
        self.assertIsNotNone(timestamp)

    @with_transaction()
    def test_encrypt_always_uses_primary_key(self):
        "Chiffrement avec K2+old_key K1 : déchiffrable par Fernet(K2) seul"
        from cryptography.fernet import Fernet

        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        config.set(_CONFIG_SECTION, 'key', k2)
        config.set(_CONFIG_SECTION, 'old_key', k1)

        encrypted = CryptoManager.encrypt('plain')
        self.assertEqual(
            Fernet(k2.encode()).decrypt(encrypted.encode()).decode(), 'plain')

    @with_transaction()
    def test_rotate_reencrypts_instance_secret(self):
        "Wizard nominal : rechiffrement puis déchiffrement sans old_key"
        Secret = Pool().get('secret.secret')
        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        plain_value = 'rotation_ok'
        name = _unique_secret_name()

        config.set(_CONFIG_SECTION, 'key', k1)
        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
        }])
        config.set(_CONFIG_SECTION, 'key', k2)
        config.set(_CONFIG_SECTION, 'old_key', k1)

        defaults = self._run_rotate_wizard()

        self.assertEqual(defaults['rotated_count'], 1)
        _remove_config_option('old_key')
        secret = Secret(secret.id)
        self.assertEqual(secret.get_value_decrypted(), plain_value)

    @with_transaction()
    def test_rotate_no_op_when_already_primary(self):
        "Secret déjà signé par la clé primaire : pas de rechiffrement"
        Secret = Pool().get('secret.secret')
        plain_value = 'deja_primaire'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
        }])
        old_ciphertext = secret.value

        defaults = self._run_rotate_wizard()

        self.assertEqual(defaults['rotated_count'], 0)
        self.assertGreaterEqual(defaults['already_current_count'], 1)
        secret = Secret(secret.id)
        self.assertEqual(secret.value, old_ciphertext)

    @with_transaction()
    def test_rotate_skips_custom_key_secrets(self):
        "Secrets à clé personnelle ignorés par le wizard"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name('custom')

        secret, = Secret.create([{
            'name': name,
            'value': 'perso',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        old_ciphertext = secret.value

        defaults = self._run_rotate_wizard()

        self.assertGreaterEqual(defaults['custom_key_count'], 1)
        secret = Secret(secret.id)
        self.assertEqual(secret.value, old_ciphertext)

    @with_transaction()
    def test_rotate_counts_undecryptable_as_failed(self):
        "Jeton avec clé tierce : failed_count=1, valeur inchangée"
        Secret = Pool().get('secret.secret')
        k_other = CryptoManager.keygen()
        k_current = CryptoManager.keygen()
        name = _unique_secret_name('undecryptable')

        config.set(_CONFIG_SECTION, 'key', k_other)
        secret, = Secret.create([{
            'name': name,
            'value': 'inaccessible',
        }])
        old_ciphertext = secret.value
        config.set(_CONFIG_SECTION, 'key', k_current)
        _remove_config_option('old_key')

        defaults = self._run_rotate_wizard()

        self.assertEqual(defaults['failed_count'], 1)
        secret = Secret(secret.id)
        self.assertEqual(secret.value, old_ciphertext)

    @with_transaction()
    def test_rotate_without_old_key_and_stale_secret(self):
        "Sans old_key, secret ancienne clé : échec sans exception"
        Secret = Pool().get('secret.secret')
        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        name = _unique_secret_name('stale')

        config.set(_CONFIG_SECTION, 'key', k1)
        secret, = Secret.create([{
            'name': name,
            'value': 'stale',
        }])
        config.set(_CONFIG_SECTION, 'key', k2)
        _remove_config_option('old_key')

        defaults = self._run_rotate_wizard()

        self.assertGreaterEqual(defaults['failed_count'], 1)

    @with_transaction()
    def test_old_key_invalid_format_raises(self):
        "old_key invalide : UserError msg_invalid_fernet_key_format au decrypt"
        encrypted = CryptoManager.encrypt('secret')
        config.set(_CONFIG_SECTION, 'old_key', 'pas-une-cle')

        with self.assertRaises(UserError) as cm:
            CryptoManager.decrypt(encrypted)

        self.assertEqual(
            cm.exception.message,
            _('asp_SecretManager.msg_invalid_fernet_key_format'))

    @with_transaction()
    def test_default_start_counters(self):
        "default_start : compteurs cohérents avec la base"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        Secret.create([{
            'name': _unique_secret_name('inst1'),
            'value': 'inst1',
        }])
        Secret.create([{
            'name': _unique_secret_name('inst2'),
            'value': 'inst2',
        }])
        Secret.create([{
            'name': _unique_secret_name('perso'),
            'value': 'perso',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        config.set(_CONFIG_SECTION, 'old_key', CryptoManager.keygen())

        Wizard = Pool().get('secret.rotate', type='wizard')
        session_id, _, _ = Wizard.create()
        result = Wizard.execute(session_id, {}, 'start')
        defaults = result['view']['defaults']

        self.assertGreaterEqual(defaults['secret_count'], 2)
        self.assertGreaterEqual(defaults['custom_key_count'], 1)
        self.assertTrue(defaults['old_key_configured'])
        self.assertEqual(defaults['encrypted_field_count'], 0)

    def _mock_instance_encrypted_models(self, records, field_name='encrypted_char'):
        char_field = type('CharField', (), {'_type': 'char'})()

        class FakeModel:
            __name__ = 'test.encrypted.mixin'
            _instance_encrypted_fields = (field_name,)
            _fields = {field_name: char_field}

            @classmethod
            def search(cls, domain):
                return list(records)

            @classmethod
            def write(cls, *args):
                actions = iter(args)
                for recs, values in zip(actions, actions):
                    for record in recs:
                        for key, val in values.items():
                            setattr(record, key, val)

        def fake_iter(cls):
            yield FakeModel, (field_name,)

        return fake_iter

    @with_transaction()
    def test_rotate_reencrypts_instance_encrypted_field(self):
        "Champ métier Fernet (k1) : rechiffrement via wizard"
        from unittest.mock import patch

        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        plain_value = 'champ_metier'
        config.set(_CONFIG_SECTION, 'key', k1)
        token_k1 = CryptoManager.encrypt(plain_value)
        config.set(_CONFIG_SECTION, 'key', k2)
        config.set(_CONFIG_SECTION, 'old_key', k1)

        record = type('Rec', (), {'id': 1, 'encrypted_char': token_k1})()
        fake_iter = self._mock_instance_encrypted_models([record])

        with patch.object(
                RotateKey, '_iter_instance_encrypted_models', fake_iter):
            defaults = self._run_rotate_wizard()

        self.assertEqual(defaults['rotated_count'], 1)
        self.assertNotEqual(record.encrypted_char, token_k1)
        _remove_config_option('old_key')
        self.assertEqual(
            CryptoManager.decrypt(record.encrypted_char), plain_value)

    @with_transaction()
    def test_rotate_skips_instance_encrypted_field_already_primary(self):
        "Champ métier déjà signé par la clé primaire : pas de write"
        from unittest.mock import patch

        plain_value = 'deja_primaire_metier'
        token = CryptoManager.encrypt(plain_value)
        record = type('Rec', (), {'id': 2, 'encrypted_char': token})()
        writes = []
        char_field = type('CharField', (), {'_type': 'char'})()

        class TrackedFakeModel:
            __name__ = 'test.encrypted.mixin'
            _instance_encrypted_fields = ('encrypted_char',)
            _fields = {'encrypted_char': char_field}

            @classmethod
            def search(cls, domain):
                return [record]

            @classmethod
            def write(cls, *args):
                writes.append(args)

        def tracked_iter(cls):
            yield TrackedFakeModel, ('encrypted_char',)

        with patch.object(
                RotateKey, '_iter_instance_encrypted_models', tracked_iter):
            defaults = self._run_rotate_wizard()

        self.assertEqual(defaults['rotated_count'], 0)
        self.assertGreaterEqual(defaults['already_current_count'], 1)
        self.assertEqual(writes, [])
        self.assertEqual(record.encrypted_char, token)

    @with_transaction()
    def test_rotate_instance_encrypted_field_third_party_key_failed(self):
        "Champ métier jeton clé tierce : échec, valeur inchangée"
        from unittest.mock import patch

        k_other = CryptoManager.keygen()
        k_current = CryptoManager.keygen()
        config.set(_CONFIG_SECTION, 'key', k_other)
        token = CryptoManager.encrypt('inaccessible_metier')
        config.set(_CONFIG_SECTION, 'key', k_current)
        _remove_config_option('old_key')

        record = type('Rec', (), {'id': 3, 'encrypted_char': token})()
        fake_iter = self._mock_instance_encrypted_models([record])

        with patch.object(
                RotateKey, '_iter_instance_encrypted_models', fake_iter):
            defaults = self._run_rotate_wizard()

        self.assertEqual(defaults['failed_count'], 1)
        self.assertEqual(record.encrypted_char, token)

    def _usage_log_char_values(self, log):
        UsageLog = Pool().get('secret.usage.log')
        values = []
        for field_name, field in UsageLog._fields.items():
            if field._type in ('char', 'selection'):
                val = getattr(log, field_name, None)
                if val:
                    values.append(str(val))
        return values

    @with_transaction()
    def test_usage_log_create_custom_key_encrypt_success(self):
        "Création clé perso : journal encrypt / succès / ui / clé perso"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        plain_value = 'clair'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'encrypt'),
            ('outcome', '=', 'success'),
            ('channel', '=', 'ui'),
        ])
        self.assertEqual(log.secret_name, name)
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_create_without_custom_key_encrypt_success(self):
        "Création clé instance : journal encrypt / succès / clé perso fausse"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'clair',
        }])

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'encrypt'),
            ('outcome', '=', 'success'),
        ])
        self.assertFalse(log.use_custom_key)

    @with_transaction()
    def test_usage_log_keygen_wizard_no_line(self):
        "Génération de clé : aucune ligne de journal"
        UsageLog = Pool().get('secret.usage.log')
        Wizard = Pool().get('secret.generate', type='wizard')
        before = UsageLog.search_count([])

        session_id, _, _ = Wizard.create()
        Wizard.execute(session_id, {}, 'start')

        self.assertEqual(UsageLog.search_count([]), before)

    @with_transaction()
    def test_generate_key_wizard_key_not_in_session_after_start(self):
        "Génération clé : defaults RPC OK, clé absente de la session"
        Wizard = Pool().get('secret.generate', type='wizard')
        Session = Pool().get('ir.session.wizard')

        session_id, _, _ = Wizard.create()
        result = Wizard.execute(session_id, {}, 'start')
        key = result['view']['defaults']['key']

        self.assertTrue(key)

        session_data = Session(session_id).data
        if isinstance(session_data, bytes):
            session_data = session_data.decode('utf-8')
        self.assertNotIn(key, session_data)

        Wizard.delete(session_id)

    @with_transaction()
    def test_generate_key_wizard_key_not_in_session_after_end(self):
        "Fermeture GTK : clé absente de la session malgré payload client"
        Wizard = Pool().get('secret.generate', type='wizard')
        Session = Pool().get('ir.session.wizard')

        session_id, _, _ = Wizard.create()
        result = Wizard.execute(session_id, {}, 'start')
        key = result['view']['defaults']['key']
        self.assertTrue(key)

        Wizard.execute(session_id, {'start': {'key': key}}, 'end')

        session_data = Session(session_id).data
        if isinstance(session_data, bytes):
            session_data = session_data.decode('utf-8')
        self.assertNotIn(key, session_data)

        Wizard.delete(session_id)

    @with_transaction()
    def test_usage_log_show_value_success(self):
        "show_value : show / succès"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'visible',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        secret.decryption_key = custom_key
        self._run_show_wizard(secret, custom_key)

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'show'),
            ('outcome', '=', 'success'),
        ])
        self.assertEqual(log.channel, 'ui')
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_show_value_instance_success(self):
        "show_value instance : show / clé perso fausse"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'visible',
        }])

        self._run_show_wizard(secret)

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'show'),
            ('outcome', '=', 'success'),
        ])
        self.assertFalse(log.use_custom_key)

    @with_transaction()
    def test_usage_log_start_edit_unlock_success(self):
        "start_edit : unlock / succès"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'edit',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        self._run_edit_wizard(secret, 'modifié', custom_key)

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'unlock'),
            ('outcome', '=', 'success'),
        ])
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_start_edit_instance_unlock_success(self):
        "start_edit instance : unlock / clé perso fausse"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'edit',
        }])

        self._run_edit_wizard(secret, 'modifié')

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'unlock'),
            ('outcome', '=', 'success'),
        ])
        self.assertFalse(log.use_custom_key)

    @with_transaction()
    def test_usage_log_write_new_value_reencrypt_success(self):
        "write new_value : reencrypt / succès"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'initial',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        Secret.write([secret], {
            'new_value': 'nouveau',
            'decryption_key': custom_key,
        })

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'reencrypt'),
            ('outcome', '=', 'success'),
        ], order=[('date', 'DESC')], limit=1)
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_write_new_value_instance_reencrypt_success(self):
        "write new_value instance : reencrypt / clé perso fausse"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'initial',
        }])

        Secret.write([secret], {'new_value': 'nouveau'})

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'reencrypt'),
            ('outcome', '=', 'success'),
        ], order=[('date', 'DESC')], limit=1)
        self.assertFalse(log.use_custom_key)

    @with_transaction()
    def test_show_wizard_no_sensitive_data_in_session_after_show(self):
        "Assistant Afficher : clé absente de la session après transition show"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        plain_value = 'session_test'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        session_id, result = self._run_show_wizard(secret, custom_key)
        session_data = self._session_data_str(session_id)

        self.assertEqual(
            result['view']['defaults']['decrypted_value'], plain_value)
        self.assertNotIn(custom_key, session_data)
        self.assertNotIn(plain_value, session_data)

        Wizard = Pool().get('secret.show', type='wizard')
        Wizard.delete(session_id)

    @with_transaction()
    def test_show_wizard_no_sensitive_data_after_gtk_end(self):
        "Fermeture GTK : clair et clé absents malgré payload client"
        Secret = Pool().get('secret.secret')
        Wizard = Pool().get('secret.show', type='wizard')
        custom_key = CryptoManager.keygen()
        plain_value = 'gtk_end'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        with Transaction().set_context(**self._secret_wizard_context(secret)):
            session_id, _, _ = Wizard.create()
            ask_result = Wizard.execute(session_id, {}, 'start')
            ask_data = dict(ask_result['view']['defaults'])
            ask_data['decryption_key'] = custom_key
            Wizard.execute(session_id, {'ask': ask_data}, 'show')
            Wizard.execute(session_id, {
                'ask': ask_data,
                'result': {'decrypted_value': plain_value},
            }, 'end')

        session_data = self._session_data_str(session_id)
        self.assertNotIn(custom_key, session_data)
        self.assertNotIn(plain_value, session_data)

        Wizard.delete(session_id)

    @with_transaction()
    def test_show_wizard_delete_no_sensitive_data_in_session(self):
        "Fermeture Sao : clair et clé absents après Wizard.delete"
        Secret = Pool().get('secret.secret')
        Wizard = Pool().get('secret.show', type='wizard')
        custom_key = CryptoManager.keygen()
        plain_value = 'sao_delete'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        session_id, result = self._run_show_wizard(secret, custom_key)
        decrypted = result['view']['defaults']['decrypted_value']
        session_data = self._session_data_str(session_id)
        self.assertNotIn(custom_key, session_data)
        self.assertNotIn(decrypted, session_data)

        Wizard.delete(session_id)

    @with_transaction()
    def test_edit_wizard_no_sensitive_data_in_session_after_save(self):
        "Assistant Modifier : new_value et clé absents après save"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        new_plain = 'modifié_session'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'initial',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        session_id, _ = self._run_edit_wizard(secret, new_plain, custom_key)
        session_data = self._session_data_str(session_id)

        self.assertNotIn(custom_key, session_data)
        self.assertNotIn(new_plain, session_data)

        Wizard = Pool().get('secret.edit', type='wizard')
        Wizard.delete(session_id)

    @with_transaction()
    def test_show_wizard_wrong_key_session_clean_ciphertext_unchanged(self):
        "Mauvaise clé Afficher : UserError, ciphertext inchangé, session propre"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        wrong_key = CryptoManager.keygen()
        plain_value = 'inchangé_show'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        old_ciphertext = secret.value

        with self.assertRaises(UserError):
            self._run_show_wizard(secret, wrong_key)

        secret = Secret(secret.id)
        self.assertEqual(secret.value, old_ciphertext)

        Session = Pool().get('ir.session.wizard')
        sessions = Session.search([])
        for session in sessions:
            session_data = self._session_data_str(session.id)
            self.assertNotIn(wrong_key, session_data)
            self.assertNotIn(plain_value, session_data)

    @with_transaction()
    def test_edit_wizard_name_unchanged(self):
        "Assistant Modifier : le nom reste inchangé après modification de la valeur"
        Secret = Pool().get('secret.secret')
        custom_key = CryptoManager.keygen()
        old_name = _unique_secret_name('old')

        secret, = Secret.create([{
            'name': old_name,
            'value': 'valeur',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        self._run_edit_wizard(secret, 'nouvelle_valeur', custom_key)

        secret = Secret(secret.id)
        self.assertEqual(secret.name, old_name)
        self.assertEqual(
            secret.get_value_decrypted(key=custom_key), 'nouvelle_valeur')

    @with_transaction()
    def test_edit_wizard_default_start_use_custom_key(self):
        "default_start : use_custom_key reflète le secret"
        Secret = Pool().get('secret.secret')
        Wizard = Pool().get('secret.edit', type='wizard')
        custom_key = CryptoManager.keygen()

        secret_inst, = Secret.create([{
            'name': _unique_secret_name('inst'),
            'value': 'valeur',
        }])
        with Transaction().set_context(**self._secret_wizard_context(
                secret_inst)):
            session_id, _, _ = Wizard.create()
            result = Wizard.execute(session_id, {}, 'start')
            self.assertFalse(result['view']['defaults']['use_custom_key'])

        secret_perso, = Secret.create([{
            'name': _unique_secret_name('perso'),
            'value': 'valeur',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        with Transaction().set_context(**self._secret_wizard_context(
                secret_perso)):
            session_id, _, _ = Wizard.create()
            result = Wizard.execute(session_id, {}, 'start')
            self.assertTrue(result['view']['defaults']['use_custom_key'])

    @with_transaction()
    def test_usage_log_never_stores_secret_material(self):
        "Journal : aucune clé, clair ni ciphertext dans les champs"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        plain_value = 'matériel_secret'
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        self._run_show_wizard(secret, custom_key)

        for log in UsageLog.search([]):
            joined = ' '.join(self._usage_log_char_values(log))
            self.assertNotIn(custom_key, joined)
            self.assertNotIn(plain_value, joined)
            self.assertNotIn(secret.value, joined)

    @with_transaction()
    def test_usage_log_must_isolate(self):
        "_must_isolate : échec ou readonly ; succès en TX écrivable"
        UsageLog = Pool().get('secret.usage.log')
        from unittest.mock import patch

        self.assertTrue(UsageLog._must_isolate('failure'))
        self.assertFalse(UsageLog._must_isolate('success'))

        with patch.object(
                Transaction, 'new_transaction') as mock_new_tx:
            mock_new_tx.return_value.__enter__ = lambda s: Transaction()
            mock_new_tx.return_value.__exit__ = lambda s, *a: None
            UsageLog.log_usage(
                'encrypt', outcome='failure', secret_name='test_iso')
            mock_new_tx.assert_called_once_with(autocommit=True)

    @with_transaction()
    def test_usage_log_failure_persisted_despite_user_error(self):
        "Échec create sans clé : ligne persistée malgré UserError"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        from trytond.transaction import without_check_access
        name = _unique_secret_name()

        with self.assertRaises(UserError):
            Secret.create([{
                'name': name,
                'value': 'clair',
                'use_custom_key': True,
            }])

        with Transaction().new_transaction():
            with without_check_access():
                logs = UsageLog.search([
                    ('secret_name', '=', name),
                    ('action', '=', 'encrypt'),
                    ('outcome', '=', 'failure'),
                    ('failure_reason', '=', 'key_missing'),
                ])
                self.assertEqual(len(logs), 1)
                self.assertTrue(logs[0].use_custom_key)
                UsageLog.delete(logs)

    @with_transaction()
    def test_usage_log_secret_manager_get_no_line(self):
        "SecretManager.get : aucune ligne de journal"
        UsageLog = Pool().get('secret.usage.log')
        name = _unique_secret_name()

        SecretManager.save(name, 'valeur')
        UsageLog.delete(UsageLog.search([]))

        SecretManager.get(name)

        self.assertEqual(UsageLog.search_count([]), 0)

    @with_transaction()
    def test_usage_log_secret_manager_edit_single_reencrypt(self):
        "SecretManager.edit : une seule ligne reencrypt / api"
        UsageLog = Pool().get('secret.usage.log')
        name = _unique_secret_name()

        secret = SecretManager.save(name, 'initial')
        UsageLog.delete(UsageLog.search([]))

        SecretManager.edit(name, None, 'modifié')

        logs = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'reencrypt'),
            ('outcome', '=', 'success'),
            ('channel', '=', 'api'),
        ])
        self.assertEqual(len(logs), 1)

    @with_transaction()
    def test_usage_log_secret_manager_edit_instance_decrypt_failure(self):
        "SecretManager.edit instance : reencrypt / échec / api"
        UsageLog = Pool().get('secret.usage.log')
        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        name = _unique_secret_name()

        config.set(_CONFIG_SECTION, 'key', k1)
        SecretManager.save(name, 'secret')
        UsageLog.delete(UsageLog.search([]))
        config.set(_CONFIG_SECTION, 'key', k2)
        _remove_config_option('old_key')

        with self.assertRaises(UserError):
            SecretManager.edit(name, None, 'nouveau')

        log, = UsageLog.search([
            ('secret_name', '=', name),
            ('action', '=', 'reencrypt'),
            ('outcome', '=', 'failure'),
            ('channel', '=', 'api'),
        ])
        self.assertFalse(log.use_custom_key)

    @with_transaction()
    def test_usage_log_secret_manager_save_instance_encrypt_api(self):
        "SecretManager.save instance : encrypt / succès / api"
        UsageLog = Pool().get('secret.usage.log')
        name = _unique_secret_name()

        secret = SecretManager.save(name, 'valeur-api')

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'encrypt'),
            ('outcome', '=', 'success'),
            ('channel', '=', 'api'),
        ])
        self.assertFalse(log.use_custom_key)

    @with_transaction()
    def test_usage_log_secret_manager_save_custom_key_encrypt_api(self):
        "SecretManager.save clé perso : encrypt / succès / api"
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret = SecretManager.save(
            name, 'valeur-api', personalized_key=custom_key)

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'encrypt'),
            ('outcome', '=', 'success'),
            ('channel', '=', 'api'),
        ])
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_secret_manager_edit_custom_key_single_reencrypt(self):
        "SecretManager.edit clé perso : une seule ligne reencrypt / api"
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret = SecretManager.save(
            name, 'initial', personalized_key=custom_key)
        UsageLog.delete(UsageLog.search([]))

        SecretManager.edit(name, custom_key, 'modifié')

        logs = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'reencrypt'),
            ('outcome', '=', 'success'),
            ('channel', '=', 'api'),
        ])
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].use_custom_key)

    @with_transaction()
    def test_usage_log_show_value_wrong_key_failure(self):
        "show_value mauvaise clé : show / échec / decrypt_fail"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        wrong_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'visible',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        with self.assertRaises(UserError):
            self._run_show_wizard(secret, wrong_key)

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'show'),
            ('outcome', '=', 'failure'),
            ('failure_reason', '=', 'decrypt_fail'),
        ])
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_edit_wizard_wrong_key_failure(self):
        "Assistant Modifier mauvaise clé : unlock / échec / decrypt_fail"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        wrong_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'edit',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])

        with self.assertRaises(UserError):
            self._run_edit_wizard(secret, 'tentative', wrong_key)

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'unlock'),
            ('outcome', '=', 'failure'),
            ('failure_reason', '=', 'decrypt_fail'),
        ])
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_write_new_value_wrong_key_failure(self):
        "write new_value mauvaise clé : reencrypt / échec / decrypt_fail"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        wrong_key = CryptoManager.keygen()
        name = _unique_secret_name()

        secret, = Secret.create([{
            'name': name,
            'value': 'initial',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        UsageLog.delete(UsageLog.search([('secret', '=', secret.id)]))

        with self.assertRaises(UserError):
            Secret.write([secret], {
                'new_value': 'tentative',
                'decryption_key': wrong_key,
            })

        log, = UsageLog.search([
            ('secret', '=', secret.id),
            ('action', '=', 'reencrypt'),
            ('outcome', '=', 'failure'),
            ('failure_reason', '=', 'decrypt_fail'),
        ])
        self.assertTrue(log.use_custom_key)

    @with_transaction()
    def test_usage_log_write_preencrypted_no_line(self):
        "write jeton déjà chiffré : aucune ligne reencrypt"
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        custom_key = CryptoManager.keygen()
        name = _unique_secret_name()
        new_encrypted = CryptoManager.encrypt('nouveau', custom_key)

        secret, = Secret.create([{
            'name': name,
            'value': 'initial',
            'custom_key': custom_key,
            'use_custom_key': True,
        }])
        UsageLog.delete(UsageLog.search([('secret', '=', secret.id)]))

        Secret.write([secret], {
            'new_value': new_encrypted,
            'decryption_key': custom_key,
        })

        self.assertEqual(UsageLog.search_count([
            ('secret', '=', secret.id),
            ('action', '=', 'reencrypt'),
        ]), 0)

    @with_transaction()
    def test_usage_log_rotate_wizard_success(self):
        "Wizard rotation : rotate / succès / canal ui"
        UsageLog = Pool().get('secret.usage.log')
        Secret = Pool().get('secret.secret')
        k1 = CryptoManager.keygen()
        k2 = CryptoManager.keygen()
        name = _unique_secret_name()

        config.set(_CONFIG_SECTION, 'key', k1)
        secret, = Secret.create([{'name': name, 'value': 'rotation'}])
        config.set(_CONFIG_SECTION, 'key', k2)
        config.set(_CONFIG_SECTION, 'old_key', k1)
        UsageLog.delete(UsageLog.search([]))

        self._run_rotate_wizard()

        log, = UsageLog.search([
            ('action', '=', 'rotate'),
            ('outcome', '=', 'success'),
            ('secret_name', '=', name),
        ])
        self.assertEqual(log.channel, 'ui')
        self.assertEqual(log.secret, secret)

    @with_transaction()
    def test_usage_log_delete_success(self):
        "Suppression : delete / succès, secret détaché, nom conservé"
        UsageLog = Pool().get('secret.usage.log')
        Secret = Pool().get('secret.secret')
        name = _unique_secret_name()

        secret, = Secret.create([{'name': name, 'value': 'x'}])
        UsageLog.delete(UsageLog.search([('secret', '=', secret.id)]))

        Secret.delete([secret])

        log, = UsageLog.search([
            ('action', '=', 'delete'),
            ('outcome', '=', 'success'),
            ('secret_name', '=', name),
        ])
        self.assertEqual(log.channel, 'ui')
        self.assertIsNone(log.secret)

    @with_transaction()
    def test_usage_log_rotate_wizard_failure(self):
        "Wizard rotation échec déchiffrement : rotate / failure / decrypt_fail"
        UsageLog = Pool().get('secret.usage.log')
        Secret = Pool().get('secret.secret')
        k_other = CryptoManager.keygen()
        k_current = CryptoManager.keygen()
        name = _unique_secret_name('undecryptable')

        config.set(_CONFIG_SECTION, 'key', k_other)
        Secret.create([{'name': name, 'value': 'inaccessible'}])
        config.set(_CONFIG_SECTION, 'key', k_current)
        _remove_config_option('old_key')
        UsageLog.delete(UsageLog.search([]))

        self._run_rotate_wizard()

        log, = UsageLog.search([
            ('action', '=', 'rotate'),
            ('outcome', '=', 'failure'),
            ('secret_name', '=', name),
            ('failure_reason', '=', 'decrypt_fail'),
        ])
        self.assertEqual(log.channel, 'ui')

    @with_transaction()
    def test_usage_log_purge_old_entries(self):
        "Purge : ligne > 1 an supprimée, récente conservée"
        import datetime as dt
        from dateutil.relativedelta import relativedelta
        from trytond.transaction import without_check_access

        UsageLog = Pool().get('secret.usage.log')
        Secret = Pool().get('secret.secret')
        name = _unique_secret_name()

        secret, = Secret.create([{'name': name, 'value': 'x'}])
        UsageLog.delete(UsageLog.search([]))

        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        with without_check_access():
            old_log, = UsageLog.create([{
                'date': now - relativedelta(years=1, days=1),
                'secret': secret.id,
                'secret_name': name,
                'use_custom_key': False,
                'action': 'encrypt',
                'outcome': 'success',
                'channel': 'ui',
            }])
            recent_log, = UsageLog.create([{
                'date': now,
                'secret': secret.id,
                'secret_name': name,
                'use_custom_key': False,
                'action': 'show',
                'outcome': 'success',
                'channel': 'ui',
            }])

        UsageLog.purge_old_entries()

        self.assertFalse(UsageLog.search([('id', '=', old_log.id)]))
        self.assertTrue(UsageLog.search([('id', '=', recent_log.id)]))

    @with_transaction()
    def test_usage_log_date_stored_as_utc_naive(self):
        "log_usage : date UTC naïve, proche de l'horloge UTC"
        import datetime as dt

        UsageLog = Pool().get('secret.usage.log')
        UsageLog.delete(UsageLog.search([]))

        before = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        UsageLog.log_usage('show', outcome='success', secret_name='test_utc')
        after = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

        log, = UsageLog.search([('secret_name', '=', 'test_utc')])
        self.assertIsNone(log.date.tzinfo)
        self.assertGreaterEqual(log.date, before - dt.timedelta(seconds=2))
        self.assertLessEqual(log.date, after + dt.timedelta(seconds=2))


del ModuleTestCase
