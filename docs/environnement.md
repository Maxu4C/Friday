# Environnement — Phase 0

Relevé du 2026-09-27.

## Utilisateur

- Appellation : « Mr » ou « Mr Chemmane »
- Dossier de travail par défaut : `C:\Users\maxch\Friday\workspace`
- Port de l'interface : `8765` (bind `127.0.0.1`)
- Mode par défaut : `claude` (conversation)
- Modèle complexe : `opus`

## Claude Code

| Vérification | Résultat |
|---|---|
| `claude --version` | 2.1.283 (Claude Code), mis à jour depuis 2.1.272 |
| `claude auth status` | connecté, `authMethod: claude.ai`, `subscriptionType: max` (et non Pro) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | non définies |
| `claude -p "Réponds uniquement : OK" --output-format json` | OK : `result: "OK"`, `session_id` présent, `is_error: false`, modèle par défaut `claude-opus-5`. (Dans le bac à sable de la session de développement : échec `Failed to refresh OAuth token` ; hors bac à sable : OK.) |

### Modèles disponibles

| Demandé | Modèle réellement utilisé | Statut |
|---|---|---|
| `--model haiku` | `claude-haiku-4-5-20251001` | ✅ |
| `--model opus` | `claude-opus-5-5` | ✅ |
| `--model claude-opus-5-5` | `claude-opus-5-5` | ✅ |
| `--model fable` | `claude-fable-5-1` | ✅ |

Proposés par FRIDAY : **haiku (Haiku 4.5), opus (Opus 5.5), fable (Fable 5.1)**.

Historique : sur Claude Code 2.1.272, `opus` donnait `claude-opus-5` et `claude-opus-5-5` était refusé (« version 2.1.280 or newer is required »). Mis à jour vers **2.1.283** avec `claude update` le 2026-09-27.

## Système

| Élément | Résultat |
|---|---|
| OS | Windows 11 Home 10.0.26200 |
| Python | absent au départ ; **3.12.14 installé via uv** (`C:\Users\maxch\AppData\Roaming\uv\python\cpython-3.12.14-windows-x86_64-none`) ; `uv` 0.12.19 |
| GPU | NVIDIA GeForce RTX 4070 Ti, 12 Go, pilote 610.62 → Whisper `large-v3` (ou `medium`) sur CUDA |
| Disque C: | ~333 Go libres |
| git | 2.55.0 |

## Périphériques audio (endpoints Windows)

- Casque pour téléphone (A50 X Voice)
- Casque (3- USB Audio Device)
- Ligne (USB Audio Device)
- Microphone (USB Live camera audio)
- Microphone sur casque (2- USB Audio Device)
- ZOWIE XL LCD (NVIDIA High Definition Audio)
- MAG 272U X24 (NVIDIA High Definition Audio)

`friday devices` liste les indices `sounddevice` (MME, DirectSound, WASAPI, WDM-KS). Par défaut : entrée = « Microphone sur casque (2- USB Audio Device) », sortie = « Casque (3- USB Audio Device) ».
