# Journal de bord

## Phase 1 — Cerveau texte (2026-09-27)

### Fait
- `friday/adapters/brain_claude_code.py` : pilote un processus `claude -p` longue durée en `stream-json` bidirectionnel (plusieurs messages sans relancer Claude Code), dans les deux modes.
- `friday/adapters/claude_stream.py` : traduction des événements JSON en événements du cœur (`friday/core/events.py`), classification des erreurs (quota, authentification, modèle, réseau).
- `config/persona.md` (persona de FRIDAY, balises `[AFFICHER]` et `[MODE_CODE]`), `friday/core/prompt.py` (persona + mode + date + appellations + session).
- `friday chat` (`friday/chat.py`) : `/mode`, `/model`, `/session`, `/etat`, `/aide`, `/quitter`, Ctrl+C pour interrompre.
- Configuration validée au démarrage (`friday/config.py`), journaux `logs/friday.log` et `logs/actions.log` avec rotation.
- 67 tests (dont fixtures `stream-json` réelles anonymisées dans `tests/fixtures/stream/`), ruff et mypy strict propres.

### Vérifié en réel (Claude Code 2.1.283)
- Mode Claude : `system/init` montre `tools: []` avec `--tools ""`.
- Conversation multi-tours dans un seul processus (contexte conservé).
- `/model <alias>` envoyé comme message change de modèle **sans relancer** le processus (réponse synthétique « Set model to … »). Repli codé : relance avec `--model` + `--resume` si la commande échoue.
- Interruption : `{"type":"control_request","request":{"subtype":"interrupt"}}` sur stdin → résultat `error_during_execution` / `aborted_streaming`, le processus reste utilisable. Si claude ne répond pas en 5 s, il est tué et relancé avec `--resume` à la requête suivante.
- Modèle inconnu → résultat `is_error`, `api_error_status: 404`, sortie code 1 → FRIDAY reste sur le modèle précédent.
- `rate_limit_event` donne l'utilisation (5 h, 7 jours) et l'heure de réinitialisation → commande `/etat` et message de quota.
- Proposition de passer en mode Claude Code, puis création réelle d'un fichier.

### Décisions
- **`--safe-mode` + `--strict-mcp-config`** : sans eux, les plugins et hooks de l'utilisateur (ECC, GateGuard…) et la mémoire automatique se chargent dans les sessions FRIDAY (`--setting-sources project` ne suffit pas). Conséquence : le `CLAUDE.md` du dossier est ignoré, donc **le persona est un fichier `config/persona.md` passé avec `--append-system-prompt-file`** au lieu d'un `CLAUDE.md` dans le dossier de travail (écart assumé au §4.3, même contenu). Autre avantage : il n'influence pas les sessions de développement de FRIDAY.
- **`--system-prompt-snapshot off`** : par défaut, Claude Code fige le prompt ajouté au premier message et le réutilise à chaque `--resume` ; il faut le désactiver pour que le mode et la date soient à jour.
- **Changement de mode = relance avec `--resume`** : la liste d'outils est fixée au lancement.
- **Mode Claude Code** : `--tools` limité à `claude.code_tools` (sinon 35 outils : Cron, Workflow, RemoteTrigger…), `--permission-mode acceptEdits`, `--allowedTools`, `--permission-prompts none` (tout ce qui demanderait une permission est refusé jusqu'à la phase 6).
- **Règles `ask` via `--settings`** (`claude.confirm_tools`) : constaté en réel, `acceptEdits` laisse passer `Remove-Item` dans le dossier de travail sans rien demander. Les règles `ask` (fichier `data/runtime/claude-settings.json`) forcent la demande de permission — refusée aujourd'hui, confirmée à la voix en phase 6. Vérifié : elles s'appliquent malgré `--safe-mode`.
- Claude Code approuve seul certaines commandes en lecture seule (ex. `whoami`) même hors `--allowedTools` : comportement intégré, jugé acceptable.
- Proposition de mode : en mode Claude, le persona demande de terminer par `[MODE_CODE]` ; FRIDAY le masque, propose le changement, puis renvoie la demande précédée d'une note (sinon Claude, voyant l'historique, s'excusait d'avoir demandé le changement).
- Modèle au démarrage : `models.complex` en attendant le routeur de la phase 2 ; passage en mode Claude Code → modèle complexe.
- Vérification réseau par DNS (2 s) avant chaque requête : pas d'attente de 3 minutes sans réseau.
- Entrée clavier : suppression du BOM UTF-8 que PowerShell ajoute parfois en tête d'entrée redirigée.

### Reste
- Registre des sessions nommées (phase 2) : `/session` ne gère pour l'instant que la session courante et la reprise par identifiant.
- Le compteur de requêtes par modèle (§4.5) est prévu avec l'interface (phases 7/9) ; `/etat` affiche déjà le quota renvoyé par Claude.

## Phase 0 — Environnement et squelette (2026-09-27)

### Fait
- Vérifications consignées dans `docs/environnement.md`.
- Python 3.12.14 installé via `uv python install 3.12` (gratuit, sans droits admin), `.venv` créé par uv.
- Squelette : paquet `friday/` (`core`, `adapters`, `permission_server`, `ui`), `config/friday.example.yaml`, `scripts/install.ps1`, commande `friday devices`.
- Dépendances épinglées par `uv.lock`.

### Décisions
- **Paquet `friday/` au lieu de dossiers `core/`, `adapters/`… à la racine** : évite les collisions de noms d'import génériques (`core`, `ui`) et permet un point d'entrée `friday` installable. La structure interne suit le §2.1 du protocole.
- **uv** comme gestionnaire d'environnement et de dépendances : déjà installé, gratuit, gère aussi l'installation de Python et l'épinglage (`uv.lock`).
- **Python 3.12** (et non 3.13) : meilleure disponibilité des roues binaires pour faster-whisper / onnxruntime / openWakeWord.
- **Whisper `large-v3` sur CUDA** par défaut : RTX 4070 Ti 12 Go détectée.
- Les tests réels de `claude` doivent tourner **hors du bac à sable** de la session Claude Code qui développe FRIDAY : dans le bac à sable, le rafraîchissement du jeton OAuth échoue (`Failed to refresh OAuth token`). FRIDAY elle-même, lancée normalement, n'est pas concernée.

### Flags `claude` (v2.1.272) vérifiés dans `claude --help`
- `--tools ""` existe : désactive tous les outils intégrés → candidat pour le mode Claude (à confirmer en phase 1 via `system/init`).
- `--input-format stream-json`, `--output-format stream-json`, `--include-partial-messages`, `--verbose`, `--resume`, `--append-system-prompt`, `--allowedTools`, `--disallowedTools`, `--mcp-config`, `--strict-mcp-config`, `--permission-mode` (`acceptEdits`, `auto`, `dontAsk`, `manual`, `plan`, `bypassPermissions`) : présents.
- `--permission-prompt-tool` n'apparaît plus dans l'aide mais est référencé par le nouveau `--permission-prompts host|none` (« host » = l'hôte SDK ou `--permission-prompt-tool`). À tester en phase 6.
- `--restricted` (nouveau) : retire les outils qui exécutent du code et confine les outils fichiers au dossier de travail. Piste de durcissement pour le mode Claude Code.

- **Périphériques audio désignés par leur nom, jamais par leur indice** (`friday/adapters/audio_io.py`) : les indices `sounddevice` changent dès qu'un casque est branché ou débranché (constaté en phase 0). Le nom est résolu en indice à chaque ouverture : correspondance exacte puis partielle, insensible aux accents et à la casse, préfixe accepté (MME tronque les noms à 31 caractères). Parmi les homonymes, préférence DirectSound (noms complets, rééchantillonnage vers 16 kHz géré par Windows) > MME > WASAPI (exige la fréquence native). Périphérique introuvable → défaut Windows + avertissement dans le journal, sans plantage.

- **Claude Code mis à jour en 2.1.283** (`claude update`, à la demande de l'utilisateur) : l'alias `opus` donne désormais Opus 5.5 (`claude-opus-5-5`). Les flags ci-dessus ont été relevés sur 2.1.272 ; ils seront revérifiés en phase 1.
