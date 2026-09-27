# FRIDAY

Assistant vocal local pour Windows, en français, piloté par Claude Code (abonnement Claude, sans clé API).

> Projet en cours de construction. Ce README sera complété en phase 8 (installation, micro, mot d'activation, modes, modèles, sessions, démarrage automatique).

## Installation

Dans PowerShell, depuis le dossier du projet :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

## Discuter au clavier

```powershell
.venv\Scripts\friday chat
```

FRIDAY utilise Claude Code avec ton abonnement Claude (aucune clé API). Si elle dit que ta connexion a expiré, lance `claude` dans un terminal pour te reconnecter.

- **Mode Claude** : conversation pure, aucun accès à l'ordinateur.
- **Mode Claude Code** : FRIDAY agit sur les fichiers du dossier de travail (`workspace\` par défaut). Les suppressions et autres actions sensibles sont refusées tant que la confirmation vocale n'existe pas.

Parlez (ou tapez) naturellement ; ces commandes sont traitées sur votre PC, sans consommer de quota :

- **Modèle** : « utilise Opus », « passe sur Haiku », « avec Fable », « modèle automatique ». Par défaut FRIDAY choisit seule : Haiku pour les questions simples, Opus pour le reste (règles modifiables dans `config\friday.yaml`, section `router`).
- **Mode** : « passe en mode Claude Code », « repasse sur Claude », « mode conversation ».
- **Sessions** : « nouvelle session pour le projet boucherie », « reprends la session boucherie », « session précédente », « liste mes sessions », « renomme cette session en site restaurant », « oublie la session boucherie », « sur quelle session on est ? ».
- **État** : « quel modèle tu utilises ? », « on est dans quel mode ? », « combien de requêtes aujourd'hui ? ».
- **Contrôle** : « stop », « annule », « répète », « ouvre Claude dans le navigateur ».

Chaque session garde son mode, son modèle et sa conversation. Au redémarrage, FRIDAY reprend la dernière session. Raccourcis clavier : `/aide`.

### FRIDAY toujours à l'écoute

```powershell
.venv\Scripts\friday ecoute
```

- Dites **« Hey Jarvis »** (en attendant le mot « Friday »), ou appuyez sur **Ctrl+Alt+F** depuis n'importe quelle fenêtre, ou sur Entrée dans le terminal. Un petit son indique que FRIDAY vous écoute.
- Pour l'**interrompre** pendant qu'elle parle : redites « Hey Jarvis » (puis « stop » ou votre nouvelle demande), tapez `/stop`, ou Ctrl+C.
- Quand FRIDAY vous pose une question, répondez directement, sans redire le mot d'activation.
- « Coupe le micro » : FRIDAY n'écoute plus le mot d'activation (le raccourci reste actif) ; « réactive le micro » pour revenir.
- Réglages dans `config\friday.yaml`, section `wake_word` : `threshold` (plus haut = moins de faux déclenchements), `barge_in`, `hotkey`.
- Tant que rien ne la réveille, FRIDAY analyse le son **localement** et n'envoie rien à Claude.

### Parler à FRIDAY dans `friday chat`

Dans `friday chat`, appuyez sur **Entrée sans rien taper** : un petit son indique que FRIDAY écoute. Parlez, puis marquez une pause d'une seconde ; un second son indique la fin de l'écoute. FRIDAY affiche ce qu'elle a compris, puis répond.

- La reconnaissance vocale (Whisper) tourne sur votre carte graphique, entièrement en local.
- **Micro** : `audio.input_device` dans `config\friday.yaml` (nom donné par `friday devices`).
- Coupée trop tôt ? Augmentez `audio.end_silence_seconds`. Déclenchée par le bruit ? Montez `audio.vad_threshold`.
- `friday chat --sans-micro` : clavier seulement.

### Voix

FRIDAY lit ses réponses à voix haute (voix française Piper, 100 % locale), phrase par phrase dès que Claude commence à répondre. Le contenu technique (code, chemins, tableaux) est affiché mais jamais lu.

- **Couper la parole** : Ctrl+C, taper une nouvelle phrase, ou « stop ».
- **Sans la voix** : `.venv\Scripts\friday chat --muet`, ou `tts.enabled: false` dans `config\friday.yaml`.
- **Tester la voix** : `.venv\Scripts\friday dis Bonjour`.
- **Vitesse** : `tts.length_scale` (1.2 = plus lent, 0.9 = plus rapide). **Sortie audio** : `audio.output_device` (nom donné par `friday devices`).
- Si la voix Piper est absente, FRIDAY utilise la voix de Windows ; relancez `scripts\install.ps1` pour la télécharger.

Les actions de Claude sont journalisées dans `logs\actions.log`.

## Lister les micros et sorties audio

```powershell
.venv\Scripts\friday devices
```

Copie ensuite le **nom** du périphérique (entre guillemets) dans `config\friday.yaml` (`audio.input_device` et `audio.output_device`). Un extrait du nom suffit, sans se soucier des accents ni des majuscules. Si le périphérique est débranché, FRIDAY utilise celui par défaut de Windows.
