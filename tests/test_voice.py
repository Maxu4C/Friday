"""Phase 3: text cleaning, sentence splitting, the narrator and spoken chat answers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from friday.chat import ChatSession
from friday.core.narrator import Narrator
from friday.core.ports import AudioClip
from friday.core.speech import Display, Segment, Speak, SpeechStream, clean_for_speech
from tests.fakes import answer
from tests.test_controller import Harness

# -- cleaning ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("**Bonjour** Mr Chemmane !", "Bonjour Mister Chemmane !"),
        ("## Titre\n- point un\n- point deux", "Titre point un point deux"),
        ("Lancez `pytest` maintenant.", "Lancez pytest maintenant."),
        ("Voir [la doc](https://example.com/a/b).", "Voir la doc."),
        ("Lien : https://docs.python.org/3/library/re.html", "Lien : un lien"),
        ("Bravo 🎉🚀 !", "Bravo !"),
        ("Il fait 21 °C, soit 10 €.", "Il fait 21 °C, soit 10 €."),
        ("C'est fait.\n[AFFICHER]\ncode\n[/AFFICHER]\nVoilà.", "C'est fait. Voilà."),
        ("Avant\n```python\nprint(1)\n```\naprès", "Avant après"),
        ("Il faut le mode Claude Code. [MODE_CODE]", "Il faut le mode Claude Code."),
        ("| a | b |\n|---|---|", "a b --- ---"),
    ],
)
def test_clean_for_speech(text: str, spoken: str) -> None:
    assert clean_for_speech(text) == spoken


# -- sentence splitting -------------------------------------------------------------------

ANSWER = (
    "Bien sûr, Mr Chemmane ! Nous sommes en 2026. M. Dupont a appelé vers 14 h. "
    "Voici **trois** points :\n- le premier ;\n- le `second`\n\n"
    '[AFFICHER]\n```python\nprint("[x]")\n```\n[/AFFICHER]\n'
    "Je vous affiche le script. Plus d'infos sur https://example.com/page"
)
EXPECTED: list[Segment] = [
    Speak("Bien sûr, Mister Chemmane !"),
    Speak("Nous sommes en 2026."),
    Speak("M. Dupont a appelé vers 14 h."),
    Speak("Voici trois points :"),
    Speak("le premier ;"),
    Speak("le second"),
    Display('```python\nprint("[x]")\n```'),
    Speak("Je vous affiche le script."),
    Speak("Plus d'infos sur un lien"),
]


def split(chunks: list[str]) -> list[Segment]:
    stream = SpeechStream()
    segments: list[Segment] = []
    for chunk in chunks:
        segments += stream.feed(chunk)
    return segments + stream.flush()


@pytest.mark.parametrize("size", [1, 2, 3, 7, 50, len(ANSWER)])
def test_segments_do_not_depend_on_chunk_size(size: int) -> None:
    chunks = [ANSWER[i : i + size] for i in range(0, len(ANSWER), size)]
    assert split(chunks) == EXPECTED


def test_first_sentence_is_ready_before_the_answer_ends() -> None:
    stream = SpeechStream()
    assert stream.feed("Bonjour. Je") == [Speak("Bonjour.")]
    assert stream.feed(" réfléchis") == []
    assert stream.flush() == [Speak("Je réfléchis")]


def test_list_numbers_and_abbreviations_do_not_split() -> None:
    assert split(["1. Ouvrir le fichier. 2. Le lire, etc. Fin."]) == [
        Speak("1. Ouvrir le fichier."),
        Speak("2. Le lire, etc. Fin."),
    ]


def test_long_sentence_is_cut_at_a_comma() -> None:
    long_text = ", ".join(["un morceau de phrase assez long"] * 20) + "."
    segments = split([long_text])
    assert len(segments) > 1
    assert all(isinstance(s, Speak) and len(s.text) <= 260 for s in segments)


def test_unfinished_display_block_is_displayed_not_spoken() -> None:
    assert split(["Voici. [AFFICHER]ligne 1\nligne 2"]) == [
        Speak("Voici."),
        Display("ligne 1\nligne 2"),
    ]


# -- narrator ---------------------------------------------------------------------------


class FakeTTS:
    def __init__(self, fail_on: str | None = None) -> None:
        self.texts: list[str] = []
        self.fail_on = fail_on

    def synthesize(self, text: str) -> AudioClip:
        if text == self.fail_on:
            raise RuntimeError("boom")
        self.texts.append(text)
        return AudioClip(text.encode("utf-8"), 16000)


class FakeOutput:
    def __init__(self, seconds: float = 0.0) -> None:
        self.played: list[str] = []
        self.cut: list[str] = []
        self.seconds = seconds
        self.started = threading.Event()

    def play(self, clip: AudioClip, cancelled: Callable[[], bool]) -> None:
        self.started.set()
        deadline = time.monotonic() + self.seconds
        while time.monotonic() < deadline:
            if cancelled():
                self.cut.append(clip.pcm.decode("utf-8"))
                return
            time.sleep(0.005)
        self.played.append(clip.pcm.decode("utf-8"))


def test_sentences_are_spoken_in_order() -> None:
    output, states = FakeOutput(), []
    narrator = Narrator(FakeTTS(), output, on_speaking=states.append)
    for sentence in ("Un.", "Deux.", "**Trois**."):
        narrator.say(sentence)
    assert narrator.wait(timeout=2)
    assert output.played == ["Un.", "Deux.", "Trois."]
    assert states == [True, False]
    assert not narrator.speaking
    narrator.close()


def test_stop_cuts_the_current_sentence_and_drops_the_rest() -> None:
    output = FakeOutput(seconds=5)
    narrator = Narrator(FakeTTS(), output)
    for sentence in ("Une très longue phrase.", "Deuxième.", "Troisième."):
        narrator.say(sentence)
    assert output.started.wait(timeout=2)
    narrator.stop()
    assert narrator.wait(timeout=2)
    assert output.cut == ["Une très longue phrase."] and output.played == []
    narrator.say("Après.")
    output.seconds = 0
    assert narrator.wait(timeout=2)
    assert output.played == ["Après."]
    narrator.close()


def test_synthesis_error_skips_the_sentence() -> None:
    output = FakeOutput()
    narrator = Narrator(FakeTTS(fail_on="Casse."), output)
    for sentence in ("Avant.", "Casse.", "Après."):
        narrator.say(sentence)
    assert narrator.wait(timeout=2)
    assert output.played == ["Avant.", "Après."]
    narrator.close()


def test_nothing_to_say() -> None:
    narrator = Narrator(FakeTTS(), FakeOutput())
    narrator.say("[AFFICHER]rien à lire[/AFFICHER]")
    assert not narrator.speaking
    narrator.close()


# -- spoken chat ------------------------------------------------------------------------


class RecordingNarrator:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.stops = 0
        self.speaking = False

    def say(self, text: str) -> None:
        self.said.append(text)

    def stop(self) -> None:
        self.stops += 1

    def wait(self, timeout: float | None = None) -> bool:
        return True

    def close(self) -> None:
        pass


def spoken_chat(harness: Harness, narrator: RecordingNarrator) -> ChatSession:
    return ChatSession(
        harness.controller,
        write=lambda _: None,
        read=lambda _: "",
        narrator=narrator,  # type: ignore[arg-type]
    )


def test_answer_is_spoken_sentence_by_sentence_without_display_blocks() -> None:
    harness = Harness(
        [answer("Voici le fichier. ", "[AFFICHER]\nnotes.txt\n", "[/AFFICHER]", "C'est fait.")]
    )
    narrator = RecordingNarrator()
    spoken_chat(harness, narrator).handle("Crée le fichier")
    assert narrator.said == ["Voici le fichier.", "C'est fait."]


def test_local_answers_are_spoken_and_stop_silences() -> None:
    harness, narrator = Harness(), RecordingNarrator()
    chat = spoken_chat(harness, narrator)
    chat.handle("utilise Haiku")
    assert narrator.said == ["Je passe sur Haiku 4.5."]
    stops = narrator.stops
    chat.handle("stop")
    assert narrator.stops >= stops + 2  # new input + explicit stop
    assert narrator.said[-1] == "D'accord."


# -- real Piper voice (only when the model has been downloaded) -------------------------

VOICE_DIR = Path(__file__).parents[1] / "models" / "piper"


def test_softening_keeps_length_and_tames_high_frequencies() -> None:
    import numpy as np

    from friday.adapters.tts_piper import soften

    rate = 22050
    t = np.arange(rate) / rate
    low = 8000 * np.sin(2 * np.pi * 300 * t)
    high = 8000 * np.sin(2 * np.pi * 7000 * t)
    pcm = (low + high).astype(np.int16).tobytes()
    softened = np.frombuffer(soften(pcm, 1.0), dtype=np.int16).astype(np.float64)
    assert len(softened) == rate

    def energy(signal: np.ndarray, frequency: int) -> float:
        return float(abs(np.fft.rfft(signal)[frequency]))

    original = (low + high).astype(np.int16).astype(np.float64)
    assert energy(softened, 7000) < 0.2 * energy(original, 7000)
    assert energy(softened, 300) > 0.9 * energy(original, 300)


def test_voice_style_config() -> None:
    from friday.config import load_config

    tts = load_config(Path(__file__).parents[1] / "config" / "friday.example.yaml").tts
    assert tts.length_scale > 1 and 0 < tts.softness <= 1 and tts.volume < 1


VOICE = VOICE_DIR / "fr_FR-siwis-medium.onnx"


@pytest.mark.skipif(not VOICE.exists(), reason="Piper voice not downloaded")
def test_real_piper_voice_produces_audio() -> None:
    from friday.adapters.tts_piper import PiperTTS, VoiceStyle

    text = "Bonjour, je suis FRIDAY."
    normal = PiperTTS(VOICE_DIR, "fr_FR-siwis-medium").synthesize(text)
    slow = PiperTTS(VOICE_DIR, "fr_FR-siwis-medium", VoiceStyle(length_scale=1.3, softness=0.5))
    assert normal.sample_rate == 22050
    assert 0.8 < normal.duration < 4
    assert slow.synthesize(text).duration > normal.duration * 1.15


@pytest.mark.skipif(
    not (VOICE_DIR / "fr_FR-upmc-medium.onnx").exists(), reason="upmc voice not downloaded"
)
def test_speaker_is_chosen_by_name() -> None:
    from friday.adapters.tts_piper import PiperTTS, PiperUnavailableError, VoiceStyle

    PiperTTS(VOICE_DIR, "fr_FR-upmc-medium", VoiceStyle(speaker="jessica"))
    with pytest.raises(PiperUnavailableError, match="jessica, pierre"):
        PiperTTS(VOICE_DIR, "fr_FR-upmc-medium", VoiceStyle(speaker="paul"))
