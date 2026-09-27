# Journal de bord

## Correctif — raccourci du Bureau et Python (2026-09-27)

- Symptôme : le raccourci du Bureau affichait « No Python at …\AppData\Roaming\uv\python\cpython-3.12.14…\pythonw.exe ».
- Cause : les commandes de développement sont lancées depuis l'application Claude, empaquetée (MSIX). Windows **virtualise `AppData\Roaming`** pour ces applications : `uv python install` avait écrit Python dans `AppData\Local\Packages\Claude_…\LocalCache\Roaming\…`, visible seulement depuis l'application, pas depuis l'Explorateur ni un raccourci.
- Correctif : Python est installé **dans le projet** (`.python/`, ignoré par git, via `UV_PYTHON_INSTALL_DIR`), `.venv` recréé dessus ; `install.ps1` fait de même. Le reste était déjà hors de `AppData\Roaming` (modèles dans `models/`, `claude` dans `~\.local\bin`, données dans `data/`).

## Phase 7 — Interface HUD (2026-09-27)

### Fait
- **`friday`** (sans argument) lance FRIDAY avec son interface : fenêtre native **pywebview** (WebView2), repli sur le navigateur par défaut ; `friday hud --navigateur` ; `friday hud --sans-fenetre` (affiche l'adresse). `friday ecoute` reste la version terminal.
- **Serveur FastAPI + WebSocket lié à 127.0.0.1 uniquement**, avec un **jeton aléatoire renouvelé à chaque lancement** exigé pour ouvrir le WebSocket, et vérification de l'**Origin** : aucune page web ouverte dans un navigateur ne peut piloter FRIDAY via localhost. Messages malformés ou inconnus ignorés ; modèles et modes validés côté serveur.
- **HUD** (HTML/CSS/JS pur, aucune ressource externe, fonctionne hors ligne, aucun visuel protégé) : orbe animé par état (veille, écoute, réflexion, parole ; animations coupées si « réduire les animations » est activé) ; bandeau d'état (session, sélecteurs Mode et Modèle avec badge « auto »/« verrouillé », dossier de travail) ; conversation en direct (réponse en streaming, blocs `[AFFICHER]` retirés du fil) ; zone **Actions** (outils utilisés, refus, **demandes de confirmation avec boutons Oui/Non** et « Oui, confirme » pour les actions dangereuses) ; zone **Affichage** (blocs techniques rendus : code, titres, listes) ; **panneau Sessions** (Nouvelle, Reprendre, Renommer, Oublier) ; requêtes du jour par modèle et quota ; indicateurs micro, Whisper, voix, Claude, liaison ; barre du bas : Parler (push-to-talk), champ texte, Micro (couper/réactiver), Stop (et touche Échap). Tout texte reçu est échappé avant affichage.
- **Icône dans la zone de notification** (pystray, dessinée à l'exécution) : Afficher/masquer, Couper le micro (coché si coupé), Quitter. Fermer la fenêtre la masque : FRIDAY reste active.
- Une fenêtre qui se (re)connecte reçoit l'état complet et les 400 derniers messages.
- `friday/runtime.py` assemble voix, micro, reconnaissance, mot d'activation et raccourci pour le terminal comme pour le HUD (chaque partie peut échouer sans empêcher le reste). L'assistant accepte des commandes de l'interface (`execute`) et signale les blocs `[AFFICHER]` (`ShowBlock`), voix activée ou non.
- 361 tests, dont le serveur (jeton absent ou faux, page web étrangère, autre port local → refus 4403 ; session complète : snapshot, historique, texte, push-to-talk, modèle, commande inconnue ignorée, stop).

### Vérifié en réel
- `friday hud --sans-fenetre` ouvert dans un navigateur : connexion, session et sélecteurs remplis ; « modèle automatique » tapé → badge « auto » ; question à Claude → orbe orange (réflexion), réponse en streaming, orbe bleu (parole), formule du bloc `[AFFICHER]` rendue dans la zone Affichage, quota affiché.

### Incident corrigé
- Un ancien test appelait `friday` sans argument pour vérifier une erreur ; depuis que `friday` seul lance le HUD, ce test **a démarré FRIDAY pour de vrai** (micro ouvert) et bloqué la suite. Le micro a alors capté « passez en mode conversation » à 21 h 01 et changé le mode de la session en cours. Test remplacé (commande inconnue), aucun processus résiduel ; les suites de tests sont désormais lancées avec une limite de temps.

### Reste
- Fenêtre native et icône de notification à vérifier sur votre bureau (je ne vois pas votre écran).
- Démarrage automatique, verrou d'instance unique, import des sessions existantes : phase 8.

## Phase 6 — Permissions et confirmations vocales (2026-09-27)

### Fait
- **Demandes de permission de Claude Code transmises à FRIDAY** : en mode Claude Code, toute action hors `allowed_tools` et toute règle `confirm_tools` arrive sous forme de requête `can_use_tool` (outil, commande, description rédigée par Claude). FRIDAY la lit à voix haute (« Je dois exécuter une commande PowerShell : supprimer le fichier… Vous confirmez ? »), affiche la commande exacte, attend « oui » ou « non » (à la voix, ou au clavier), puis renvoie la décision à Claude Code.
- `friday/core/safety.py` — **liste noire du §4.4** : suppression récursive (`Remove-Item -Recurse`, `rm -rf`, `del /s`, `rd /s`), formatage et disques (`format`, `Format-Volume`, `diskpart`, `Clear-Disk`), registre (`reg add/delete`, `*-ItemProperty`, `HKLM:`/`HKCU:`), arrêt/redémarrage, désinstallation (`Uninstall-Package`, `msiexec /x`, `winget/choco uninstall`), envoi d'e-mail, tout chemin sous `C:\Windows`, `bcdedit`/`takeown`, et `git push --force`/`reset --hard`/`clean -f`. Ces actions exigent une **confirmation en deux temps** : « oui », puis « oui, confirme » explicite ; toute autre seconde réponse refuse.
- **Refus par défaut** : « non », « stop », « annule », une réponse incomprise, aucune réponse ou une réponse après **30 s** (`claude.permission_timeout_seconds`) → refus, annoncé oralement.
- Pendant l'attente de la réponse, le délai global de la requête (180 s) repart à zéro ; FRIDAY finit de poser la question avant d'écouter ; le mot d'activation est ignoré (elle écoute déjà) ; une réponse tapée est acceptée même si elle écoute.
- Toute autre requête de contrôle inattendue de Claude Code reçoit une erreur immédiate (Claude Code ne reste jamais bloqué).
- `logs/actions.log` : chaque outil demandé, la décision (allow/deny) et sa raison.
- 320 tests (politique de sécurité, requête réelle enregistrée, cerveau, contrôleur, chat, assistant vocal).

### Vérifié en réel (Claude Code 2.1.283)
- Suppression d'un fichier : question, « oui », fichier supprimé ; décision journalisée.
- Suppression récursive d'un dossier : « ACTION À RISQUE (suppression récursive) », « oui » puis « oui, confirme », dossier supprimé.
- Essai préalable : refus → Claude Code reçoit le refus et n'insiste pas ; le fichier reste en place.

### Décision : pas de serveur MCP séparé (écart assumé au §4.4)
- Le protocole prévoyait un serveur MCP local passé par `--permission-prompt-tool`. Claude Code 2.1.283 permet mieux : `--permission-prompts host --permission-prompt-tool stdio`, le mécanisme du SDK officiel, qui envoie les demandes de permission **sur le canal stream-json déjà ouvert** entre FRIDAY et Claude Code. Résultat identique (Claude Code demande, FRIDAY répond), avec moins de pièces : aucun processus supplémentaire, **aucun port réseau**, aucune communication inter-processus à sécuriser. Le paquet vide `friday/permission_server/` a été retiré ; la logique vit dans `core/safety.py` et `core/controller.py`.
- Sans `--permission-prompt-tool stdio`, `--permission-prompts host` seul refuse d'office (vérifié) : les deux options sont nécessaires.

### Reste
- Affichage des demandes dans le HUD avec boutons Oui/Non : phase 7.

## Phase 5 — Mot d'activation, anti-écho, écoute permanente (2026-09-27)

### Fait
- **openWakeWord 0.6** (gratuit, hors ligne, CPU, inférence ONNX) avec le modèle pré-entraîné **« hey Jarvis »** (`models/openwakeword/`, quelques Mo, téléchargés une fois depuis les versions officielles GitHub du projet). Seuil configurable (`wake_word.threshold`). Tout modèle `.onnx` déposé dans ce dossier peut servir (« Friday » en phase 10).
- `friday ecoute` : FRIDAY **toujours à l'écoute**. Déclencheurs : mot d'activation, **raccourci global Ctrl+Alt+F** (pynput, fonctionne même fenêtre non active et micro coupé), touche Entrée, ou demande tapée au clavier. `/stop` ou Ctrl+C coupent la parole ; Ctrl+C au repos quitte.
- `friday/core/assistant.py` : **machine à états IDLE → LISTENING → THINKING → SPEAKING → IDLE**, déclencheurs mis en file d'attente depuis n'importe quel fil, « stop » immédiat (interrompt Claude et la voix). Quand FRIDAY pose une question après une demande orale (« Voulez-vous passer en mode Claude Code ? »), elle écoute la réponse **sans qu'il faille redire le mot d'activation**.
- `friday/adapters/microphone.py` : **un seul flux micro permanent** partagé entre le mot d'activation et l'enregistrement de la demande (aucun mot perdu entre les deux) ; réouverture automatique si le micro disparaît (casque débranché).
- `friday/core/wake.py` — **anti-écho** : le détecteur n'est pas alimenté pendant l'écoute d'une demande ; 0,6 s de surdité après que FRIDAY a fini de parler (écho des haut-parleurs) ; audio accumulé pendant les pauses jeté avant de reprendre. **Interruption vocale fiable** (`wake_word.barge_in`) : dire le mot d'activation pendant que FRIDAY parle ou réfléchit la coupe et l'écoute — c'est le « stop » vocal robuste (FRIDAY ne prononce jamais « hey Jarvis »), puis « stop », « annule » ou une nouvelle demande.
- Retour immédiat au réveil : carillon d'écoute joué avant même la transcription (l'orbe animée viendra avec le HUD).
- Nouvelle commande « réactive le micro » (« coupe le micro » désactive le mot d'activation ; le raccourci reste actif).
- `friday/console.py` (affichage terminal partagé) et `friday/core/voice.py` (voix des sorties du contrôleur) : `friday chat` et `friday ecoute` utilisent le même code. `friday/factory.py` regroupe les fabriques.
- 281 tests.

### Mesuré / vérifié
- Détecteur réel : « Hé, Jarvisse » prononcé par Piper → 0,75 (détecté) ; phrases ordinaires → 0,00.
- `friday ecoute` démarre (voix, micro partagé, mot d'activation, Whisper sur GPU, raccourci) et répond, en 7 s de bout en bout.

### Décisions
- « stop » vocal pendant la parole = mot d'activation puis commande : transcrire tout ce qu'entend le micro pendant que FRIDAY parle capterait sa propre voix sur des haut-parleurs (écho) ; le mot d'activation est, lui, fiable.
- Le micro reste ouvert en permanence mais **seul** le détecteur local l'analyse au repos ; rien n'est envoyé à Claude sans mot d'activation, raccourci ou saisie (aucune boucle automatique).

### Reste
- Test de faux positifs avec musique ou vidéo en fond : à faire avec vous (je ne peux pas diffuser de son dans votre pièce et écouter en même temps).
- Modèle « Friday » personnalisé : phase 10.

## Phase 4 — Reconnaissance vocale, push-to-talk (2026-09-27)

### Fait
- **faster-whisper 1.2.1** (CTranslate2 4.8.2) sur la **RTX 4070 Ti** (CUDA via les paquets pip `nvidia-cublas-cu12` et `nvidia-cudnn-cu12`, rendus visibles par `os.add_dll_directory`), modèle **large-v3-turbo** dans `models/whisper` (téléchargé une fois, puis chargé hors ligne avec `local_files_only`). Langue forcée `fr`, `initial_prompt` avec les mots rares (Friday, Claude, Haiku, Opus, Fable, session, Mr Chemmane). Repli automatique sur CPU (int8).
- **Silero VAD v6** (fourni avec faster-whisper, exécuté par onnxruntime) en flux continu : trames de 32 ms, état récurrent conservé entre les trames. Repli : détecteur d'énergie avec plancher de bruit adaptatif (`audio.vad: energy`).
- `friday/core/endpointing.py` : début de parole après 0,2 s de voix continue (les clics sont ignorés), 0,3 s de pré-enregistrement, fin après `end_silence_seconds` (1 s) avec hystérésis pour ne pas couper les fins de mots, 20 s maximum, « Je n'ai rien entendu » après 6 s sans parole.
- `friday/core/transcript.py` : filtre des hallucinations de Whisper sur le silence (« Sous-titrage ST' 501 », « Merci d'avoir regardé », Amara.org…) ; segments marqués « pas de parole » par Whisper écartés.
- `MicrophoneRecorder` : micro choisi **par son nom**, 16 kHz mono ; `VoiceInput` : petit carillon au début et à la fin de l'écoute (sons générés, aucun fichier), enregistrement, transcription.
- `friday chat` : **Entrée sans rien taper = parler** (push-to-talk). La transcription est affichée (« Vous (voix) > … ») puis traitée exactement comme une phrase tapée : « utilise Opus » à la voix change de modèle sans appeler Claude. La voix de FRIDAY est coupée avant d'écouter (jamais d'enregistrement de sa propre voix). `--sans-micro` pour le clavier seul.
- Config `audio` (vad, seuils, délais, carillons) et `stt` (modèle, device, compute_type, beam_size, initial_prompt).
- 266 tests, dont une chaîne réelle sans micro : phrase dite par Piper → Silero → fin de phrase → Whisper → reconnue comme la commande `SetModel("opus")`.

### Mesuré
- Whisper large-v3-turbo sur GPU : **0,26 s** pour transcrire 4,2 s de parole (transcription exacte de « Friday, utilise Opus et crée une nouvelle session pour le projet boucherie »).
- Micro du casque (« Microphone sur casque (2- USB Audio Device) ») accessible à 16 kHz.

### Décisions
- **large-v3-turbo** plutôt que large-v3 : même famille (écart de précision minime en français), environ deux fois plus léger et plus rapide ; `large-v3` reste configurable.
- Fin de phrase à **1 s** de silence avec Silero (plus réactif que les 1,5 s prévus pour le repli par énergie, qui reste réglable).
- Le push-to-talk passe par la touche Entrée dans le terminal ; le **raccourci global Ctrl+Alt+F** et le bouton de l'interface arrivent avec l'écoute permanente (phase 5) et le HUD (phase 7), qui remplacent la boucle `input()` du terminal.

### Reste
- Test réel avec votre voix (je ne peux pas parler dans votre micro).
- Mot d'activation, anti-écho, « stop » vocal pendant la parole : phase 5.

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

### Ajustement demandé : voix plus lente et plus douce (« comme FRIDAY dans Iron Man »)
- Style par défaut : `length_scale` 1.2 (plus lent), `noise_scale` 0.5 et `noise_w_scale` 0.6 (intonation et rythme plus réguliers, plus posés), `volume` 0.85, `softness` 0.5 (filtre passe-bas binomial à 5 coefficients mélangé au signal : adoucit les sifflantes).
- Seconde voix féminine téléchargée pour comparer : `fr_FR-upmc-medium`, locutrice « jessica » (`tts.speaker`). `friday voix` fait écouter les deux avec le style configuré.
- Limite : les voix Piper françaises gratuites n'ont pas l'accent irlandais de la FRIDAY du film ; on approche surtout le ton calme et doux.

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
