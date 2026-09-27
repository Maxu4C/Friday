# FRIDAY

Assistant vocal local pour Windows, en français, piloté par Claude Code (abonnement Claude, sans clé API).

> Projet en cours de construction. Ce README sera complété en phase 8 (installation, micro, mot d'activation, modes, modèles, sessions, démarrage automatique).

## Installation

Dans PowerShell, depuis le dossier du projet :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

## Lister les micros et sorties audio

```powershell
.venv\Scripts\friday devices
```

Copie ensuite le **nom** du périphérique (entre guillemets) dans `config\friday.yaml` (`audio.input_device` et `audio.output_device`). Un extrait du nom suffit, sans se soucier des accents ni des majuscules. Si le périphérique est débranché, FRIDAY utilise celui par défaut de Windows.
