# DATA MODEL — Env Manager

Base : SQLite. ORM : Django. Toutes les tables ci-dessous correspondent à des modèles Django à créer dans l'app `core`.

---

## User

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| email | string, unique | identifiant de connexion |
| display_name | string | |
| role | enum(ADMIN, DEVELOPER) | |
| is_active | bool | default true |
| created_at | datetime | |

## Credential (WebAuthn)

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | FK → User | |
| credential_id | bytes, unique | identifiant WebAuthn |
| public_key | bytes | |
| sign_count | int | anti-replay |
| device_label | string | ex. "Laptop Alice" |
| status | enum(ACTIVE, REVOKED) | |
| created_at | datetime | |
| last_used_at | datetime, nullable | |

## AllowedRoot

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| path | string | chemin absolu, ex. `/opt/ffaero` |
| label | string | |
| created_by | FK → User | admin uniquement |
| created_at | datetime | |

Contrainte applicative : seul un ADMIN peut créer/modifier. Toute résolution de chemin projet doit rester un descendant canonique d'un `AllowedRoot`.

## Project

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | string, unique | ex. "FFAERO" |
| allowed_root_id | FK → AllowedRoot | |
| created_at | datetime | |

## Environment

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | FK → Project | |
| name | string | ex. "DEV", "CI", "TOOLS" |
| relative_path | string | ex. `.env`, `config/ci.env` |
| revision | int | default 0, incrémenté à chaque write réussi |
| locked_for_deploy | bool | default false |
| created_at | datetime | |

Contrainte unique : (`project_id`, `name`).

## Variable

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| environment_id | FK → Environment | |
| key | string | ex. `DATABASE_HOST` |
| value | text | en clair si `is_secret=false` |
| encrypted_value | bytes, nullable | rempli si `is_secret=true`, Fernet |
| is_secret | bool | default false |
| created_at | datetime | |
| updated_at | datetime | |
| order | int | default 0. Position d'affichage (structured editor, `core/envdoc.py`) |
| group_name | string | default `""`. Nom du groupe d'affichage, vide = hors groupe |
| leading_comment | text | default `""`. Commentaire affiché juste au-dessus de la variable |
| group_flank_char | char(1) | default `"-"`. Caractère de décoration de l'en-tête du groupe (ex. `=` pour `# ==== Nom ====`). Redondant entre les membres d'un même groupe ; ignoré si `group_name=""` |
| group_flank_len | int | default 3. Longueur du flanc de l'en-tête (ex. 20 pour `====================`) |

Contrainte unique : (`environment_id`, `key`).
Règle : si `is_secret=true`, `value` reste vide/null, seul `encrypted_value` est peuplé.

**`order`/`group_name`/`leading_comment` pilotent le fichier écrit, mais ne portent jamais
la valeur d'une variable.** `write_environment_file` sérialise via `envfile.render_document`
(`core/envdoc.py`) : groupes, commentaires, ordre et quoting-si-nécessaire atterrissent
dans le fichier — décision actée après le format canonique toujours-quoté/trié initial (voir
git log ; le changement casse potentiellement un consommateur externe strict sur le format,
accepté en connaissance de cause). Perdre ces champs ne perd jamais une valeur, seulement
la mise en forme (un fichier réécrit sans eux retombe sur un bloc plat, non groupé, sans
commentaire).

**Invariant de contiguïté des groupes** : à un instant donné, toutes les `Variable` d'un
même `environment_id` partageant un `group_name` non vide doivent être contiguës en `order`
— aucune variable hors groupe ou d'un autre groupe ne peut s'intercaler. Maintenu par
`services._group_blocks`/`_validate_block_contiguity` (rejette un `reorder_variables` qui
casserait ça) et `_normalize_group_contiguity` (répare après `update_variable_layout` ou
un import qui ajoute des membres d'un groupe déjà présent ailleurs).

Ces champs sont peuplés à l'import (`import_variables_from_file`, via `core/envdoc.py` qui
comprend le vrai dialecte `.env` — groupes, commentaires, valeurs non quotées) et modifiables
via `update_variable_layout`/`reorder_variables`/`swap_variable_order`, qui n'incrémentent
jamais `Environment.revision` et ne réécrivent jamais le fichier eux-mêmes (autorisés même si
`locked_for_deploy=true`, puisqu'ils ne changent rien à ce qui est *actuellement* déployé) —
mais la prochaine écriture déclenchée par une modification de valeur utilisera l'état courant
de ces champs.

## Permission

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | FK → User | |
| environment_id | FK → Environment | |
| can_read | bool | |
| can_write | bool | |
| can_delete | bool | |

Contrainte unique : (`user_id`, `environment_id`).

## Revision (historique)

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| environment_id | FK → Environment | |
| revision_number | int | correspond à `Environment.revision` au moment du snapshot |
| snapshot | JSON | liste des variables (key, value ou encrypted_value, is_secret, order, group_name, leading_comment, group_flank_char, group_flank_len) à cet instant |
| created_by | FK → User | |
| created_at | datetime | |

Utilisé pour restore et pour l'affichage de l'historique. Jamais supprimé.

## AuditLog

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | FK → User, nullable | null si action système |
| project_id | FK → Project, nullable | |
| environment_id | FK → Environment, nullable | |
| action | enum(CREATE, UPDATE, DELETE, LOCK, UNLOCK, RESTORE, LOGIN, ...) | |
| target | string | ex. nom de la variable, jamais sa valeur |
| result | enum(SUCCESS, FAILURE) | |
| detail | text, nullable | message d'erreur éventuel |
| created_at | datetime | |

---

## Relations résumées

```
User 1───N Credential
User 1───N Permission N───1 Environment
Project 1───N Environment N───1 AllowedRoot
Environment 1───N Variable
Environment 1───N Revision
Environment 1───N AuditLog (via FK optionnelle)
```

## Points d'attention pour l'implémentation

- L'incrémentation de `Environment.revision` doit se faire dans la même transaction que l'écriture des `Variable` et la création du `Revision` — utiliser `select_for_update()` ou une transaction atomique Django avec vérification `WHERE revision = <valeur lue>`.
- Le chiffrement Fernet nécessite une clé stockée **hors DB** (variable d'environnement du process ou fichier séparé avec permissions 600), jamais dans SQLite.
- `AuditLog.target` = nom de variable ou identifiant d'objet, jamais `Variable.value` ni `encrypted_value` déchiffré.
