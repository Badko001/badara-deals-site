# AIR UPGRADE AGENT

Assistant personnel qui surveille **votre propre réservation** pour détecter une possibilité
**réelle et officiellement proposée** de passer **3 passagers ensemble** de **Economy à Business**,
par défaut à **0 € et 0 Miles**.

> Le produit dit « J'ai trouvé une opportunité réelle », jamais « J'ai modifié le système Air France ».
> Seule la compagnie peut confirmer qu'une réservation est passée en Business.

## Ce que fait le système (et ce qu'il ne fait jamais)

| Fait | Ne fait jamais |
|---|---|
| Lit la page officielle dans un navigateur isolé où **vous** vous connectez à la main | Demander, stocker ou taper votre mot de passe |
| Décide de façon déterministe (le LLM explique, sans être l'autorité) | Contourner un CAPTCHA, une authentification, un paiement ou un système de Miles |
| Exige **une seule offre officielle couvrant tous les passagers** | Combiner des offres individuelles, deviner une donnée invisible |
| Signale les offres payantes / en Miles, sans les exécuter | Appeler une API privée non documentée, réserver artificiellement des sièges |
| N'agit qu'après **CONFIRMER**, relit la page, et vérifie ensuite le résultat chez la compagnie | Falsifier un PNR, un billet ou une carte d'embarquement |

## Plusieurs réservations

Dans l'onglet **Surclassement**, « + Ajouter une réservation » : un nom, la référence (facultative) et le
nombre de passagers à surclasser (1 à 9). Chaque réservation a sa propre surveillance, ses alertes
(préfixées par son nom) et ses confirmations. La référence complète reste **en mémoire uniquement** ;
seule sa version masquée (`PNR_****123`) est enregistrée et sert à vérifier que la page affichée est
bien la bonne réservation. Après un redémarrage, en mode réel, ressaisissez la référence pour que
l'agent ouvre la réservation.

## Veille des prix (onglet « Veille des prix »)

Surveille les **prix publiés** et vous alerte quand ils baissent :

- **Dakar ↔ Paris** aller-retour (Air France) et **Escapades Europe** au départ de Paris
  (Lisbonne, Barcelone, Rome, Amsterdam, Athènes, Madrid, Prague, Porto — AF, KLM, Transavia),
  préconfigurés et modifiables ; ajoutez vos propres trajets (1 à 9 passagers, aller simple ou A/R).
- Alertes : prix sous votre maximum, plus bas prix observé, baisse nette (≥ 10 % par défaut).
  Pas de doublon : une destination n'est ré-alertée que si le prix baisse encore.
- **Vous réservez et payez sur le site officiel** (lien dans l'alerte) : l'application ne manipule
  jamais de carte bancaire.
- Vérification au plus toutes les heures (3 h par défaut), avec un nombre limité de recherches par
  passage : aucune sollicitation excessive.
- Source : `FARE_PROVIDER=mock` (prix fictifs) ou `duffel` avec votre propre `DUFFEL_API_TOKEN`
  (API d'agrégation qui inclut Air France). Le site Air France n'est jamais lu automatiquement
  pour les prix. Aucun « tarif caché » : seulement les tarifs réellement proposés au public
  (promos, Promo Rewards Flying Blue, etc.).

## Démarrage rapide (mode MOCK, aucune connexion à Air France)

```bash
# Backend (Python 3.12+)
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium        # pour les tests navigateur / le mode réel
cp ../.env.example ../.env                   # optionnel : valeurs par défaut sûres
uvicorn app.main:app --reload --port 8000

# Frontend
cd ../frontend
npm install
npm run dev                                  # http://localhost:5173
```

Dans le dashboard : **Vérifier maintenant**, puis changer de scénario dans **MOCK AIR FRANCE**
(16 scénarios : Economy seule, 2 sièges seulement, offre payante, offre Miles, check-in fermé,
CAPTCHA, données non confirmées…).

Avec Docker : `docker compose up --build` → http://localhost:8080 (mock + DRY_RUN).

## Mode réel Air France (prudence)

1. `PROVIDER=airfrance`, garder `DRY_RUN=true` au début, lancer le backend **sur votre machine**
   (navigateur visible requis).
2. Dashboard → **Ouvrir le navigateur** : une fenêtre Chromium isolée s'ouvre sur le site officiel.
3. Vous vous connectez **vous-même** (et résolvez vous-même toute vérification anti-robot),
   puis ouvrez la réservation.
4. L'agent lit la page et surveille. Tout ce qu'il ne voit pas reste `null`.

⚠️ Les sélecteurs du vrai site sont marqués **non vérifiés** (`verified=False`) : tant qu'ils ne
sont pas validés sur une session réelle (procédure : `docs/AIR_FRANCE_WORKFLOW.md`), l'agent est
en **lecture seule** et refuse de cliquer ; vous acceptez l'offre vous-même dans l'interface officielle.

## Configuration

Voir `.env.example`. Points clés : `DRY_RUN=true`, `CASH_LIMIT=0`, `MILES_LIMIT=0`
(modifiables à chaud depuis le dashboard), `POLL_INTERVAL_SECONDS` borné par
`MINIMUM_CHECK_INTERVAL` / `MAXIMUM_CHECK_INTERVAL`. Azure est optionnel.

## Qualité

```bash
cd backend && pytest && ruff check . && ruff format --check . && mypy
cd frontend && npm run typecheck && npm run lint && npm run build
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — couches, flux, extensibilité multi-compagnies
- [docs/SECURITY.md](docs/SECURITY.md) — secrets, sessions, logs, screenshots, incidents
- [docs/PRIVACY.md](docs/PRIVACY.md) — minimisation et redaction des données
- [docs/TESTING.md](docs/TESTING.md) — scénarios A–F, mock, tests navigateur
- [docs/AIR_FRANCE_WORKFLOW.md](docs/AIR_FRANCE_WORKFLOW.md) — parcours réel et validation des sélecteurs
- [docs/DEPLOYMENT_AZURE.md](docs/DEPLOYMENT_AZURE.md) — Azure Container Apps / App Service / Foundry
