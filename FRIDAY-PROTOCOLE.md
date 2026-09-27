# PROTOCOLE — Création de FRIDAY, assistant vocal local

> Ce document est destiné à Claude Code. Lis-le en entier avant d'écrire la moindre ligne de code. Il fait office de cahier des charges, de contraintes et de plan de travail.

---

## 0. Mission et contraintes non négociables

**Objectif :** créer FRIDAY, un assistant personnel vocal (inspiré de Jarvis/Friday dans Iron Man) qui tourne sur mon PC Windows, s'active quand je dis « Friday », comprend ma voix, me répond à voix haute, affiche une interface type HUD, et peut fonctionner dans deux modes :

- **Mode Claude** (« Claude classique ») : conversation pure, sans outils, pour discuter, poser des questions, réfléchir.
- **Mode Claude Code** : agent avec outils, qui exécute des actions sur mon ordinateur (fichiers, commandes, code, applications).

Je dois pouvoir, **à la voix ou par l'interface** : changer de mode, changer de modèle (Haiku, Opus 5.5, Fable 5.1), et naviguer entre plusieurs sessions de conversation.

**Contraintes absolues (à respecter à chaque décision) :**

1. **Zéro clé API.** Le seul « cerveau » autorisé est le binaire `claude` (Claude Code) déjà installé et connecté à mon abonnement Claude Pro via OAuth. Les deux modes (Claude et Claude Code) passent par ce même binaire. Il est interdit d'utiliser `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, le Claude Agent SDK avec clé, ou toute API tierce payante (OpenAI, ElevenLabs, Google Cloud, Azure Speech, Picovoice avec compte payant, etc.).
2. **Zéro paiement supplémentaire.** Tout ce qui n'est pas Claude Code doit être open source, gratuit, et tourner **100 % en local** : reconnaissance vocale, synthèse vocale, mot d'activation, interface, détection d'intentions.
3. **Ne jamais extraire ni manipuler le jeton OAuth** de Claude Code (`~/.claude/.credentials.json`, keychain Windows). On pilote le binaire `claude`, on ne réimplémente pas son authentification. Le jeton reste à l'intérieur du processus `claude`.
4. **Usage strictement personnel, mono-utilisateur.** FRIDAY ne doit pas être exposée sur le réseau (bind sur `127.0.0.1` uniquement), pas de partage, pas de boucle automatique qui interroge Claude sans action de ma part.
5. **Ne jamais utiliser `--bare`** avec `claude -p` : ce mode ignore la connexion OAuth de l'abonnement et exige une clé API.
6. **Ne jamais utiliser `--dangerously-skip-permissions`.** Les actions sensibles passent par une confirmation.
7. **Langue :** FRIDAY parle et comprend le **français**. Le code, les commentaires et les messages de commit peuvent être en anglais ; la documentation utilisateur (README) est en français.
8. **Plateforme :** Windows 10/11. Tester avec PowerShell, pas avec bash. Attention à l'encodage UTF-8 dans la console (accents).

Si une contrainte te semble impossible à respecter à un moment donné, **arrête-toi et demande-moi** au lieu de contourner.

---

## 1. Phase 0 — Vérifications avant de coder

Avant toute chose, vérifie et note dans un fichier `docs/environnement.md` :

- `claude --version` et `claude auth status` (ou `claude /status`) : Claude Code doit être installé et connecté à mon compte Pro. Si ce n'est pas le cas, dis-le-moi et arrête-toi.
- Un test minimal : `claude -p "Réponds uniquement : OK" --output-format json`. Vérifie que la réponse contient `"result"` et un `session_id`, et que la sortie n'indique aucune erreur d'authentification.
- **Modèles disponibles sur mon abonnement** : teste `claude -p "Réponds : OK" --model haiku`, puis `--model opus`, puis `--model fable` (et les identifiants complets si les alias ne passent pas, par ex. `claude-opus-5-5`, `claude-fable-5-1`, `claude-haiku-4-5`). Note lesquels fonctionnent réellement ; si un modèle est refusé, il ne doit pas apparaître dans la liste proposée par FRIDAY. Ne suppose rien : la disponibilité dépend du plan.
- Version de Python (≥ 3.11 attendu). Si absent, propose-moi l'installation (gratuite) et attends.
- Présence d'un GPU NVIDIA (`nvidia-smi`) : cela détermine la taille du modèle Whisper (voir §5.3).
- Périphériques audio disponibles (liste des micros et sorties). Prévois que je choisisse le micro dans la config.
- Espace disque disponible (les modèles Whisper/Piper pèsent quelques centaines de Mo).
- Vérifie qu'aucune variable `ANTHROPIC_API_KEY` ou `ANTHROPIC_AUTH_TOKEN` n'est définie dans l'environnement. Si oui, préviens-moi : le lanceur de FRIDAY devra les retirer de l'environnement du sous-processus `claude` pour garantir l'usage de l'abonnement.

**Ne poursuis pas tant que la Phase 0 n'est pas validée.**

---

## 2. Architecture cible

### 2.1 Principe

Un orchestrateur Python local, découpé en modules indépendants derrière des interfaces (ports/adaptateurs). Chaque composant doit être **remplaçable** sans toucher au reste (changer de moteur TTS = changer un adaptateur, pas le cœur).

```
friday/
├── core/                 # logique métier, aucune dépendance audio/UI
│   ├── assistant.py      # machine à états : IDLE → LISTENING → THINKING → SPEAKING
│   ├── ports.py          # interfaces : WakeWordDetector, SpeechToText, TextToSpeech, Brain, UI
│   ├── events.py         # bus d'événements interne (dataclasses)
│   ├── intents.py        # détection locale des commandes système (mode, modèle, sessions, stop)
│   ├── router.py         # choix automatique du modèle (simple → Haiku, complexe → Opus/Fable)
│   ├── sessions.py       # registre des sessions (nom, id Claude, mode, modèle, dossier, date)
│   └── safety.py         # politique de confirmation des actions sensibles
├── adapters/
│   ├── wakeword_openwakeword.py
│   ├── stt_faster_whisper.py
│   ├── tts_piper.py
│   ├── tts_windows_sapi.py     # repli si Piper indisponible
│   ├── brain_claude_code.py    # pilotage du binaire `claude` (modes Claude et Claude Code)
│   └── audio_io.py             # capture micro, lecture, VAD
├── permission_server/    # serveur MCP local qui reçoit les demandes de permission de Claude Code
├── ui/
│   ├── server.py         # FastAPI + WebSocket sur 127.0.0.1
│   └── static/           # HUD HTML/CSS/JS
├── config/
│   └── friday.example.yaml
├── scripts/
│   ├── install.ps1       # dépendances + téléchargement des modèles
│   ├── start.ps1
│   └── autostart.ps1     # enregistrement au démarrage de Windows
├── tests/
├── CLAUDE.md             # persona + règles pour les sessions lancées par FRIDAY
├── README.md
└── pyproject.toml
```

### 2.2 Machine à états

```
IDLE ──(mot "Friday" détecté)──► LISTENING ──(fin de phrase via VAD ou silence 1,5 s)──► THINKING
THINKING ──(réponse Claude)──► SPEAKING ──(fin de lecture)──► IDLE
N'importe quel état ──(mot "stop" ou clic Stop)──► IDLE (interrompt Claude et la lecture)
```

Règles :
- Pendant SPEAKING, le micro est **coupé** (ou le flux ignoré) pour éviter que FRIDAY s'entende elle-même (anti-écho). Exception : la détection du mot « stop » peut rester active si elle est fiable.
- Entre LISTENING et THINKING s'intercale la **détection d'intention locale** (§3.5) : si la phrase est une commande système (changer de modèle, de mode, de session), elle est traitée sans appeler Claude, donc sans consommer de quota.
- Pendant THINKING, l'interface montre que Claude travaille (et, si possible, quelle action il fait).
- Un timeout global par requête (configurable, 180 s par défaut) évite qu'une session bloquée fige FRIDAY.

---

## 3. Modes, modèles et sessions

### 3.1 Les deux modes

| | Mode Claude (« classique ») | Mode Claude Code |
|---|---|---|
| Usage | Discussion, questions, rédaction, réflexion | Actions sur le PC, fichiers, code, commandes |
| Lancement | `claude -p` avec **tous les outils désactivés** (`--tools ""` ou, si ce flag n'existe pas dans ma version, `--disallowedTools` couvrant tous les outils + `--permission-mode dontAsk`) | `claude -p` avec outils, `--permission-mode acceptEdits`, `--allowedTools` et serveur de permission (§4.4) |
| Persona | `CLAUDE.md` + consigne : « tu es en mode conversation, tu n'as pas accès à l'ordinateur ; si l'utilisateur demande une action, propose-lui de passer en mode Claude Code » | `CLAUDE.md` + consigne : « tu peux agir sur l'ordinateur, résume oralement, détaille dans `[AFFICHER]` » |
| Modèle par défaut | Router automatique (§3.3) | Modèle « complexe » de la config (Opus 5.5 par défaut) |

Vérifie en Phase 1 quelle combinaison de flags donne réellement un `claude -p` **sans aucun outil** (à confirmer avec `claude --help` de ma version) et documente-la dans `docs/journal.md`.

Le mode par défaut au démarrage est configurable (`default_mode: claude`). En mode Claude, si Claude répond qu'il faudrait agir sur le PC, FRIDAY me propose : « Tu veux que je passe en mode Claude Code ? » et attend un « oui ».

Option (à la voix : « ouvre Claude dans le navigateur ») : ouvrir `https://claude.ai` dans le navigateur par défaut. C'est un simple lancement de lien, FRIDAY ne pilote pas la page.

### 3.2 Modèles

- Passage du modèle au lancement : `--model haiku`, `--model opus`, `--model fable` (ou identifiants complets validés en Phase 0). Les noms parlés et leurs alias sont dans `friday.yaml` :
  ```yaml
  models:
    simple: haiku            # questions simples
    complex: opus            # tâches complexes, défaut du mode Claude Code
    alternatives:
      haiku: [haiku, "aïcou", "aiku"]     # variantes de prononciation reconnues par Whisper
      opus: [opus, "opus 5.5", "opus cinq cinq"]
      fable: [fable, "fable 5.1", "fable cinq un"]
  ```
- Changement en cours de session : envoyer `/model <alias>` comme message dans la session (supporté en `-p` sur les versions récentes) ; si cela échoue, relancer le processus avec `--model <alias> --resume <session_id>`. Tester les deux et retenir celle qui marche.
- FRIDAY annonce toujours le modèle actif après un changement (« Je passe sur Opus 5.5 ») et l'affiche dans l'interface.
- Si le modèle demandé n'est pas disponible sur mon abonnement (erreur `model_not_found` ou refus), FRIDAY le dit et reste sur le modèle courant.

### 3.3 Routage automatique simple/complexe (sans consommer de quota)

`router.py` choisit le modèle **localement**, sans appel à Claude :

- **Haiku** (simple) si : phrase courte (< ~20 mots), forme interrogative de connaissance (« qu'est-ce que », « c'est quoi », « combien », « quelle heure », « traduis », « définis », « explique en une phrase »), pas de référence à un fichier, un projet, un dossier, du code, ni de verbe d'action sur le PC.
- **Modèle complexe** (Opus 5.5 par défaut, Fable 5.1 si configuré) si : verbe d'action (« crée », « modifie », « corrige », « ouvre », « exécute », « cherche dans », « analyse », « refactorise », « déploie »), mention de fichier/dossier/projet/code, demande longue, demande de raisonnement (« compare », « conçois », « planifie », « pourquoi ça plante »), ou tout mode Claude Code.
- Cas ambigus → modèle complexe (mieux vaut une bonne réponse qu'une réponse rapide).
- Le choix automatique est **toujours surclassable** : si je dis « utilise Opus », « passe sur Haiku », « avec Fable », le modèle demandé s'impose jusqu'à nouvel ordre (`model_lock`), et « modèle automatique » réactive le routeur.
- Le routeur est un module pur, testé unitairement avec une liste de phrases d'exemple en français (fixtures), et ses règles sont éditables dans `friday.yaml`.

### 3.4 Sessions

FRIDAY tient un **registre local** `data/sessions.json` : pour chaque session, un nom parlé, le `session_id` Claude Code (issu de `system/init` ou du message `result`), le mode, le modèle, le dossier de travail, la date de création et de dernière utilisation, et un résumé d'une ligne (mis à jour à partir de la dernière réponse).

- **Créer** : « nouvelle session » / « nouvelle session pour le projet boucherie » → nouveau processus `claude -p` sans `--resume`, nommé automatiquement (« Session 3 ») ou avec le nom dicté.
- **Reprendre** : « reprends la session boucherie » / « retourne sur la session précédente » → `--resume <session_id>`. Le `--resume` par identifiant fonctionne quel que soit le dossier courant sur les versions récentes ; sinon relancer depuis le dossier d'origine enregistré dans le registre.
- **Lister** : « liste mes sessions » / « quelles sessions j'ai ? » → FRIDAY énumère à voix haute (nom, mode, date, résumé) et affiche la liste dans l'interface.
- **Renommer** : « renomme cette session en site restaurant ».
- **Supprimer** du registre : « oublie la session X » (confirmation demandée ; ne supprime pas la transcription Claude Code sur le disque).
- **Session courante** : « sur quelle session on est ? ».
- Correspondance des noms : tolérante (minuscules, accents, distance de Levenshtein ≤ 2) ; en cas d'ambiguïté FRIDAY demande laquelle.
- Optionnel (phase 8) : importer les sessions Claude Code existantes en lisant les transcriptions `~/.claude/projects/**/*.jsonl` (lecture seule), pour reprendre une session commencée dans un terminal.
- Une seule session est active à la fois ; changer de session ferme proprement le processus précédent.
- Le mode et le modèle sont **propres à chaque session** ; un changement de mode dans une session s'y applique et y est mémorisé.

### 3.5 Commandes vocales système (détection locale, hors Claude)

`intents.py` reconnaît par règles (mots-clés + expressions régulières, insensible aux accents et à la casse) et **sans appel à Claude** :

| Intention | Exemples de phrases |
|---|---|
| Changer de modèle | « utilise Opus », « passe sur Haiku », « prends Fable 5.1 », « modèle automatique » |
| Changer de mode | « passe en mode Claude Code », « repasse sur Claude », « mode conversation », « mode action » |
| Sessions | « nouvelle session… », « reprends la session… », « liste mes sessions », « renomme cette session en… », « session précédente » |
| État | « quel modèle tu utilises ? », « on est dans quel mode ? », « combien de requêtes aujourd'hui ? » |
| Contrôle | « stop », « annule », « répète », « coupe le micro », « ouvre Claude dans le navigateur » |

- Chaque commande est confirmée oralement en une phrase courte.
- Si une phrase ressemble à une commande sans correspondre exactement, FRIDAY demande (« Tu veux changer de modèle ? »).
- Toutes ces commandes ont un équivalent dans l'interface (menus déroulants modèle/mode, liste des sessions cliquable).
- Les phrases d'exemple ci-dessus sont des fixtures de tests unitaires.

---

## 4. Cœur : intégration de Claude Code

### 4.1 Commande de base

Piloter le vrai binaire `claude` en sous-processus :

```
claude -p --output-format stream-json --input-format stream-json --verbose --include-partial-messages --model <alias> [--resume <id>] [flags du mode]
```

- `--output-format stream-json` : événements JSON ligne par ligne, permettant d'afficher le texte au fur et à mesure et de commencer la synthèse vocale phrase par phrase.
- `--input-format stream-json` : permet de **garder le processus ouvert** et d'envoyer plusieurs messages sans redémarrer Claude Code à chaque phrase (gain de latence important).
- Repli si le mode bidirectionnel pose problème : un `claude -p "…"` par requête avec `--resume <session_id>` pour conserver le contexte.

### 4.2 Environnement du sous-processus

- Retirer `ANTHROPIC_API_KEY` et `ANTHROPIC_AUTH_TOKEN` de l'environnement transmis au sous-processus.
- Fixer `cwd` sur le dossier de travail de la session (par défaut `~/Friday/workspace`, ou le dossier de projet choisi pour cette session) pour que `CLAUDE.md` et les permissions du projet s'appliquent.
- Forcer l'encodage UTF-8 (`PYTHONIOENCODING=utf-8`, lecture de stdout en UTF-8).

### 4.3 Persona et contexte

- Écrire `CLAUDE.md` dans le dossier de travail : FRIDAY se présente comme un assistant vocal, répond en **français**, en **phrases courtes** adaptées à la lecture à voix haute (pas de markdown, pas de listes à puces, pas de blocs de code dans la réponse orale ; si un résultat technique est long, le résumer à l'oral et l'écrire dans un bloc `[AFFICHER]`).
- Compléter avec `--append-system-prompt` pour les consignes dynamiques : mode actif, date/heure, nom de l'utilisateur, nom de la session.
- Convention : Claude produit du texte oral naturel ; tout contenu technique va dans un bloc `[AFFICHER]…[/AFFICHER]` que l'orchestrateur envoie à l'interface sans le lire à voix haute. Documenter cette convention dans `CLAUDE.md`.

### 4.4 Permissions et outils (mode Claude Code uniquement)

- Mode de permission : `--permission-mode acceptEdits` dans le dossier de travail ; **jamais** `--dangerously-skip-permissions`.
- Liste d'autorisation explicite via `--allowedTools`, par exemple : `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash(dir *)`, `Bash(Get-ChildItem *)`, `Bash(python *)`, `Bash(git status *)`, `Bash(git log *)`, `Bash(start *)` (ouvrir une application ou un fichier). Cette liste vit dans `friday.yaml`.
- **Serveur de permission** : implémenter un petit serveur MCP local (`permission_server/`) et le passer avec `--permission-prompt-tool`. Quand Claude Code veut faire une action non autorisée par la liste, la demande arrive dans ce serveur → FRIDAY me la lit à voix haute (« Je dois exécuter la commande X, tu confirmes ? ») et l'affiche dans l'interface → je réponds « oui »/« non » à la voix ou par clic → le serveur renvoie la décision. Sans réponse en 30 s, refus.
- Liste noire absolue (`safety.py`) : toute commande contenant `Remove-Item -Recurse`, `rm -rf`, `format`, `diskpart`, `reg delete`, `shutdown`, `Stop-Computer`, `Restart-Computer`, modification du registre, désinstallation, envoi d'e-mail/message, ou touchant `C:\Windows` est **refusée** sauf confirmation vocale explicite en deux temps (« oui, confirme »).
- Journaliser chaque outil utilisé par Claude (nom, arguments résumés, décision) dans `logs/actions.log`.

### 4.5 Gestion des erreurs propres à Claude Code

- Exit code non nul ou événement `system/api_retry` avec `error: rate_limit` → FRIDAY dit : « J'ai atteint la limite de mon abonnement, réessaie plus tard » et affiche l'heure de réinitialisation si elle est présente. **Ne jamais relancer en boucle.** Proposer de basculer sur Haiku si la limite concerne seulement les gros modèles (à vérifier empiriquement).
- `authentication_failed` → « Ma connexion à Claude a expiré, lance `claude` dans un terminal pour te reconnecter. »
- `model_not_found` → « Ce modèle n'est pas disponible, je reste sur X. »
- Pas de réseau → détection rapide (ping DNS) et message vocal clair plutôt qu'un timeout de 3 minutes.
- Processus `claude` qui meurt → redémarrage automatique à la prochaine requête, avec `--resume` si un `session_id` est connu.
- Compteur des requêtes par modèle (heure/jour), affiché dans l'interface, pour surveiller ma consommation de quota Pro.

### 4.6 Interruption

- Le mot « stop » (ou bouton Stop) interrompt Claude et coupe la lecture audio. Sur Windows, tester la méthode qui fonctionne (fermeture de stdin, `CTRL_BREAK_EVENT`, ou kill + `--resume` de la session).

---

## 5. Pipeline audio (tout local, tout gratuit)

### 5.1 Mot d'activation « Friday »

- Moteur : **openWakeWord** (open source, CPU, hors ligne).
- openWakeWord fournit des modèles pré-entraînés (dont « hey Jarvis »). Pour « Friday » : entraîner un modèle personnalisé avec le notebook officiel gratuit d'openWakeWord. Si l'entraînement n'est pas faisable immédiatement, **livrer d'abord avec « hey Jarvis »**, mot d'activation **configurable**, puis prévoir la tâche « Friday » en dernière phase.
- Seuil de détection configurable ; tester les faux positifs avec musique/vidéo en fond.
- Retour immédiat au réveil : petit son + animation de l'orbe, avant même la transcription.
- Prévoir en plus un **raccourci clavier global** (ex. `Ctrl+Alt+F`) et un bouton dans l'interface en « push-to-talk ».

### 5.2 Détection de fin de phrase

- **Silero VAD** (gratuit, local) ; repli : seuil d'énergie + silence de 1,5 s (configurable).
- Durée max d'écoute : 20 s (configurable), puis retour à IDLE avec « Je n'ai rien compris ».

### 5.3 Reconnaissance vocale (parole → texte)

- Moteur : **faster-whisper** (local). Langue forcée `fr`.
- Choix du modèle selon le matériel : GPU NVIDIA → `medium` ou `large-v3` ; CPU seul → `small` (ou `base`). Configurable.
- Téléchargement une seule fois via `scripts/install.ps1`.
- Afficher la transcription dans l'interface avant de l'envoyer à Claude.
- Filtrer les transcriptions vides ou les hallucinations classiques de Whisper sur le silence (« Sous-titrage… », « Merci d'avoir regardé »).
- Ajouter un `initial_prompt` Whisper contenant les mots rares : « Friday, Claude, Claude Code, Haiku, Opus, Fable, session » pour améliorer leur reconnaissance.

### 5.4 Synthèse vocale (texte → parole)

- Moteur principal : **Piper TTS** (local, gratuit), voix française (`fr_FR-siwis-medium` ou `fr_FR-upmc-medium`), téléchargée par `install.ps1`.
- Repli : voix Windows intégrée (SAPI via `pyttsx3`).
- Lecture **phrase par phrase** dès que le flux de Claude produit une phrase complète.
- Nettoyer le texte avant lecture : retirer markdown, emojis, URLs longues, blocs `[AFFICHER]`.
- Interruption possible à tout moment (§4.6).

### 5.5 Audio I/O

- Bibliothèque : `sounddevice` (+ `numpy`). Sélection explicite du micro et de la sortie dans `friday.yaml`, avec une commande `friday devices` qui liste les périphériques.
- Micro capturé en continu à 16 kHz mono.
- Tester avec des écouteurs Bluetooth (changement de périphérique à chaud) : ne pas planter, se reconnecter au périphérique par défaut.

---

## 6. Interface utilisateur (HUD)

- Serveur **FastAPI** sur `127.0.0.1:<port>` avec WebSocket, front en HTML/CSS/JS pur. Fenêtre native via **pywebview** ; repli : navigateur par défaut.
- Contenu :
  - Orbe/anneau animé reflétant l'état (repos, écoute, réflexion, parole).
  - **Bandeau d'état** : mode actif (Claude / Claude Code), modèle actif (avec badge « auto » ou « verrouillé »), nom de la session, dossier de travail.
  - Transcription de ce que j'ai dit, réponse de FRIDAY en streaming.
  - Zone « Actions » : ce que Claude Code fait en temps réel et les demandes de confirmation avec boutons Oui/Non.
  - Zone « Affichage » pour le contenu technique (`[AFFICHER]`), rendu markdown/code.
  - **Panneau Sessions** : liste (nom, mode, modèle, date, résumé), boutons Nouvelle / Reprendre / Renommer / Oublier.
  - Sélecteurs déroulants Mode et Modèle (équivalents des commandes vocales).
  - Historique de la session, bouton Stop, bouton Push-to-talk, champ texte pour taper au lieu de parler.
  - Indicateurs : micro actif, modèle Whisper chargé, session Claude connectée, compteur de requêtes par modèle.
- Icône dans la zone de notification Windows (`pystray`) : Afficher/Masquer, Couper le micro, Quitter.
- Thème sombre par défaut, ambiance « HUD » sobre, variables CSS. Pas d'assets protégés par droit d'auteur (pas de visuels Marvel).

---

## 7. Configuration, journaux, données

- `config/friday.yaml` (copie de `friday.example.yaml` à l'installation) : mot d'activation, seuils, périphériques audio, modèle Whisper, voix Piper, dossier de travail par défaut, mode par défaut, modèles simple/complexe et alias, règles du routeur, liste `allowedTools`, port de l'UI, timeouts, langue.
- Validation de la config au démarrage avec messages d'erreur clairs.
- Journaux dans `logs/` avec rotation : `friday.log` (technique) et `actions.log` (actions de Claude et décisions de permission). Ne jamais journaliser de jeton ou de secret.
- `data/sessions.json` (registre) et `data/history.jsonl` (conversations), effaçables depuis l'interface.
- Aucune donnée n'est envoyée ailleurs qu'à Anthropic via le binaire `claude`.

---

## 8. Démarrage automatique et cycle de vie

- `scripts/autostart.ps1` : tâche planifiée Windows « FRIDAY » lancée à l'ouverture de session avec un délai de 30 s. Fournir la commande de désinstallation.
- Un seul exemplaire à la fois (verrou de processus).
- Arrêt propre : fermeture du sous-processus `claude`, sauvegarde du registre de sessions et de l'historique, libération du micro.
- Au redémarrage, FRIDAY reprend la **dernière session active** (mode et modèle inclus) et l'annonce : « Session site restaurant, mode Claude Code, Opus 5.5. »
- Modèles audio chargés une fois au démarrage ; afficher « Chargement… » pendant ce temps.

---

## 9. Qualité de code et tests

- Python 3.11+, `pyproject.toml`, `.venv`, dépendances épinglées.
- Principes SOLID : `core/` ne dépend d'aucun adaptateur ; injection de dépendances via une fabrique dans `main.py`.
- Typage (`mypy`-friendly), `ruff` pour lint/format.
- Tests `pytest` :
  - machine à états (transitions, interruption, timeouts) avec adaptateurs factices ;
  - `intents.py` : chaque phrase d'exemple du §3.5 (et des variantes avec fautes de transcription) est correctement classée ;
  - `router.py` : liste de phrases simples/complexes en français ;
  - `sessions.py` : création, reprise, renommage, correspondance tolérante des noms, persistance ;
  - `safety.py` (liste noire, confirmation en deux temps) ;
  - parsing des événements `stream-json` (fixtures enregistrées, y compris `system/init`, `result`, `api_retry`, `permission_denied`) ;
  - découpage phrase par phrase et nettoyage du texte pour le TTS ;
  - serveur de permission (accepter/refuser/timeout).
- Pas de test automatisé qui appelle réellement `claude` (quota). Un script manuel `scripts/smoke_test.ps1` fait un appel réel par mode et par modèle disponible.

---

## 10. Plan de travail par phases

Travaille **phase par phase**. À la fin de chaque phase : tests, commit git clair, mise à jour de `docs/journal.md` (fait, reste, décisions). **Attends ma validation avant la phase suivante.**

| Phase | Livrable | Critère de validation |
|---|---|---|
| 0 | `docs/environnement.md`, squelette, `install.ps1`, liste des modèles réellement disponibles | Phase 0 (§1) validée |
| 1 | Cerveau texte : `brain_claude_code.py` (deux modes), `CLAUDE.md`, CLI `friday chat` avec commandes `/mode`, `/model`, `/session` | Conversation multi-tours dans chaque mode, changement de modèle effectif, gestion erreur quota |
| 2 | `intents.py` + `router.py` + `sessions.py` avec tests | Commandes texte reconnues localement ; routage Haiku/Opus vérifié sur fixtures ; sessions créées/reprises/listées |
| 3 | Synthèse vocale Piper + lecture phrase par phrase + nettoyage | FRIDAY lit ses réponses en français, interruption « stop » clavier |
| 4 | Reconnaissance vocale push-to-talk + VAD + `initial_prompt` | Je parle, transcription affichée, Claude répond, FRIDAY parle ; « utilise Opus » à la voix fonctionne |
| 5 | Mot d'activation (openWakeWord) + anti-écho + son de réveil | « Friday » (ou « hey Jarvis » en attendant) réveille l'assistant, pas de faux positifs pendant la lecture |
| 6 | Serveur de permission MCP + `safety.py` + confirmations vocales | Action non autorisée → question vocale, « oui »/« non » fonctionnent, timeout = refus |
| 7 | Interface HUD complète (bandeau d'état, sessions, sélecteurs) + icône de notification | Tous les états visibles, changement de mode/modèle/session par clic |
| 8 | Démarrage automatique, verrou, reprise de la dernière session, README, import optionnel des sessions existantes | Redémarrage du PC → FRIDAY prête et annonce sa session |
| 9 | Durcissement : timeouts, reconnexion audio, compteurs, tests complets | Suite de tests verte, `smoke_test.ps1` OK |
| 10 | Modèle « Friday » personnalisé pour openWakeWord | Le mot « Friday » fonctionne avec < 1 faux positif/heure |

---

## 11. Check-list des oublis fréquents (à relire avant chaque commit)

- [ ] Aucune clé API, aucun service payant, aucun appel HTTP vers une API d'IA externe.
- [ ] `--bare` jamais utilisé ; `--dangerously-skip-permissions` jamais utilisé.
- [ ] Variables `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` retirées de l'environnement du sous-processus.
- [ ] Mode Claude = réellement aucun outil disponible (vérifié dans `system/init` : liste `tools` vide ou minimale).
- [ ] Les commandes système (mode, modèle, session, stop) sont traitées localement, sans appel à Claude.
- [ ] Seuls les modèles validés en Phase 0 sont proposés ; un modèle indisponible est annoncé, jamais silencieusement remplacé.
- [ ] Mode et modèle mémorisés par session ; annoncés à chaque changement et à la reprise.
- [ ] Serveur UI et serveur de permission liés à `127.0.0.1` uniquement.
- [ ] Micro coupé pendant que FRIDAY parle (anti-écho).
- [ ] Encodage UTF-8 partout (console Windows, stdout de `claude`, fichiers).
- [ ] Aucune boucle qui interroge Claude sans action de ma part.
- [ ] Erreur de quota et perte de réseau gérées par un message vocal clair, sans relance automatique.
- [ ] Toute action destructive ou irréversible passe par la confirmation en deux temps.
- [ ] Modèles audio téléchargés une seule fois ; `.gitignore` exclut `models/`, `logs/`, `data/`, `.venv/`, `config/friday.yaml`.
- [ ] README en français : installation, micro, mot d'activation, modes, modèles, sessions, reconnexion à Claude, désactivation du démarrage automatique.

---

## 12. Façon de travailler attendue de ta part

1. Commence par me poser les questions dont tu as besoin (nom d'utilisateur, dossier de travail par défaut, port, mode par défaut, modèle complexe préféré entre Opus 5.5 et Fable 5.1). Pose-les **toutes en une fois**, puis avance.
2. Si une bibliothèque prévue ici ne s'installe pas ou n'est plus maintenue, propose une alternative **gratuite et locale** et explique le compromis ; ne bascule jamais sur un service payant.
3. Si un flag de `claude` cité ici n'existe pas dans ma version, vérifie `claude --help`, trouve l'équivalent, et note-le dans `docs/journal.md`.
4. Explique brièvement chaque décision d'architecture dans `docs/journal.md`.
5. Ne fais aucune action en dehors du dossier du projet sans me le dire (sauf la tâche planifiée de la phase 8, annoncée avant).
6. Termine chaque phase par un résumé de trois lignes : ce qui marche, ce qui ne marche pas, la prochaine étape.
