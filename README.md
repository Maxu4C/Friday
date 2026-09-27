# FRIDAY

Assistant vocal local pour Windows, en français, piloté par **Claude Code** avec votre abonnement Claude — **aucune clé API**, aucun service payant. La voix, la reconnaissance vocale et le mot d'activation tournent entièrement sur votre PC ; seules vos questions partent vers Claude, via le programme `claude` officiel.

## Sommaire

1. [Installation](#installation)
2. [Lancer FRIDAY](#lancer-friday)
3. [Démarrage automatique](#démarrage-automatique)
4. [Micro et sortie audio](#micro-et-sortie-audio)
5. [Mot d'activation](#mot-dactivation)
6. [Modes : Claude et Claude Code](#modes--claude-et-claude-code)
7. [Modèles](#modèles)
8. [Sessions](#sessions)
9. [Voix](#voix)
10. [Reconnexion à Claude](#reconnexion-à-claude)
11. [Autres commandes](#autres-commandes)
12. [Fichiers et confidentialité](#fichiers-et-confidentialité)

## Installation

Prérequis : Windows 10/11, [Claude Code](https://claude.com/claude-code) installé **et connecté** (lancez `claude` une fois dans un terminal), `uv` (`winget install --id=astral-sh.uv -e`). Une carte graphique NVIDIA accélère la reconnaissance vocale (sinon mettez `stt.device: cpu`).

Dans PowerShell, depuis le dossier du projet :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Le script installe Python 3.12 **dans le projet** (`.python\`), les dépendances, crée `config\friday.yaml`, puis télécharge une seule fois la voix, le modèle Whisper (~1,6 Go) et le mot d'activation dans `models\`.

Raccourci sur le Bureau :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\raccourci-bureau.ps1
```

## Lancer FRIDAY

Double-cliquez sur le raccourci **FRIDAY** du Bureau, ou :

```powershell
.venv\Scripts\friday
```

La fenêtre s'ouvre tout de suite sur **« Chargement… »** pendant que la voix, Whisper et le mot d'activation se chargent (quelques secondes), puis FRIDAY annonce sa session : « Session site restaurant, mode Claude Code, Opus 5.5. »

L'interface : l'orbe indique l'état (veille, écoute, réflexion, parole) ; le bandeau du haut change le **mode** et le **modèle** ; à droite, les **actions** de Claude Code (boutons **Oui / Non** pour les confirmations), le **contenu technique** et vos **sessions** ; en bas, **Parler**, le champ texte, **Micro** et **Stop** (ou Échap).

- **Un seul exemplaire** : relancer FRIDAY alors qu'elle tourne déjà ramène simplement sa fenêtre au premier plan.
- Fermer la fenêtre ne quitte pas FRIDAY : elle reste dans la zone de notification (icône en anneau près de l'horloge). Clic droit : Afficher/masquer, Couper le micro, **Quitter FRIDAY**.
- En quittant, FRIDAY ferme Claude proprement, enregistre ses sessions et l'historique de la conversation (réaffiché au prochain lancement), libère le micro et dit « À bientôt ».
- `friday hud --navigateur` : l'interface dans votre navigateur.

## Démarrage automatique

Pour que FRIDAY se lance à l'ouverture de votre session Windows (30 secondes après, le temps que le son et le réseau soient prêts) :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1
```

Cela crée une tâche planifiée Windows nommée **« FRIDAY »** (visible dans le Planificateur de tâches), sans droits administrateur. Au démarrage, FRIDAY reprend la **dernière session active** avec son mode et son modèle, et l'annonce.

**Désactiver** le démarrage automatique :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 -Desinstaller
```

Vérifier l'état : `scripts\autostart.ps1 -Etat`.

## Micro et sortie audio

```powershell
.venv\Scripts\friday devices
```

Copiez le **nom** du périphérique (entre guillemets) dans `config\friday.yaml` : `audio.input_device` (micro) et `audio.output_device` (haut-parleurs). Un extrait du nom suffit, sans se soucier des accents ni des majuscules ; `null` = périphérique par défaut de Windows. S'il est débranché, FRIDAY utilise celui par défaut.

- La reconnaissance vocale (Whisper) tourne sur votre carte graphique, entièrement en local.
- Coupée trop tôt ? Augmentez `audio.end_silence_seconds`. Déclenchée par le bruit ? Montez `audio.vad_threshold`.

## Mot d'activation

- Dites **« Hey Jarvis »** (en attendant le modèle « Friday »), appuyez sur **Ctrl+Alt+F** depuis n'importe quelle fenêtre, ou cliquez sur **Parler**. Un petit son indique que FRIDAY écoute ; parlez, puis marquez une pause d'une seconde.
- Pour l'**interrompre** pendant qu'elle parle : redites « Hey Jarvis » (puis « stop » ou votre nouvelle demande), ou Échap dans la fenêtre.
- Quand FRIDAY vous pose une question, répondez directement, sans redire le mot d'activation.
- « Coupe le micro » : FRIDAY n'écoute plus le mot d'activation (le raccourci reste actif) ; « réactive le micro » pour revenir.
- Réglages (section `wake_word`) : `threshold` (plus haut = moins de faux déclenchements), `barge_in`, `hotkey`.
- Tant que rien ne la réveille, FRIDAY analyse le son **localement** et n'envoie rien à Claude.

## Modes : Claude et Claude Code

- **Mode Claude** (par défaut) : conversation pure, aucun accès à l'ordinateur.
- **Mode Claude Code** : FRIDAY agit sur les fichiers du dossier de travail de la session (`workspace\` par défaut). Pour toute action hors de la liste autorisée (`claude.allowed_tools`), elle vous lit ce qu'elle veut faire, affiche la commande exacte et demande « Vous confirmez ? ». Répondez « oui » ou « non » (voix, clavier ou boutons). Les actions dangereuses (suppression récursive, formatage, registre, arrêt du PC, désinstallation, envoi d'e-mail, dossier Windows…) exigent en plus « **oui, confirme** ». Sans réponse en 30 secondes, elle refuse.

Pour changer : « passe en mode Claude Code », « repasse sur Claude », « mode conversation », ou le sélecteur **Mode**. Toutes les actions de Claude sont journalisées dans `logs\actions.log`.

## Modèles

- « utilise Opus », « passe sur Haiku », « avec Fable », ou le sélecteur **Modèle**.
- « modèle automatique » : FRIDAY choisit seule, Haiku pour les questions simples et Opus pour le reste (règles dans `config\friday.yaml`, section `router`).
- « quel modèle tu utilises ? », « combien de requêtes aujourd'hui ? ».

## Sessions

Chaque session garde son mode, son modèle, son dossier de travail et sa conversation avec Claude.

- « nouvelle session pour le projet boucherie », « reprends la session boucherie », « session précédente », « liste mes sessions », « renomme cette session en site restaurant », « oublie la session boucherie », « sur quelle session on est ? ». Les noms sont reconnus même mal prononcés.
- Au lancement, FRIDAY reprend la dernière session active.

**Reprendre une session Claude Code commencée ailleurs** (dans un terminal ou l'application Claude) : quittez FRIDAY, puis

```powershell
.venv\Scripts\friday importer
.venv\Scripts\friday importer 2 --nom "site restaurant"
```

La première commande liste vos sessions récentes (dossier, date, première demande) ; la seconde importe la n° 2 en mode Claude Code, dans son dossier d'origine. Les transcriptions de Claude (`~/.claude/projects`) sont seulement **lues**, jamais modifiées. Dites ensuite « reprends la session site restaurant ».

## Voix

FRIDAY lit ses réponses à voix haute (voix française Piper, 100 % locale), phrase par phrase dès que Claude commence à répondre. Le contenu technique (code, chemins, tableaux) est affiché mais jamais lu.

- **Choisir la voix** : `.venv\Scripts\friday voix` fait écouter les voix disponibles ; réglez `tts.voice` / `tts.speaker`.
- **Vitesse** : `tts.length_scale` (1.2 = plus lent, 0.9 = plus rapide) ; **douceur** : `tts.softness`.
- **Tester** : `.venv\Scripts\friday dis Bonjour`. **Sans la voix** : `tts.enabled: false`.
- Si la voix Piper est absente, FRIDAY utilise la voix de Windows ; relancez `scripts\install.ps1`.

## Reconnexion à Claude

FRIDAY utilise votre connexion Claude Code (abonnement). Si elle dit que la connexion a expiré ou qu'elle ne peut pas joindre Claude :

1. Ouvrez un terminal et lancez `claude`, puis suivez la connexion (`/login` si besoin).
2. Revenez à FRIDAY et reposez votre question : pas besoin de la relancer.

Si la limite d'utilisation de l'abonnement est atteinte, FRIDAY l'annonce avec l'heure de reprise. N'ajoutez **jamais** de variable `ANTHROPIC_API_KEY` : FRIDAY l'ignore volontairement.

## Autres commandes

| Commande | Rôle |
|---|---|
| `friday` | FRIDAY avec son interface (par défaut) |
| `friday hud --navigateur` / `--sans-fenetre` | interface dans le navigateur / sans fenêtre (affiche l'adresse) |
| `friday ecoute` | FRIDAY toujours à l'écoute dans le terminal, sans interface |
| `friday chat [--muet] [--sans-micro]` | discussion au clavier (Entrée vide = parler) ; `/aide` pour les raccourcis |
| `friday importer [n] [--nom X]` | importer une session Claude Code existante |
| `friday devices` / `friday voix` / `friday dis <texte>` | périphériques audio / choix de la voix / test de la voix |

Commandes vocales de contrôle : « stop », « annule », « répète », « ouvre Claude dans le navigateur ».

## Fichiers et confidentialité

- `config\friday.yaml` : vos réglages (non versionné). `config\persona.md` : la personnalité de FRIDAY.
- `data\` : sessions, historique, compteurs de requêtes. `logs\` : journaux (`friday.log`, `actions.log`). `models\` : modèles audio. Aucun de ces dossiers n'est envoyé sur GitHub.
- L'interface n'est accessible que depuis votre PC (adresse 127.0.0.1, clé secrète renouvelée à chaque lancement).
- FRIDAY n'interroge jamais Claude toute seule : chaque requête part d'une demande de votre part.
