# Journal de bord

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
