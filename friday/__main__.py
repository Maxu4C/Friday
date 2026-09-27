"""FRIDAY command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from friday.factory import create_controller, create_ears, create_narrator, load

logger = logging.getLogger(__name__)


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _listen_app() -> int:
    from friday.voice_app import run_voice_app

    config = load()
    if config is None:
        return 2
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    return run_voice_app(config, _write)


def _chat(mute: bool, no_mic: bool) -> int:
    from friday.chat import ChatSession

    config = load()
    if config is None:
        return 2
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    narrator = None if mute or not config.tts.enabled else create_narrator(config)
    ears = None
    if not no_mic:
        _write("Chargement de la reconnaissance vocale…\n")
        try:
            ears = create_ears(config)
        except Exception as exc:
            logger.exception("Speech recognition unavailable")
            _write(f"Reconnaissance vocale indisponible ({exc}) : clavier seulement.\n")
    session = ChatSession(
        create_controller(config), write=_write, read=input, narrator=narrator, ears=ears
    )
    return session.run()


VOICE_SAMPLES = (
    (
        "A",
        "fr_FR-siwis-medium",
        None,
        "Voix A. Bonsoir Mister Chemmane. Tous les systèmes sont opérationnels. "
        "Je reste à votre disposition.",
    ),
    (
        "B",
        "fr_FR-upmc-medium",
        "jessica",
        "Voix B. Bonsoir Mister Chemmane. Tous les systèmes sont opérationnels. "
        "Je reste à votre disposition.",
    ),
)


def _voices() -> int:
    """Play each candidate voice with the configured slow and soft style."""
    from friday.adapters.audio_io import SoundDevicePlayer
    from friday.adapters.tts_piper import PiperTTS, VoiceStyle

    config = load()
    if config is None:
        return 2
    tts = config.tts
    player = SoundDevicePlayer(config.audio.output_device)
    for label, voice, speaker, text in VOICE_SAMPLES:
        if not (tts.models_dir / f"{voice}.onnx").exists():
            print(f"Voix {label} ({voice}) absente : python -m piper.download_voices {voice}")
            continue
        style = VoiceStyle(
            tts.length_scale, tts.noise_scale, tts.noise_w_scale, tts.volume, tts.softness, speaker
        )
        print(f"Voix {label} : voice: {voice}" + (f", speaker: {speaker}" if speaker else ""))
        player.play(PiperTTS(tts.models_dir, voice, style).synthesize(text), lambda: False)
    print(
        "Réglez tts.voice / tts.speaker dans config\\friday.yaml ; tts.length_scale pour le "
        "débit et tts.softness pour la douceur."
    )
    return 0


def _say(text: str) -> int:
    config = load()
    if config is None:
        return 2
    narrator = create_narrator(config)
    narrator.say(text)
    narrator.wait()
    narrator.close()
    return 0


def _list_devices() -> int:
    from friday.adapters.audio_io import Kind, default_device_name, device_names, query_devices

    devices = query_devices()
    sections: tuple[tuple[Kind, str, str], ...] = (
        ("input", "Micros", "input_device"),
        ("output", "Sorties", "output_device"),
    )
    for kind, title, key in sections:
        default = default_device_name(devices, kind)
        print(f"{title} (audio.{key}) :")
        for name in device_names(devices, kind):
            mark = "   <- défaut Windows" if name == default else ""
            print(f'  "{name}"{mark}')
        print()
    print("Copie un nom entre guillemets dans config\\friday.yaml (null = défaut Windows).")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="friday", description="FRIDAY, assistant vocal local")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ecoute", help="FRIDAY à l'écoute : mot d'activation, raccourci, clavier")
    chat = commands.add_parser("chat", help="discute avec FRIDAY au clavier (Entrée = parler)")
    chat.add_argument("--muet", action="store_true", help="réponses écrites seulement")
    chat.add_argument("--sans-micro", action="store_true", help="clavier seulement")
    say = commands.add_parser("dis", help="fait prononcer un texte à FRIDAY (test de la voix)")
    say.add_argument("texte", nargs="+")
    commands.add_parser("voix", help="fait écouter les voix disponibles pour choisir")
    commands.add_parser("devices", help="liste les périphériques audio")

    args = parser.parse_args(argv)
    if args.command == "ecoute":
        return _listen_app()
    if args.command == "devices":
        return _list_devices()
    if args.command == "chat":
        return _chat(args.muet, args.sans_micro)
    if args.command == "dis":
        return _say(" ".join(args.texte))
    if args.command == "voix":
        return _voices()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
