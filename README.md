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

Chaque session garde son mode, son modèle et sa conversation. Au redémarrage, FRIDAY reprend la dernière session. Raccourcis clavier : `/aide`. **Ctrl+C** interrompt une réponse.

Les actions de Claude sont journalisées dans `logs\actions.log`.

## Lister les micros et sorties audio

```powershell
.venv\Scripts\friday devices
```

Copie ensuite le **nom** du périphérique (entre guillemets) dans `config\friday.yaml` (`audio.input_device` et `audio.output_device`). Un extrait du nom suffit, sans se soucier des accents ni des majuscules. Si le périphérique est débranché, FRIDAY utilise celui par défaut de Windows.
