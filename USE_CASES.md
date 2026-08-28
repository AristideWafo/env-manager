# USE CASES — Env Manager

Chaque cas d'usage doit se traduire en : une route API (`API_CONTRACT.md`), une vérification de permission, une entrée d'audit si l'action modifie un état.

---

## Authentification & comptes

| UC | Description | Rôle requis |
|---|---|---|
| UC-01 | Un dev enregistre un device (passkey) pour se connecter | DEVELOPER (self) |
| UC-02 | Un dev se connecte via son device enregistré | DEVELOPER |
| UC-03 | Un admin crée un compte développeur | ADMIN |
| UC-04 | Un admin désactive/réactive un compte | ADMIN |
| UC-05 | Un admin ajoute un nouveau credential à un compte (recovery après perte de device) | ADMIN |
| UC-06 | Un admin révoque un credential compromis ou obsolète | ADMIN |

## Gestion des projets et environnements

| UC | Description | Rôle requis |
|---|---|---|
| UC-07 | Un admin déclare un `AllowedRoot` | ADMIN |
| UC-08 | Un admin crée un projet et l'associe à un root autorisé | ADMIN |
| UC-09 | Un admin crée un environnement avec son chemin relatif cible | ADMIN |
| UC-10 | Un utilisateur liste les projets/environnements existants (filtré par permission) | tous |

## Permissions

| UC | Description | Rôle requis |
|---|---|---|
| UC-11 | Un admin attribue une permission (READ/WRITE/DELETE) à un dev sur projet+environnement | ADMIN |
| UC-12 | Un admin révoque une permission | ADMIN |
| UC-13 | Un dev consulte la liste des environnements auxquels il a accès | DEVELOPER |

## Gestion des variables

| UC | Description | Rôle requis |
|---|---|---|
| UC-14 | Un dev consulte les variables d'un environnement (secrets masqués par défaut) | READ |
| UC-15 | Un dev ajoute une variable | WRITE |
| UC-16 | Un dev modifie une variable | WRITE |
| UC-17 | Un dev supprime une variable | DELETE |
| UC-18 | Un dev effectue une modification groupée (plusieurs variables, une seule opération) | WRITE |
| UC-19 | Un dev marque une variable comme secrète | WRITE |
| UC-20 | Le système valide une configuration avant écriture (schéma, types, requis, doublons) | système |
| UC-21 | Le système rejette une écriture si l'environnement est `locked_for_deploy` | système |
| UC-22 | Un dev révèle temporairement la valeur d'une variable secrète (action explicite, auditée) | READ + confirmation |

## Versionnement & conflits

| UC | Description | Rôle requis |
|---|---|---|
| UC-23 | Le système crée une nouvelle revision à chaque modification validée | système |
| UC-24 | Le système détecte un conflit de revision et le signale au dev | système |
| UC-25 | Un dev consulte l'historique des révisions d'un environnement | READ |
| UC-26 | Un dev restaure une révision antérieure | WRITE |

## Audit

| UC | Description | Rôle requis |
|---|---|---|
| UC-27 | Le système journalise toute action (qui, quoi, quand, résultat) sans exposer les valeurs secrètes | système |
| UC-28 | Un admin consulte le journal d'audit d'un projet/environnement | ADMIN |

## Intégration déploiement (CI/CD)

| UC | Description | Rôle requis |
|---|---|---|
| UC-29 | Le pipeline CI/CD verrouille un environnement avant déploiement | service account / token API |
| UC-30 | Le pipeline CI/CD déverrouille l'environnement après déploiement | service account / token API |
| UC-31 | Le pipeline CI/CD lit le fichier `.env` déjà présent à l'emplacement exact attendu | aucune (lecture filesystem directe, hors API) |

---

## Priorisation suggérée pour un premier sprint agent

1. UC-03, UC-01, UC-02 (comptes + auth minimale) — bloquant pour tout le reste
2. UC-07, UC-08, UC-09 (structure projet/env) — bloquant pour les variables
3. UC-11, UC-13, UC-14 (permissions + lecture) — premier flux utile de bout en bout
4. UC-15, UC-16, UC-17, UC-20, UC-23 (CRUD variable + validation + revision) — cœur produit
5. UC-24, UC-25, UC-26 (conflits, historique, restore)
6. UC-27, UC-28 (audit)
7. UC-19, UC-22 (secrets)
8. UC-29, UC-30, UC-31 (verrou déploiement — dernier, car dépend d'un token API séparé)
