# Journal de bord

## Phase 3 — Synthèse vocale (2026-09-27)

### Fait
- **Piper TTS** (`piper-tts` 1.8.0, gratuit, hors ligne) avec la voix `fr_FR-siwis-medium` (60 Mo, téléchargée une seule fois dans `models/piper/` par l'outil officiel `python -m piper.download_voices`, aussi appelé par `install.ps1`). Repli automatique sur la **voix Windows (SAPI via pyttsx3)** si Piper ne se charge pas.
- `friday/core/speech.py` : découpage phrase par phrase **pendant** le streaming de Claude (abréviations, numéros de liste, phrases trop longues coupées à une virgule) ; les blocs `[AFFICHER]` partent vers l'affichage, jamais lus ; nettoyage du texte (markdown, code, liens → « un lien », emojis, `[MODE_CODE]`, « Mr » → « Mister »).
- `friday/core/narrator.py` : deux fils (synthèse de la phrase suivante pendant la lecture de la phrase en cours) ; `stop()` coupe la phrase en cours et abandonne les suivantes ; rappel `on_speaking` pour la future machine à états (micro coupé pendant la parole, phase 5).
- `SoundDevicePlayer` : lecture par blocs de 50 ms sur la sortie configurée **par son nom**, résolue à chaque phrase (casque débranché → sortie Windows par défaut).
- `friday chat` parle : les réponses de Claude et les phrases locales de FRIDAY sont lues. Interruption clavier : Ctrl+C (pendant la réponse ou pendant la lecture), une nouvelle ligne tapée, ou « stop » / « annule ». `friday chat --muet` pour le texte seul ; `friday dis <texte>` pour tester la voix.
- Config `tts` : `enabled`, `engine`, `voice`, `models_dir`, `length_scale` (vitesse).
- 241 tests (dont un test réel de la voix Piper, sauté si le modèle est absent).

### Mesuré en réel
- Chargement de la voix : 1,4 s (une fois au démarrage). Synthèse : 0,27 s pour 6,9 s de parole (CPU).
- Demande à Opus 5.5 : premier texte à 2,7 s, **FRIDAY commence à parler à 3,7 s**, avant la fin de la réponse de Claude (4,9 s).

### Décisions
- Voix féminine siwis (cohérente avec FRIDAY) ; `fr_FR-upmc-medium` reste possible via la config.
- Piper sur CPU : largement assez rapide, le GPU reste libre pour Whisper (phase 4).
- Un flux audio par phrase plutôt qu'un flux continu : plus simple, tolère le changement de périphérique entre deux phrases ; le court silence entre phrases sonne naturel.
- « Mr » est prononcé « Mister » (en français, espeak lirait « M R »).
- Toute nouvelle saisie coupe la parole en cours (le mot « stop » vocal viendra avec le micro).

### Reste
- Machine à états IDLE → LISTENING → THINKING → SPEAKING et anti-écho : phases 4 et 5.

## Phase 2 — Commandes locales, routeur, sessions (2026-09-27)

### Fait
- `friday/core/intents.py` : détection locale (sans Claude, donc sans quota) des commandes de modèle, de mode, de sessions, d'état et de contrôle, tolérante aux accents, à la casse, à la ponctuation, aux formules de politesse (« Friday », « s'il vous plaît », « tu peux… »), au tutoiement comme au vouvoiement et aux variantes de transcription (« aïcou », « cloud code »). Une commande suivie d'une demande (« utilise Opus pour analyser… ») applique la commande puis envoie la suite à Claude, avec ses accents d'origine. Une phrase qui ressemble à une commande (« Opus ? », « session boucherie ») déclenche une question de confirmation.
- `friday/core/router.py` : choix local Haiku / Opus. Simple = question de connaissance courte sans action, fichier, chemin ni sujet technique ; tout le reste et les cas ambigus → modèle complexe ; mode Claude Code → modèle complexe. Règles éditables dans `friday.yaml`.
- `friday/core/sessions.py` + `data/sessions.json` : registre des sessions (nom, identifiant Claude Code, mode, modèle, verrou de modèle, dossier, dates, résumé d'une ligne), recherche tolérante (Levenshtein ≤ 2, nom partiel, « 3 » pour « Session 3 »), ambiguïté → « Laquelle ? ».
- `friday/core/usage.py` + `data/usage.json` : compteur de requêtes par modèle et par heure (31 jours) → « combien de requêtes aujourd'hui ? ».
- `friday/core/controller.py` : logique applicative commune au texte, à la voix et à l'interface ; questions en attente (passage en mode Claude Code, oubli d'une session, commande incertaine, choix entre sessions) ; au démarrage, reprise de la dernière session active (mode et modèle compris) et annonce.
- `friday chat` réécrit comme simple affichage du contrôleur : les phrases naturelles fonctionnent comme à l'oral, les raccourcis `/…` restent disponibles.
- FRIDAY vouvoie l'utilisateur (persona et messages locaux).
- 213 tests (dont toutes les phrases d'exemple du §3.5 et des variantes), ruff et mypy strict propres.

### Vérifié en réel
- Question simple → Haiku 4.5 ; « quel modèle tu utilises ? » répond sans appeler Claude.
- Sessions : création nommée, liste parlée, session précédente, reprise malgré une faute (« bouchrie »), contexte conservé (`--resume`), redémarrage de FRIDAY → « Session boucherie, mode Claude, Fable 5.1. » et le contexte est toujours là.

### Décisions
- **Verrou de modèle par session** (`model_lock`) : « utilise Fable » s'impose dans cette session jusqu'à « modèle automatique » ; sinon le routeur choisit à chaque requête et le changement se fait par `/model` dans la session (sans relance ni quota).
- **Mots techniques en mots entiers** dans le routeur (bug réel : « repo » reconnaissait « répondez » et envoyait une question simple sur Opus) ; les verbes d'action restent des préfixes pour couvrir les conjugaisons.
- **Réponse inattendue à une question = nouvelle demande** : si l'utilisateur ne répond ni oui ni non, la question est abandonnée et la phrase traitée normalement (plus naturel à l'oral).
- **Oublier une session** ne supprime que l'entrée du registre (confirmation demandée) ; la transcription Claude Code reste sur le disque.
- **Arrêt propre du flux** : si l'affichage abandonne une réponse en cours, le contrôleur interrompt Claude et termine le tour, pour que le cerveau reste utilisable. Dans `friday chat`, Ctrl+C déclenche l'interruption via un gestionnaire de signal (plus de `KeyboardInterrupt` au milieu d'un générateur).
- Dossier de travail mémorisé par session (`SessionState.workspace`) : prépare l'import des sessions existantes (phase 8).

### Reste
- Import des sessions Claude Code existantes (phase 8).
- Les noms dictés sont gardés tels quels (« boucherie » en minuscules si c'est ainsi qu'il a été dit ou tapé).

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
