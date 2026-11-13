# asp_SecretManager

Module Tryton de coffre-fort pour stocker des secrets chiffrés et les exposer aux autres modules de l'instance.

## Description

Les secrets sont enregistrés chiffrés (Fernet) dans le modèle `secret.secret`. La clé de chiffrement par défaut de l'instance est fournie dans la section `[asp_secret_manager]` du fichier `trytond.conf` (hors dépôt). Il est aussi possible de chiffrer un secret avec une clé Fernet personnelle, conservée hors de l'instance.

Deux groupes Tryton contrôlent l'accès : **Gestionnaire de secrets** et **Administration des secrets** (enfant du premier, il en hérite les droits). Le détail des actions autorisées par groupe est décrit dans **Utilisation**.

## Fonctionnalités

- **Liste des secrets** — Administration → Secrets → Secrets (colonnes : clé, clé personnelle utilisée)
- **Création** — même écran, bouton **Nouveau**
- **Afficher / Modifier** — boutons du formulaire d'un secret enregistré
- **Générer une clé** — Administration → Secrets → Générer une clé (rien n'est enregistré en base)
- **Rechiffrer les secrets** — Administration → Secrets → Rechiffrer les secrets
- **Journal d'usage** — Administration → Secrets → Journal d'usage (admin, lecture seule)

## Dépendances python

- **Python 3.10 ou supérieur** — le module s’appuie sur la syntaxe de types `str|None`.
- `cryptography` — chiffrement Fernet des secrets (stockage en base et API `CryptoManager`).

## Configuration

1. Assigner les groupes selon le besoin (voir **Utilisation**).
2. Définir la clé d'instance dans `trytond.conf` (fichier hors dépôt, `chmod 0600`, propriétaire du processus trytond). Générer une clé Fernet via **Générer une clé**, puis renseigner :

```ini
[asp_secret_manager]
key = <clé Fernet>
```

Pendant une **rotation de clé**, l'exploitant doit déclarer l'ancienne clé pour conserver le déchiffrement des secrets existants :

```ini
[asp_secret_manager]
key = <nouvelle clé K2>
old_key = <ancienne clé K1>
```

3. Redémarrer trytond après toute modification de cette configuration.
4. Lancer le wizard **Rechiffrer les secrets** (rotation). Le wizard rechiffre aussi les champs Fernet déclarés par d'autres modules. Les secrets à clé personnelle ne sont pas concernés.


**Attention :** modifier la clé sans rechiffrement des secrets existants rend le coffre illisible.

Optionnel : au lieu de la valeur `key`, l'exploitant peut renseigner `key_file` dans la section `[asp_secret_manager]` — chemin **absolu** vers un fichier contenant la clé Fernet, en permissions `0400` ou `0600`, hors arborescence du dépôt. Si `key_file` est défini, la clé est lue depuis ce fichier et l'option `key` n'est pas utilisée.

```ini
[asp_secret_manager]
key_file = /chemin/absolu/vers/cle_fernet
```

## Utilisation

### Gestionnaire de secrets

- lire un secret depuis le code Python via `SecretManager.get`.
- lire et rechercher les enregistrements du modèle `secret.secret` (RPC).

### Administration des secrets

Le groupe **Administration des secrets** est enfant de **Gestionnaire de secrets** : il peut tout ce que le gestionnaire peut, plus les actions suivantes :
- créer, modifier ou supprimer des secrets (interface et `SecretManager.save` / `SecretManager.edit`).
- **Générer une clé**.
- **Rechiffrer les secrets**.
- consulter le **Journal d'usage** (lecture seule).

#### Créer un secret

1. Administration → Secrets → **Secrets**
2. Cliquer **Nouveau**
3. Renseigner **Clé** (identifiant unique du secret) et **Valeur** (en clair ; chiffrée à l'enregistrement)
4. Laisser décoché **Utiliser une clé personnelle ?** pour les secrets lus par d'autres modules
5. Si la case est cochée, saisir **Clé personnelle** (Fernet générée via **Générer une clé**)
6. Enregistrer

#### Consulter ou modifier un secret existant

Après enregistrement, le champ **valeur** de la clé n'est plus affiché ; la consultation et la modification se font via les assistants **Afficher** et **Modifier**.

1. Ouvrir un secret enregistré dans **Secrets**
2. **Afficher** — ouvre l'assistant `secret.show` :
   - secret à **clé d'instance** : écran résultat **Valeur déchiffrée** directement, puis **Fermer** ;
   - secret à **clé personnelle** : saisir la **Clé de déchiffrement**, **Afficher**, consulter le résultat, puis **Fermer**.
   Le formulaire parent n'affiche pas la valeur en clair ; fermer l'assistant suffit.
3. **Modifier** — ouvre l'assistant `secret.edit` (pas de champ **Clé** / nom) :
   - notice « Ce secret utilise une clé personnelle. » si clé personnelle ;
   - saisir la **Clé de déchiffrement** si nécessaire, puis la **Nouvelle valeur** ;
   - **Enregistrer** ou **Annuler** dans l'assistant.

#### Consulter le journal d'usage

Audit des opérations sensibles sur le coffre (utilisateur, secret, action, résultat, canal interface ou API). Menu **Journal d'usage** (voir Fonctionnalités).

**Tracé :**
- créer un secret
- afficher un secret
- modifier un secret (déverrouillage et enregistrement)
- supprimer un secret
- rechiffrer les secrets (rotation de la clé d'instance)

Aucune clé Fernet ni valeur (claire ou chiffrée) n'y est enregistrée.

**Non tracé :**
- génération de clé
- lecture via `SecretManager.get`
- déchiffrement par les modules consommateurs

Les entrées de plus d'un an sont purgées automatiquement par une tâche planifiée quotidienne.

## API développeur

Classes utilitaires dans [tools.py](./tools.py), importables depuis les autres modules Tryton de l'instance. Droits d'accès : voir **Utilisation**.

#### EncryptedFieldsMixin

Pour qu'un champ `Char` chiffré avec la clé d'instance (`CryptoManager.encrypt`) soit pris en compte par le wizard **Rechiffrer les secrets** (voir étape 4 de **Configuration**) :

1. Ajouter `asp_SecretManager` dans les `depends:` du module consommateur.
2. Hériter `EncryptedFieldsMixin` sur le modèle concerné :

```python
from trytond.modules.asp_SecretManager.tools import (
    CryptoManager, EncryptedFieldsMixin)
```

3. Déclarer `_instance_encrypted_fields` : tuple des noms des champs **`fields.Char` persistés** (jetons Fernet en base), pas les champs de saisie ou de liaison vers le coffre.
4. Enregistrer le modèle dans le Pool comme d'habitude (`register()` ou section `[register]` de `tryton.cfg`). Le mixin n'a pas d'enregistrement XML.
5. Pattern recommandé : un `Char` **readonly** pour le stockage chiffré, plus un `Function` `*_display` pour afficher et saisir en clair ; ne pas lister les `Function` ni les `Many2One` vers `secret.secret` dans le tuple — le coffre est déjà rechiffré par le wizard.

**Important :** un `Char` Fernet **non déclaré** dans `_instance_encrypted_fields` n'est **pas** rechiffré. Après changement de clé d'instance, et retrait de `old_key`, ces valeurs deviennent **irrécupérables**.

```python
from trytond.modules.asp_SecretManager.tools import (
    CryptoManager, EncryptedFieldsMixin)
from trytond.model import ModelSQL, ModelView, fields

class MaConfiguration(EncryptedFieldsMixin, ModelSQL, ModelView):
    __name__ = 'mon.module.configuration'
    _instance_encrypted_fields = ('api_token',)

    api_token = fields.Char("Jeton (chiffré)", readonly=True)
    api_token_display = fields.Function(
        fields.Char("Jeton"), 'get_api_token_display', 'set_api_token_display')
```

#### CryptoManager

Chiffrement / déchiffrement Fernet et génération de clé.

```python
from trytond.modules.asp_SecretManager.tools import CryptoManager

CryptoManager.encrypt("valeur_en_clair")
CryptoManager.encrypt("valeur_en_clair", "CLE_FERNET_EXEMPLE")
CryptoManager.decrypt(secret_enregistrement, "CLE_FERNET_EXEMPLE")
CryptoManager.keygen()
```

#### SecretManager

Accès au coffre depuis le code Python.

```python
from trytond.modules.asp_SecretManager.tools import SecretManager

SecretManager.get("ma_cle")
SecretManager.save("ma_cle", "valeur_en_clair")
SecretManager.save("ma_cle", "valeur_en_clair", personalized_key="CLE_FERNET_EXEMPLE")
SecretManager.edit("ma_cle", "CLE_FERNET_EXEMPLE", "nouvelle_valeur")  # key optionnel si clé d'instance
SecretManager.is_encrypted("chaine", key=None)
```
