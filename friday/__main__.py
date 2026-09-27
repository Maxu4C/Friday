"""FRIDAY command-line entry point."""

from __future__ import annotations

import argparse
import sys


def _list_devices() -> int:
    from friday.adapters.audio_io import default_device_name, device_names, query_devices

    devices = query_devices()
    sections = (("input", "Micros", "input_device"), ("output", "Sorties", "output_device"))
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
    commands.add_parser("devices", help="liste les périphériques audio")

    args = parser.parse_args(argv)
    if args.command == "devices":
        return _list_devices()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
