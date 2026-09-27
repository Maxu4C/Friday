"""Composition root: build FRIDAY's components from the configuration."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from friday.adapters.brain_claude_code import ClaudeCodeBrain
    from friday.adapters.microphone import Microphone
    from friday.config import FridayConfig
    from friday.core.controller import Controller
    from friday.core.narrator import Narrator
    from friday.core.ports import Ears
    from friday.core.wake import WakeWordDetector

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logger = logging.getLogger(__name__)


def setup_logging() -> None:
    from friday.config import PROJECT_ROOT

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    def handler(name: str) -> RotatingFileHandler:
        rotating = RotatingFileHandler(
            log_dir / name, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        rotating.setFormatter(logging.Formatter(LOG_FORMAT))
        return rotating

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler("friday.log"))
    actions = logging.getLogger("friday.actions")
    actions.addHandler(handler("actions.log"))
    actions.propagate = False
    _log_uncaught_errors()


def _log_uncaught_errors() -> None:
    """Without a console (desktop shortcut), a crash must at least leave a trace."""
    import threading

    crash = logging.getLogger("friday.crash")

    def on_error(kind: type[BaseException], error: BaseException, trace: Any) -> None:
        crash.critical("Unhandled error", exc_info=(kind, error, trace))

    def on_thread_error(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None:
            crash.critical(
                "Unhandled error in thread %s",
                args.thread.name if args.thread else "?",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

    sys.excepthook = on_error
    threading.excepthook = on_thread_error


def load() -> FridayConfig | None:
    """Validated configuration (errors printed in French), with logging set up."""
    from friday.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        return None
    setup_logging()
    return config


def create_brain(config: FridayConfig) -> ClaudeCodeBrain:
    from friday.adapters.brain_claude_code import BrainSettings, ClaudeCodeBrain
    from friday.core.ports import SessionState

    claude = config.claude
    settings = BrainSettings(
        binary=claude.binary,
        workspace=claude.workspace,
        runtime_dir=config.data_dir / "runtime",
        persona=claude.persona_file.read_text(encoding="utf-8"),
        user_names=config.user_names,
        code_tools=claude.code_tools,
        allowed_tools=claude.allowed_tools,
        confirm_tools=claude.confirm_tools,
        request_timeout=claude.request_timeout_seconds,
    )
    # Placeholder until Controller.start() loads the last active session.
    state = SessionState(mode=claude.default_mode, model=config.models.complex, name="Session 1")
    return ClaudeCodeBrain(settings, state)


def create_controller(config: FridayConfig) -> Controller:
    from friday.adapters.json_store import JsonFile
    from friday.core.controller import Controller, ControllerSettings
    from friday.core.intents import IntentParser
    from friday.core.router import Router

    models = config.models
    parser = IntentParser({alias: info.spoken for alias, info in models.available.items()})
    settings = ControllerSettings(
        model_labels={alias: info.label for alias, info in models.available.items()},
        simple_model=models.simple,
        complex_model=models.complex,
        default_mode=config.claude.default_mode,
        workspace=config.claude.workspace,
        permission_timeout=config.claude.permission_timeout_seconds,
    )
    return Controller(
        create_brain(config),
        parser,
        Router(config.router),
        settings,
        JsonFile(config.data_dir / "sessions.json"),
        JsonFile(config.data_dir / "usage.json"),
    )


def create_narrator(config: FridayConfig) -> Narrator:
    """Piper voice, or the Windows voice if Piper cannot be loaded."""
    from friday.adapters.audio_io import SoundDevicePlayer
    from friday.adapters.tts_piper import PiperTTS, VoiceStyle
    from friday.adapters.tts_windows_sapi import WindowsSapiTTS
    from friday.core.narrator import Narrator
    from friday.core.ports import TextToSpeech

    tts: TextToSpeech
    if config.tts.engine == "piper":
        style = VoiceStyle(
            length_scale=config.tts.length_scale,
            noise_scale=config.tts.noise_scale,
            noise_w_scale=config.tts.noise_w_scale,
            volume=config.tts.volume,
            softness=config.tts.softness,
            speaker=config.tts.speaker,
        )
        try:
            tts = PiperTTS(config.tts.models_dir, config.tts.voice, style)
        except Exception as exc:  # missing model, onnxruntime problem...
            logger.warning("Piper unavailable (%s), using SAPI", exc)
            print(f"Voix Piper indisponible ({exc}) : voix Windows utilisée.", file=sys.stderr)
            tts = WindowsSapiTTS()
    else:
        tts = WindowsSapiTTS()
    return Narrator(tts, SoundDevicePlayer(config.audio.output_device))


def create_ears(config: FridayConfig, microphone: Microphone | None = None) -> Ears:
    """Voice activity detection + Whisper; records from `microphone` when it is shared."""
    from friday.adapters.audio_io import (
        MicrophoneRecorder,
        SharedMicrophoneRecorder,
        SoundDevicePlayer,
    )
    from friday.adapters.stt_faster_whisper import FasterWhisperSTT
    from friday.adapters.vad import EnergyVAD, SileroVAD
    from friday.adapters.voice_input import Recorder, VoiceInput
    from friday.core.endpointing import EndpointSettings
    from friday.core.ports import VoiceActivityDetector

    audio, stt = config.audio, config.stt
    vad: VoiceActivityDetector
    try:
        vad = SileroVAD() if audio.vad == "silero" else EnergyVAD()
    except Exception as exc:
        logger.warning("Silero VAD unavailable (%s), using energy", exc)
        vad = EnergyVAD()
    settings = EndpointSettings(
        threshold=audio.vad_threshold,
        start_timeout=audio.listen_timeout_seconds,
        end_silence=audio.end_silence_seconds,
        max_seconds=audio.max_listen_seconds,
    )
    recognizer = FasterWhisperSTT(
        stt.model,
        stt.models_dir,
        device=stt.device,
        compute_type=stt.compute_type,
        initial_prompt=stt.initial_prompt,
        beam_size=stt.beam_size,
    )
    recorder: Recorder
    if microphone is not None:
        recorder = SharedMicrophoneRecorder(microphone.subscribe, vad, settings)
    else:
        recorder = MicrophoneRecorder(audio.input_device, vad, settings)
    cues = SoundDevicePlayer(audio.output_device) if audio.cues else None
    return VoiceInput(recorder, recognizer, cues)


def create_wake_detector(config: FridayConfig) -> WakeWordDetector:
    from friday.adapters.wakeword_openwakeword import OpenWakeWordDetector

    wake = config.wake_word
    return OpenWakeWordDetector(wake.models_dir, wake.model, wake.threshold)
