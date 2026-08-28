# AGENT CONTEXT — Env Manager

> À lire en premier par tout agent ou développeur travaillant sur ce projet.
> Ce document est la source de vérité sur le "quoi" et le "pourquoi". Les autres fichiers du repo détaillent le "comment".

---

## 1. Mission du projet

Application web interne permettant aux développeurs de gérer eux-mêmes les variables d'environnement de plusieurs projets (fichiers `.env` et équivalents), sans accès serveur direct et sans dépendre systématiquement du DevOps.

**Utilisateurs cibles :** 5 à 10 développeurs internes.
**Usage :** environnements de dev/CI/tools, pas de production critique dans le scope V1.

## 2. Ce que l'outil fait

- CRUD de variables d'environnement, organisées par `Project → Environment → Variable`
- Authentification sans mot de passe (WebAuthn/Passkeys)
- Permissions par projet + environnement (READ/WRITE/DELETE)
- Versionnement interne (revisions) avec détection de conflit optimiste
- Audit complet des actions (jamais la valeur des secrets)
- Écriture atomique du fichier `.env` à l'emplacement exact attendu par le pipeline CI/CD existant
- Chiffrement au repos des variables marquées secrètes

## 3. Ce que l'outil NE fait PAS (V1)

- Pas de déclenchement de déploiement depuis l'interface
- Pas d'intégration Git/GitHub
- Pas de Secret Manager externe (Vault, Doppler...) — c'est un objectif V4+
- Pas d'écriture distante (SSH/agent) — le process tourne sur le même host que les fichiers cibles
- Pas de SSO, pas de rôles avancés au-delà de ADMIN/DEVELOPER

## 4. Principe d'intégration avec la CI/CD existante

L'Env Manager est une **source de vérité passive**. Il écrit directement le fichier `.env` à l'endroit exact attendu par le pipeline (pas d'étape de "publish" séparée — écrire = déployer la config).

```
Dev modifie via interface
        │
        ▼
Env Manager valide + écrit atomiquement le .env
        │
        ▼
(rien d'automatique ne se déclenche)
        │
        ▼
Pipeline CI/CD existant lit le .env déjà en place au moment du déploiement
```

Le pipeline peut optionnellement appeler `POST /environments/{id}/lock` avant un déploiement et `POST /environments/{id}/unlock` après, pour empêcher une écriture concurrente pendant le déploiement. Voir `API_CONTRACT.md`.

## 5. Décisions d'architecture actées (ne pas remettre en cause sans discussion)

| Sujet | Décision | Raison |
|---|---|---|
| Authentification | WebAuthn/Passkeys (`py_webauthn`) | Pas de clé privée à gérer côté dev, révocation native, MFA implicite |
| Base de données | SQLite | Suffisant pour 5-10 users, ACID, transactions natives pour l'optimistic locking |
| Stockage `.env` | SQLite = source de vérité, fichier `.env` généré à l'écriture | Simplifie atomicité et audit, fichier reproductible |
| Secrets | Chiffrement Fernet (lib `cryptography`), clé hors DB | Colonne `is_secret`, jamais en clair au repos |
| Conflits concurrents | Optimistic locking via colonne `revision` + `UPDATE ... WHERE revision = ?` | Pas de lock distribué nécessaire |
| Écriture fichier | tmp file → fsync → rename atomique, systématique | Empêche toute lecture d'un fichier partiellement écrit par le CI/CD |
| Chemins fichiers | `allowed_roots` déclarés admin-only, résolution canonique + vérification descendant | Empêche path traversal et symlink escape |
| Backend | Django + Django Ninja | Cohérent avec la stack FairFare, admin auto-généré utile en interne |
| Frontend | Django templates + HTMX + Alpine.js + Tailwind CSS | Un seul déploiement, pas de build SPA séparé, UX fluide sans rechargement |
| Déploiement | Docker + Docker Compose sur Hetzner | Cohérent avec l'infra FairFare existante |
| Registre images | GHCR | Gratuit avec GitHub, pas de coût AWS supplémentaire |

## 6. Stack technique

| Composant | Choix |
|---|---|
| Langage | Python 3.12 |
| Backend | Django 5.x + Django Ninja |
| Auth | py_webauthn |
| DB | SQLite (fichier monté en volume Docker) |
| Chiffrement | cryptography (Fernet) |
| Frontend | Django templates + HTMX + Alpine.js + Tailwind CSS (CDN ou build léger) |
| Tests | pytest + pytest-django |
| Lint | ruff |
| CI/CD | GitHub Actions → GHCR → déploiement Hetzner (SSH + docker compose) |

## 7. Où trouver quoi

| Besoin | Fichier |
|---|---|
| Modèle de données détaillé | `DATA_MODEL.md` |
| Liste exhaustive des cas d'usage | `USE_CASES.md` |
| Contrat API (endpoints, payloads, erreurs) | `API_CONTRACT.md` |
| Décisions d'architecture (ADR) | `ADR/` |
| Docker / déploiement | `docker-compose.yml`, `Dockerfile` |
| CI/CD | `.github/workflows/` |

## 8. Règles à respecter systématiquement (pour tout agent codant sur ce repo)

1. Toute écriture de fichier `.env` doit passer par le pattern atomique (tmp + fsync + rename) — jamais d'écriture directe.
2. Toute résolution de chemin doit être validée contre `allowed_roots` avant toute opération filesystem.
3. Aucune valeur de variable marquée `is_secret=true` ne doit apparaître en clair dans les logs, l'audit, ou une réponse API sans action explicite de "reveal".
4. Toute modification de variable doit vérifier la permission (READ/WRITE/DELETE) côté serveur — jamais uniquement côté interface.
5. Toute modification doit incrémenter la revision et être journalisée dans l'audit (acteur, action, timestamp, résultat).
6. Une modification groupée (batch) est all-or-nothing : validation complète avant toute écriture.
7. Ne jamais permettre l'écriture sur un environnement dont `locked_for_deploy = true`.
8. Ne jamais introduire de dépendance à un accès Docker socket ou exécution de commande arbitraire depuis l'app.
