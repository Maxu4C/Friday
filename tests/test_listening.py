"""Phase 4: end of speech detection, transcript filtering, ears, push-to-talk."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from friday.adapters.vad import EnergyVAD
from friday.adapters.voice_input import VoiceInput
from friday.chat import ChatSession
from friday.core.endpointing import Endpoint, Endpointer, EndpointSettings
from friday.core.intents import SetModel
from friday.core.ports import AudioClip, Heard
from friday.core.transcript import clean_transcript
from tests.test_controller import PARSER, Harness
from tests.test_voice import RecordingNarrator

FRAME = b"\x00\x00" * 512
SETTINGS = EndpointSettings(start_timeout=2.0, end_silence=0.5, max_seconds=5.0)


def run(probabilities: list[float]) -> tuple[Endpoint, int]:
    endpointer = Endpointer(SETTINGS)
    state = Endpoint.WAITING
    for probability in probabilities:
        state = endpointer.push(FRAME, probability)
        if state in (Endpoint.DONE, Endpoint.NO_SPEECH):
            break
    return state, len(endpointer.audio()) // len(FRAME)


# -- end of speech -----------------------------------------------------------------------


def test_utterance_ends_after_silence() -> None:
    state, frames = run([0.0] * 20 + [0.9] * 40 + [0.1] * 30)
    assert state is Endpoint.DONE
    # pre-roll (~9 frames) + speech (40) + at most ~0.2 s of the final silence
    assert 45 <= frames <= 60


def test_nobody_speaks() -> None:
    assert run([0.1] * 100)[0] is Endpoint.NO_SPEECH


def test_short_click_does_not_start_an_utterance() -> None:
    assert run([0.0] * 10 + [0.9, 0.9] + [0.0] * 100)[0] is Endpoint.NO_SPEECH


def test_soft_word_endings_do_not_cut_the_sentence() -> None:
    # probabilities just under the threshold (hysteresis) keep the utterance going
    state, frames = run([0.9] * 20 + [0.4] * 30 + [0.9] * 10 + [0.0] * 20)
    assert state is Endpoint.DONE and frames >= 60


def test_maximum_length() -> None:
    state, frames = run([0.9] * 1000)
    assert state is Endpoint.DONE and frames <= round(5.0 / 0.032)


# -- transcripts --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        (" Utilise Opus. ", "Utilise Opus"),
        ("Quelle heure est-il ?", "Quelle heure est-il ?"),
        ("Sous-titrage ST' 501", None),
        ("Sous-titres réalisés par la communauté d'Amara.org", None),
        ("Merci d'avoir regardé cette vidéo !", None),
        ("...", None),
        ("", None),
        ("Merci merci merci merci", None),
        ("Merci d'avoir regardé mon code, peux-tu corriger la fonction main de mon script ?",
         "Merci d'avoir regardé mon code, peux-tu corriger la fonction main de mon script ?"),
    ],
)  # fmt: skip
def test_clean_transcript(raw: str, clean: str | None) -> None:
    assert clean_transcript(raw) == clean


# -- voice activity -------------------------------------------------------------------------


def frames_of(samples: np.ndarray) -> list[bytes]:
    pcm = (samples * 32767).astype(np.int16)
    usable = len(pcm) - len(pcm) % 512
    return [pcm[i : i + 512].tobytes() for i in range(0, usable, 512)]


def test_energy_vad_separates_voice_from_quiet_room() -> None:
    rng = np.random.default_rng(0)
    quiet = rng.normal(0, 0.002, 16000)
    t = np.arange(16000) / 16000
    loud = 0.3 * np.sin(2 * np.pi * 220 * t)
    vad = EnergyVAD()
    quiet_probs = [vad.probability(f) for f in frames_of(quiet)]
    loud_probs = [vad.probability(f) for f in frames_of(loud)]
    assert max(quiet_probs[5:]) < 0.5 < min(loud_probs[:10])


# -- ears -----------------------------------------------------------------------------------


class FakeRecorder:
    def __init__(self, clip: AudioClip | None) -> None:
        self.clip = clip

    def record(self, cancelled: Callable[[], bool] = lambda: False) -> AudioClip | None:
        return self.clip


class FakeSTT:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, clip: AudioClip) -> str:
        return self.text


class FakeOutput:
    def __init__(self) -> None:
        self.clips: list[AudioClip] = []

    def play(self, clip: AudioClip, cancelled: Callable[[], bool]) -> None:
        self.clips.append(clip)


CLIP = AudioClip(b"\x01\x00" * 16000, 16000)


def test_ears_hear_a_sentence_with_chimes() -> None:
    cues = FakeOutput()
    heard = VoiceInput(FakeRecorder(CLIP), FakeSTT(" Utilise Opus."), cues).listen()
    assert heard == Heard("Utilise Opus", "")
    assert len(cues.clips) == 2


def test_ears_report_silence_and_nonsense() -> None:
    assert VoiceInput(FakeRecorder(None), FakeSTT("x")).listen() == Heard(None, "silence")
    assert VoiceInput(FakeRecorder(CLIP), FakeSTT("Sous-titrage ST' 501")).listen() == Heard(
        None, "incompris"
    )


# -- push-to-talk in the chat ------------------------------------------------------------


class FakeEars:
    def __init__(self, *heard: Heard) -> None:
        self.heard = list(heard)

    def listen(self) -> Heard:
        return self.heard.pop(0)


def test_voice_command_is_handled_locally() -> None:
    harness, narrator = Harness(), RecordingNarrator()
    ears = FakeEars(Heard("Utilise Opus"))
    chat = ChatSession(
        harness.controller,
        write=lambda _: None,
        read=lambda _: "",
        narrator=narrator,  # type: ignore[arg-type]
        ears=ears,
    )
    assert chat.listen()
    assert narrator.said == ["Je passe sur Opus 5.5."]
    assert harness.brain.sent == []


def test_voice_question_goes_to_claude_and_silence_is_reported() -> None:
    harness, narrator = Harness(), RecordingNarrator()
    ears = FakeEars(Heard(None, "silence"), Heard(None, "incompris"), Heard("Quelle heure ?"))
    output: list[str] = []
    chat = ChatSession(
        harness.controller,
        write=output.append,
        read=lambda _: "",
        narrator=narrator,  # type: ignore[arg-type]
        ears=ears,
    )
    chat.listen()
    chat.listen()
    chat.listen()
    assert narrator.said[:2] == ["Je n'ai rien entendu.", "Je n'ai rien compris."]
    assert "Vous (voix) > Quelle heure ?\n" in output
    assert harness.brain.sent[0][0] == "Quelle heure ?"


def test_empty_line_triggers_listening_in_run() -> None:
    harness = Harness()
    answers = iter(["", "/quitter"])
    ears = FakeEars(Heard("modèle automatique"))
    ChatSession(
        harness.controller, write=lambda _: None, read=lambda _: next(answers), ears=ears
    ).run()
    assert ears.heard == []


# -- real models (only when downloaded) -------------------------------------------------

ROOT = Path(__file__).parents[1]
PIPER = ROOT / "models" / "piper" / "fr_FR-siwis-medium.onnx"
WHISPER = ROOT / "models" / "whisper"


def spoken(text: str) -> np.ndarray:
    """French speech at 16 kHz, produced by the Piper voice.

    Noise scales at 0 make the synthesis deterministic: with Piper's default random
    sampling the same sentence scores anywhere between 0.44 and 0.98 on the wake word.
    """
    from piper import PiperVoice, SynthesisConfig

    voice = PiperVoice.load(PIPER)
    config = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0)
    audio = np.concatenate([c.audio_int16_array for c in voice.synthesize(text, config)])
    x = audio.astype(np.float32) / 32768
    count = int(len(x) * 16000 / voice.config.sample_rate)
    return np.interp(np.linspace(0, len(x) - 1, count), np.arange(len(x)), x)


@pytest.mark.skipif(not PIPER.exists(), reason="Piper voice not downloaded")
def test_silero_finds_the_sentence_in_silence() -> None:
    from friday.adapters.vad import SileroVAD

    audio = np.concatenate([np.zeros(8000), spoken("Bonjour Friday."), np.zeros(32000)])
    vad, endpointer = SileroVAD(), Endpointer(EndpointSettings(end_silence=0.8))
    states = [endpointer.push(f, vad.probability(f)) for f in frames_of(audio)]
    assert Endpoint.SPEAKING in states and states[-1] is Endpoint.DONE
    assert 0.6 < len(endpointer.audio()) / 2 / 16000 < 2.5


@pytest.mark.skipif(
    not (PIPER.exists() and any(WHISPER.glob("*large-v3-turbo*"))),
    reason="Piper voice or Whisper model not downloaded",
)
def test_spoken_command_is_transcribed_and_recognized() -> None:
    from friday.adapters.stt_faster_whisper import FasterWhisperSTT

    audio = spoken("Friday, utilise Opus.")
    clip = AudioClip((audio * 32767).astype(np.int16).tobytes(), 16000)
    stt = FasterWhisperSTT(
        "large-v3-turbo", WHISPER, initial_prompt="Friday, Claude, Haiku, Opus, Fable"
    )
    text = clean_transcript(stt.transcribe(clip))
    assert text is not None
    assert PARSER.parse(text) == SetModel("opus")
