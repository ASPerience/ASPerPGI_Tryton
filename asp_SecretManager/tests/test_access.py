import uuid
from datetime import datetime

import trytond.config as config
from trytond.model import ModelSQL
from trytond.model.modelview import AccessButtonError
from trytond.model.exceptions import AccessError
from trytond.pool import Pool
from trytond.tests.test_tryton import ModuleTestCase, with_transaction
from trytond.transaction import Transaction, without_check_access

from trytond.modules.asp_SecretManager.tools import CryptoManager, SecretManager

_check_access_context = {'_check_access': True}

_CONFIG_SECTION = 'asp_secret_manager'


def _ensure_config_section():
    if not config.has_section(_CONFIG_SECTION):
        config.add_section(_CONFIG_SECTION)


def _remove_config_option(option):
    _ensure_config_section()
    if config._config.has_option(_CONFIG_SECTION, option):
        config._config.remove_option(_CONFIG_SECTION, option)
        config._cache_clear()


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


class AspSecretManagerAccessTestCase(ModuleTestCase):
    "Tests des droits d'accès asp_SecretManager"
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
        for option in ('key_file', 'old_key'):
            _remove_config_option(option)
        self.addCleanup(_restore_instance_key_config, self._saved_key_config)

    def _get_group(self, xml_id):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Group = pool.get('res.group')
        return Group(ModelData.get_id('asp_SecretManager', xml_id))

    def _create_user(self, login, group_ids):
        """Crée un utilisateur non admin avec les groupes indiqués."""
        User = Pool().get('res.user')
        existing = User.search([('login', '=', login)])
        if existing:
            User.delete(existing)
        user, = User.create([{
            'name': login,
            'login': login,
            'password': 'testpass123',
            'groups': [('add', group_ids)],
        }])
        return user

    def _create_secret(self, name=None):
        Secret = Pool().get('secret.secret')
        if name is None:
            name = f'test_acl_{uuid.uuid4().hex}'
        secret, = Secret.create([{
            'name': name,
            'value': 'valeur-test',
        }])
        return secret

    def _assert_junction_group(self, junction_xml_id, group_xml_id, junction_model):
        """Vérifie qu'un record de liaison XML pointe vers le groupe attendu."""
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Junction = pool.get(junction_model)
        group = self._get_group(group_xml_id)
        record = Junction(ModelData.get_id('asp_SecretManager', junction_xml_id))
        self.assertEqual(record.group.id, group.id)

    @with_transaction()
    def test_menu_root_bound_to_manager_group(self):
        """Menu racine : liaison menu_secret_root → group_secret_manager."""
        self._assert_junction_group(
            'menu_secret_root_group', 'group_secret_manager',
            'ir.ui.menu-res.group')

    @with_transaction()
    def test_admin_only_menus_bound_to_admin_group(self):
        """Menus liste et générer clé : réservés au groupe admin."""
        for junction_xml_id in (
                'menu_secret_list_group', 'menu_generate_key_group',
                'menu_rotate_key_group', 'menu_secret_usage_log_group'):
            self._assert_junction_group(
                junction_xml_id, 'group_secret_manager_admin',
                'ir.ui.menu-res.group')

    @with_transaction()
    def test_usage_log_menu_action_bound_to_admin_group(self):
        """Menu et action journal d'usage : groupe admin seulement."""
        self._assert_junction_group(
            'menu_secret_usage_log_group', 'group_secret_manager_admin',
            'ir.ui.menu-res.group')
        self._assert_junction_group(
            'act_secret_usage_log_group', 'group_secret_manager_admin',
            'ir.action-res.group')

    @with_transaction(context=_check_access_context)
    def test_usage_log_user_without_groups_denied(self):
        """Sans groupe : AccessError sur le journal d'usage."""
        UsageLog = Pool().get('secret.usage.log')
        user = self._create_user('test_usage_log_no_group', [])

        with Transaction().set_user(user.id):
            with self.assertRaises(AccessError):
                UsageLog.search([])
            with self.assertRaises(AccessError):
                UsageLog.read([1], ['date'])

    @with_transaction(context=_check_access_context)
    def test_usage_log_manager_group_read_denied(self):
        """Groupe gestionnaire : lecture du journal refusée."""
        group = self._get_group('group_secret_manager')
        user = self._create_user('test_usage_log_manager', [group.id])
        UsageLog = Pool().get('secret.usage.log')

        with Transaction().set_user(user.id):
            with self.assertRaises(AccessError):
                UsageLog.search([])

    @with_transaction(context=_check_access_context)
    def test_usage_log_admin_read_only(self):
        """Admin module : read/search OK ; create/write/delete refusés."""
        group = self._get_group('group_secret_manager_admin')
        user = self._create_user('test_usage_log_admin', [group.id])
        UsageLog = Pool().get('secret.usage.log')
        with without_check_access():
            log, = UsageLog.create([{
                'date': datetime.now(),
                'action': 'show',
                'outcome': 'success',
                'channel': 'ui',
                'secret_name': 'test_acl',
            }])

        with Transaction().set_user(user.id):
            UsageLog.search([])
            UsageLog.read([log.id], ['date'])

            with self.assertRaises(AccessError):
                UsageLog.create([{
                    'date': datetime.now(),
                    'action': 'show',
                    'outcome': 'success',
                    'channel': 'ui',
                }])
            with self.assertRaises(AccessError):
                UsageLog.write([log], {'secret_name': 'x'})
            with self.assertRaises(AccessError):
                UsageLog.delete([log])

    @with_transaction()
    def test_admin_only_actions_bound_to_admin_group(self):
        """Actions act_secret et wizards : groupe admin seulement."""
        for junction_xml_id in (
                'act_secret_group', 'wizard_generate_key_group',
                'wizard_rotate_key_group', 'wizard_show_value_group',
                'wizard_edit_value_group'):
            self._assert_junction_group(
                junction_xml_id, 'group_secret_manager_admin',
                'ir.action-res.group')

    @with_transaction()
    def test_admin_only_buttons_bound_to_admin_group(self):
        """Boutons show_value / start_edit : groupe admin seulement."""
        for junction_xml_id in (
                'secret_show_value_button_group',
                'secret_start_edit_button_group'):
            self._assert_junction_group(
                junction_xml_id, 'group_secret_manager_admin',
                'ir.model.button-res.group')

    @with_transaction(context=_check_access_context)
    def test_manager_group_show_value_start_edit_denied(self):
        """Groupe gestionnaire : afficher et éditer sont refusés côté serveur."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager')
        user = self._create_user('test_secret_buttons_manager', [group.id])
        Secret = Pool().get('secret.secret')

        with Transaction().set_user(user.id):
            record = Secret(secret.id)
            with self.assertRaises(AccessButtonError):
                Secret.show_value([record])
            with self.assertRaises(AccessButtonError):
                Secret.start_edit([record])

    @with_transaction(context=_check_access_context)
    def test_manager_group_show_edit_wizard_create_denied(self):
        """Groupe gestionnaire : création des wizards Afficher/Modifier refusée."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager')
        user = self._create_user('test_secret_wizard_manager', [group.id])
        context = {
            'active_model': 'secret.secret',
            'active_id': secret.id,
            'active_ids': [secret.id],
        }

        with Transaction().set_user(user.id):
            for wizard_name in ('secret.show', 'secret.edit'):
                Wizard = Pool().get(wizard_name, type='wizard')
                with Transaction().set_context(**context):
                    with self.assertRaises(AccessError):
                        Wizard.create()

    @with_transaction(context=_check_access_context)
    def test_admin_group_show_value_start_edit_allowed(self):
        """Admin module : afficher et éditer ouvrent les assistants."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager_admin')
        user = self._create_user('test_secret_buttons_admin', [group.id])
        Secret = Pool().get('secret.secret')

        with Transaction().set_user(user.id):
            record = Secret(secret.id)
            self.assertIsNotNone(Secret.show_value([record]))
            self.assertIsNotNone(Secret.start_edit([record]))

    @with_transaction(context=_check_access_context)
    def test_manager_group_edit_wizard_save_denied(self):
        """Groupe gestionnaire : transition save du wizard Modifier refusée."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager')
        user = self._create_user('test_secret_edit_save_manager', [group.id])
        context = {
            'active_model': 'secret.secret',
            'active_id': secret.id,
            'active_ids': [secret.id],
        }
        EditWizard = Pool().get('secret.edit', type='wizard')
        with without_check_access():
            with Transaction().set_context(**context):
                session_id, _, _ = EditWizard.create()
                result = EditWizard.execute(session_id, {}, 'start')
                start_data = dict(result['view']['defaults'])
                start_data['new_value'] = 'tentative'

        with Transaction().set_user(user.id):
            with Transaction().set_context(**context):
                with self.assertRaises(AccessError):
                    EditWizard.execute(session_id, {'start': start_data}, 'save')

    @with_transaction(context=_check_access_context)
    def test_admin_group_show_edit_wizard_create_allowed(self):
        """Admin module : création des wizards Afficher/Modifier autorisée."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager_admin')
        user = self._create_user('test_secret_wizard_admin', [group.id])
        context = {
            'active_model': 'secret.secret',
            'active_id': secret.id,
            'active_ids': [secret.id],
        }

        with Transaction().set_user(user.id):
            for wizard_name in ('secret.show', 'secret.edit'):
                Wizard = Pool().get(wizard_name, type='wizard')
                with Transaction().set_context(**context):
                    session_id, start_state, end_state = Wizard.create()
                self.assertEqual(start_state, 'start')
                self.assertEqual(end_state, 'end')
                Wizard.delete(session_id)

    @with_transaction(context=_check_access_context)
    def test_user_without_groups_denied_all_operations(self):
        """Sans groupe : refus read/search/create/write/delete."""
        secret = self._create_secret()
        user = self._create_user('test_secret_no_group', [])
        Secret = Pool().get('secret.secret')

        with Transaction().set_user(user.id):
            with self.assertRaises(AccessError):
                Secret.read([secret.id], ['name'])
            with self.assertRaises(AccessError):
                Secret.search([('id', '=', secret.id)])
            with self.assertRaises(AccessError):
                Secret.create([{
                    'name': f'test_acl_create_{uuid.uuid4().hex}',
                    'value': 'valeur',
                }])
            with self.assertRaises(AccessError):
                Secret.write([secret], {'value': 'autre-valeur'})
            with self.assertRaises(AccessError):
                Secret.delete([secret])

    @with_transaction(context=_check_access_context)
    def test_manager_group_read_only(self):
        """Groupe de base : read/search OK ; create/write/delete refusés."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager')
        user = self._create_user('test_secret_manager', [group.id])
        Secret = Pool().get('secret.secret')

        with Transaction().set_user(user.id):
            rows = Secret.read([secret.id], ['name'])
            self.assertEqual(rows[0]['name'], secret.name)
            found = Secret.search([('id', '=', secret.id)])
            self.assertEqual(len(found), 1)

            with self.assertRaises(AccessError):
                Secret.create([{
                    'name': f'test_acl_create_{uuid.uuid4().hex}',
                    'value': 'valeur',
                }])
            with self.assertRaises(AccessError):
                Secret.write([secret], {'value': 'autre-valeur'})
            with self.assertRaises(AccessError):
                Secret.delete([secret])

    @with_transaction(context=_check_access_context)
    def test_admin_group_crud_allowed(self):
        """Admin module : create/write/delete autorisés."""
        group = self._get_group('group_secret_manager_admin')
        user = self._create_user('test_secret_admin', [group.id])
        Secret = Pool().get('secret.secret')
        name = f'test_acl_admin_{uuid.uuid4().hex}'

        with Transaction().set_user(user.id):
            secret, = Secret.create([{
                'name': name,
                'value': 'valeur-admin',
            }])
            Secret.write([secret], {'value': 'valeur-modifiee'})
            Secret.delete([Secret(secret.id)])

    @with_transaction(context=_check_access_context)
    def test_delete_secret_detaches_usage_log(self):
        """Suppression d'un secret avec journal : log conservé, lien détaché."""
        group = self._get_group('group_secret_manager_admin')
        user = self._create_user('test_secret_delete_log', [group.id])
        Secret = Pool().get('secret.secret')
        UsageLog = Pool().get('secret.usage.log')
        name = f'test_acl_delete_log_{uuid.uuid4().hex}'

        with Transaction().set_user(user.id):
            secret, = Secret.create([{
                'name': name,
                'value': 'valeur-delete-log',
            }])
            logs = UsageLog.search([
                ('secret', '=', secret.id),
                ('action', '=', 'encrypt'),
                ('outcome', '=', 'success'),
            ])
            self.assertEqual(len(logs), 1)
            log_id = logs[0].id

            Secret.delete([Secret(secret.id)])

            remaining_logs = UsageLog.search([('id', '=', log_id)])
            self.assertEqual(len(remaining_logs), 1)
            log = remaining_logs[0]
            self.assertIsNone(log.secret)
            self.assertEqual(log.secret_name, name)
            self.assertEqual(Secret.search([('name', '=', name)]), [])

    @with_transaction(context=_check_access_context)
    def test_secret_manager_user_without_groups_denied_get_edit_save(self):
        """Sans groupe : SecretManager.get, edit et save refusés."""
        secret = self._create_secret()
        user = self._create_user('test_secret_manager_api_no_group', [])

        with Transaction().set_user(user.id):
            with self.assertRaises(AccessError):
                SecretManager.get(secret.name)
            with self.assertRaises(AccessError):
                SecretManager.edit(secret.name, None, 'valeur-modifiee')
            with self.assertRaises(AccessError):
                SecretManager.save(
                    f'test_acl_save_no_group_{uuid.uuid4().hex}', 'valeur')

    @with_transaction(context=_check_access_context)
    def test_secret_manager_manager_group_get_ok_edit_save_denied(self):
        """Groupe de base : SecretManager.get OK ; edit et save refusés."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager')
        user = self._create_user('test_secret_manager_api', [group.id])
        Secret = Pool().get('secret.secret')

        with Transaction().set_user(user.id):
            found = SecretManager.get(secret.name)
            self.assertNotIsInstance(found, ModelSQL)
            self.assertFalse(hasattr(found, 'save'))
            self.assertEqual(found.id, secret.id)
            self.assertEqual(found.name, secret.name)
            self.assertEqual(found.value, secret.value)
            self.assertEqual(found.use_custom_key, secret.use_custom_key)
            with self.assertRaises(AccessError):
                SecretManager.edit(secret.name, None, 'valeur-modifiee')
            with self.assertRaises(AccessError):
                SecretManager.save(
                    f'test_acl_save_manager_{uuid.uuid4().hex}', 'valeur')

    @with_transaction(context=_check_access_context)
    def test_secret_manager_manager_group_get_decrypt_ok(self):
        """Groupe de base : CryptoManager.decrypt sur le snapshot get."""
        plain_value = 'valeur-decrypt-test'
        Secret = Pool().get('secret.secret')
        name = f'test_acl_decrypt_{uuid.uuid4().hex}'
        secret, = Secret.create([{
            'name': name,
            'value': plain_value,
        }])
        group = self._get_group('group_secret_manager')
        user = self._create_user('test_secret_manager_decrypt', [group.id])

        with Transaction().set_user(user.id):
            found = SecretManager.get(name)
            self.assertEqual(CryptoManager.decrypt(found), plain_value)

    @with_transaction(context=_check_access_context)
    def test_secret_manager_admin_group_get_edit_save_allowed(self):
        """Admin module : SecretManager.get, edit et save autorisés."""
        secret = self._create_secret()
        group = self._get_group('group_secret_manager_admin')
        user = self._create_user('test_secret_manager_api_admin', [group.id])
        save_name = f'test_acl_save_admin_{uuid.uuid4().hex}'

        with Transaction().set_user(user.id):
            found = SecretManager.get(secret.name)
            self.assertNotIsInstance(found, ModelSQL)
            self.assertEqual(found.name, secret.name)
            SecretManager.edit(secret.name, None, 'valeur-modifiee')
            updated = SecretManager.get(secret.name)
            self.assertIsNotNone(updated)
            self.assertNotIsInstance(updated, ModelSQL)

            created = SecretManager.save(save_name, 'valeur-save-admin')
            self.assertIsNotNone(created)
            self.assertEqual(created.name, save_name)
            saved = SecretManager.get(save_name)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.name, save_name)
            self.assertEqual(CryptoManager.decrypt(saved), 'valeur-save-admin')


del ModuleTestCase
