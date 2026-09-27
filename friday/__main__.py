"""FRIDAY command-line entry point."""

from __future__ import annotations

import argparse
import sys


def _list_devices() -> int:
    import sounddevice as sd

    default_in, default_out = sd.default.device
    for index, device in enumerate(sd.query_devices()):
        hostapi = sd.query_hostapis(device["hostapi"])["name"]
        channels = []
        if device["max_input_channels"]:
            channels.append(f"in:{device['max_input_channels']}")
        if device["max_output_channels"]:
            channels.append(f"out:{device['max_output_channels']}")
        marks = ("*in" if index == default_in else "") + ("*out" if index == default_out else "")
        print(f"{index:>3}  {device['name']:<55} {hostapi:<22} {' '.join(channels):<12} {marks}")
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
