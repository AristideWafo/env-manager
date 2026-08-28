# API CONTRACT — Env Manager

Base URL : `https://envmanager.ffaero.com/api/v1` (à adapter au sous-domaine réel choisi)
Format : JSON. Auth : session cookie (WebAuthn) pour usage interface, ou token API dédié pour le pipeline CI/CD (scope restreint lock/unlock).

## Format standard

### Succès
```json
{ "data": {}, "meta": { "requestId": "uuid", "timestamp": "iso8601" } }
```

### Erreur
```json
{ "error": { "code": "STRING_CODE", "message": "human readable" }, "meta": { "requestId": "uuid", "timestamp": "iso8601" } }
```

### Codes d'erreur

| Code | HTTP | Sens |
|---|---:|---|
| UNAUTHORIZED | 401 | non authentifié |
| FORBIDDEN | 403 | permission insuffisante |
| NOT_FOUND | 404 | ressource introuvable |
| VALIDATION_ERROR | 422 | payload invalide |
| REVISION_CONFLICT | 409 | revision fournie obsolète |
| ENVIRONMENT_LOCKED | 423 | environnement verrouillé pour déploiement |
| PATH_NOT_ALLOWED | 422 | chemin hors `allowed_roots` |
| INTERNAL_ERROR | 500 | erreur serveur |

---

## Auth

```
POST /auth/webauthn/register/options   → génère les options d'enregistrement (admin crée l'invitation en amont)
POST /auth/webauthn/register/verify    → vérifie et enregistre le credential
POST /auth/webauthn/login/options      → génère le challenge de connexion
POST /auth/webauthn/login/verify       → vérifie la signature, ouvre la session
POST /auth/logout                      → ferme la session
```

## Utilisateurs (ADMIN)

```
POST   /users                  → crée un utilisateur (déclenche invitation)
GET    /users                  → liste les utilisateurs
PATCH  /users/{id}              → active/désactive, change le rôle
POST   /users/{id}/credentials  → ajoute un credential (recovery)
DELETE /users/{id}/credentials/{credentialId} → révoque un credential
```

## Projets & environnements

```
POST   /allowed-roots           → (ADMIN) déclare un root autorisé
GET    /allowed-roots           → (ADMIN) liste les roots

POST   /projects                → (ADMIN) crée un projet
GET    /projects                → liste les projets visibles par l'utilisateur

POST   /projects/{id}/environments   → (ADMIN) crée un environnement
GET    /projects/{id}/environments   → liste les environnements (filtré permission)
```

## Permissions (ADMIN)

```
POST   /environments/{id}/permissions        → attribue une permission à un user
GET    /environments/{id}/permissions        → liste les permissions
DELETE /environments/{id}/permissions/{userId} → révoque
```

## Variables

```
GET    /environments/{id}/variables
  → liste les variables. Les variables is_secret=true sont retournées avec value: null, secret: true.
  Chaque variable inclut aussi group ("" si hors groupe), comment ("" si aucun), order (int) —
  métadonnées du structured editor (core/envdoc.py) qui déterminent aussi la structure du
  fichier .env écrit sur disque (voir DATA_MODEL.md).

POST   /environments/{id}/variables
  body: { key, value, is_secret }
  → crée une variable. Nécessite WRITE. Vérifie ENVIRONMENT_LOCKED.

PATCH  /environments/{id}/variables/{key}
  body: { value, revision }
  → modifie une variable. revision doit correspondre à Environment.revision courant, sinon REVISION_CONFLICT.

DELETE /environments/{id}/variables/{key}
  body: { revision }
  → supprime une variable. Nécessite DELETE.

POST   /environments/{id}/variables/batch
  body: { revision, operations: [{ op: "create"|"update"|"delete", key, value?, is_secret? }] }
  → opération groupée, all-or-nothing. Valide l'ensemble avant toute écriture.

POST   /environments/{id}/variables/{key}/reveal
  → révèle temporairement la valeur d'un secret. Auditée (UC-22).

POST   /environments/{id}/variables/import
  → relit le fichier .env sur disque et importe les clés qui n'existent pas encore en DB
  (import_variables_from_file). Additive uniquement : une clé déjà trackée n'est jamais
  écrasée, même si sa valeur a changé sur disque — la DB reste la source de vérité pour
  ce qui est déjà tracké (AGENT_CONTEXT.md §5). Capture group/comment/order depuis le
  fichier via core/envdoc.py. Nécessite WRITE. Ne bump pas revision, ne réécrit pas le
  fichier (son contenu vient d'être lu, il est déjà à jour).

PATCH  /environments/{id}/variables/{key}/layout
  body: { group?, comment? }
  → modifie le groupe d'affichage et/ou le commentaire d'une variable. Nécessite WRITE.
  Métadonnée d'affichage uniquement : n'incrémente PAS revision, ne réécrit PAS le fichier,
  et reste autorisé même si locked_for_deploy=true (ne change rien à ce qui est déployé).
  Omettre un champ le laisse inchangé.

POST   /environments/{id}/variables/reorder
  body: { keys: [string, ...] }
  → réordonne les variables selon la liste fournie, qui doit contenir exactement les clés
  actuelles de l'environnement (chacune une fois), sinon VALIDATION_ERROR. Rejette aussi (même
  code) un ordre qui casserait la contiguïté d'un groupe — voir DATA_MODEL.md. Nécessite WRITE.
  Même règle que /layout : pas de revision, pas de réécriture fichier, autorisé si verrouillé.

POST   /environments/{id}/variables/{key}/move
  body: { direction: "up"|"down" }
  → échange l'ordre de la variable avec son voisin immédiat (no-op en bout de liste).
  Nécessite WRITE. Même règles que /reorder.
```

## Groupes

Un groupe n'est pas une table séparée — juste la valeur partagée `Variable.group_name`
(voir DATA_MODEL.md). Renommer/dégrouper agit donc en masse sur toutes les variables qui
partagent ce nom.

```
POST   /environments/{id}/groups/rename
  body: { old_name, new_name }
  → renomme le groupe : met à jour group_name sur toutes les variables membres.
  new_name vide → VALIDATION_ERROR. Nécessite WRITE. Métadonnée uniquement (pas de revision,
  pas de réécriture fichier, autorisé si verrouillé).

POST   /environments/{id}/groups/ungroup
  body: { group_name }
  → retire toutes les variables du groupe (group_name -> ""), équivalent à
  delete_group(keep_children=True) dans core/envdoc.py : les variables restent, seul
  l'affichage groupé disparaît. Nécessite WRITE.
```

## Revisions

```
GET    /environments/{id}/revisions              → liste l'historique
GET    /environments/{id}/revisions/{revNumber}  → détail d'une revision (snapshot)
POST   /environments/{id}/revisions/{revNumber}/restore → restaure (crée une nouvelle revision à partir du snapshot)
```

## Audit (ADMIN)

```
GET /audit?project_id=&environment_id=&from=&to=
```

## Intégration CI/CD

```
POST /environments/{id}/lock    → auth par token API dédié, scope limité à cette action
POST /environments/{id}/unlock  → idem
```

Ces deux routes n'exigent pas de session WebAuthn — elles utilisent un token API distinct (Bearer), généré par un ADMIN et stocké côté CI/CD comme secret de pipeline.

---

## Exemple de flux complet — modification d'une variable

```
1. GET  /environments/{id}/variables         → dev récupère variables + revision courante
2. PATCH /environments/{id}/variables/DATABASE_HOST
   body: { value: "db-dev-02", revision: 41 }
3. Si revision == 41 en base :
     → écriture atomique du .env
     → Environment.revision passe à 42
     → Revision snapshot créé
     → AuditLog créé
     → 200 OK
   Si revision != 41 (ex. Bob a déjà écrit) :
     → 409 REVISION_CONFLICT, le dev doit recharger et réessayer
```
