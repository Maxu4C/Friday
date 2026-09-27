"""Phase 5: the assistant state machine, the wake word listener (anti-echo, barge-in),
the real "hey Jarvis" model, the hotkey syntax and the shared microphone."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from friday.adapters.audio_io import record_utterance
from friday.adapters.hotkey import to_pynput
from friday.adapters.microphone import Microphone
from friday.core.assistant import Assistant, AssistantEvent, State, StateEvent, UserSaid
from friday.core.controller import Ask, Say
from friday.core.endpointing import EndpointSettings
from friday.core.events import Mode
from friday.core.ports import Heard
from friday.core.wake import WakeListener
from tests.fakes import answer
from tests.test_controller import Harness

# -- assistant ------------------------------------------------------------------------


class ScriptedEars:
    def __init__(self, *heard: Heard) -> None:
        self.heard = list(heard)
        self.calls = 0

    def listen(self) -> Heard:
        self.calls += 1
        return self.heard.pop(0) if self.heard else Heard(None, "silence")


class FakeNarrator:
    """Speaks instantly unless `hold` is set; notifies listeners like the real one."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.stops = 0
        self.speaking = False
        self.hold = False
        self._listeners: list[Callable[[bool], None]] = []

    def add_listener(self, listener: Callable[[bool], None]) -> None:
        self._listeners.append(listener)

    def say(self, text: str) -> None:
        self.said.append(text)
        self._set(True)
        if not self.hold:
            self._set(False)

    def finish(self) -> None:
        self._set(False)

    def stop(self) -> None:
        self.stops += 1
        self._set(False)

    def wait(self, timeout: float | None = None) -> bool:
        return True

    def _set(self, speaking: bool) -> None:
        if speaking != self.speaking:
            self.speaking = speaking
            for listener in self._listeners:
                listener(speaking)


class Running:
    """An Assistant running in a background thread, recording what it displays."""

    def __init__(
        self, harness: Harness, ears: ScriptedEars, narrator: FakeNarrator | None = None
    ) -> None:
        self.events: list[AssistantEvent] = []
        self.assistant = Assistant(
            harness.controller,
            display=self.events.append,
            ears=ears,
            narrator=narrator,  # type: ignore[arg-type]
        )
        self.thread = threading.Thread(target=self.assistant.run, daemon=True)
        self.thread.start()

    def settle(self, condition: Callable[[], object], timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, f"timeout; events: {self.events}"
            time.sleep(0.01)

    def stop(self) -> None:
        self.assistant.shutdown()
        self.thread.join(timeout=3)

    def states(self) -> list[State]:
        return [e.state for e in self.events if isinstance(e, StateEvent)]

    def said(self) -> list[str]:
        return [e.text for e in self.events if isinstance(e, Say | Ask)]


def test_wake_listen_answer_back_to_idle() -> None:
    harness = Harness([answer("Il est midi.")])
    ears = ScriptedEars(Heard("Quelle heure est-il ?"))
    app = Running(harness, ears)
    app.settle(lambda: app.assistant.state is State.IDLE and app.states())
    app.events.clear()
    app.assistant.wake()
    app.settle(lambda: len(harness.brain.sent) == 1 and app.assistant.state is State.IDLE)
    app.stop()
    assert UserSaid("Quelle heure est-il ?", spoken=True) in app.events
    assert app.states() == [State.LISTENING, State.THINKING, State.IDLE]


def test_typed_text_and_silence() -> None:
    harness = Harness()
    app = Running(harness, ScriptedEars(Heard(None, "silence")))
    app.assistant.submit_text("utilise Haiku")
    app.assistant.wake("raccourci")
    app.settle(lambda: "Je n'ai rien entendu." in app.said())
    app.stop()
    assert UserSaid("utilise Haiku", spoken=False) in app.events
    assert "Je passe sur Haiku 4.5." in app.said()
    assert harness.brain.sent == []


def test_spoken_question_is_answered_without_the_wake_word() -> None:
    harness = Harness([answer("Il faut le mode Claude Code. [MODE_CODE]"), answer("Fait.")])
    ears = ScriptedEars(Heard("Crée un fichier notes.txt"), Heard("oui"))
    app = Running(harness, ears)
    app.assistant.wake()
    app.settle(lambda: len(harness.brain.sent) == 2)
    app.stop()
    assert ears.calls == 2  # the "oui" was heard without saying the wake word again
    assert harness.controller.current.mode is Mode.CLAUDE_CODE


def test_speaking_state_follows_the_voice() -> None:
    harness, narrator = Harness([answer("Une longue réponse.")]), FakeNarrator()
    narrator.hold = True
    app = Running(harness, ScriptedEars(), narrator)
    app.settle(lambda: narrator.said)  # greeting spoken
    narrator.finish()
    app.settle(lambda: app.assistant.state is State.IDLE)
    app.events.clear()
    app.assistant.submit_text("Raconte-moi une histoire")
    app.settle(lambda: app.assistant.state is State.SPEAKING and harness.brain.sent)
    narrator.finish()
    app.settle(lambda: app.assistant.state is State.IDLE)
    app.stop()
    assert app.states()[-2:] == [State.SPEAKING, State.IDLE]
    assert narrator.said[-1] == "Une longue réponse."


def test_wake_interrupts_speech_and_stop_silences() -> None:
    harness, narrator = Harness(), FakeNarrator()
    narrator.hold = True
    app = Running(harness, ScriptedEars(Heard("stop")), narrator)
    app.settle(lambda: app.assistant.state is State.SPEAKING)  # speaking the greeting
    stops = narrator.stops
    app.assistant.wake()
    app.settle(lambda: "D'accord." in narrator.said)
    app.stop()
    assert narrator.stops > stops
    assert "interrupt" in harness.brain.calls


def test_accepts_wake() -> None:
    harness = Harness()
    assistant = Assistant(harness.controller, display=lambda _: None)
    assert assistant.accepts_wake(barge_in=False)
    assistant._state = State.SPEAKING
    assert assistant.accepts_wake(barge_in=True) and not assistant.accepts_wake(barge_in=False)
    assistant._state = State.LISTENING
    assert not assistant.accepts_wake(barge_in=True)
    assistant._state = State.IDLE
    harness.controller.mic_muted = True
    assert not assistant.accepts_wake(barge_in=True)


# -- wake word listener --------------------------------------------------------------------


class FakeDetector:
    def __init__(self, hits: set[int]) -> None:
        self.hits = hits
        self.resets = 0

    def push(self, frame: bytes) -> bool:
        return int.from_bytes(frame, "little") in self.hits

    def reset(self) -> None:
        self.resets += 1


class FakeTarget:
    def __init__(self, states: list[State]) -> None:
        self.states = states
        self.index = 0
        self.woken: list[int] = []

    @property
    def state(self) -> State:
        return self.states[min(self.index, len(self.states) - 1)]

    def accepts_wake(self, barge_in: bool) -> bool:
        return self.state is State.IDLE or (barge_in and self.state is State.SPEAKING)

    def wake(self, source: str = "") -> None:
        self.woken.append(self.index)


def listen(target: FakeTarget, hits: set[int], *, barge_in: bool = True) -> FakeDetector:
    detector = FakeDetector(hits)
    clock = {"t": 0.0}

    def frames() -> Iterator[bytes]:
        for i in range(len(target.states)):
            target.index = i
            clock["t"] = i * 0.1
            yield i.to_bytes(4, "little")

    WakeListener(
        frames(),
        detector,
        target,
        barge_in=barge_in,
        echo_tail=0.35,
        clock=lambda: clock["t"],
    ).run()
    return detector


def test_wake_word_wakes_when_idle_but_not_while_listening() -> None:
    target = FakeTarget([State.IDLE] * 3 + [State.LISTENING] * 3 + [State.IDLE] * 3)
    listen(target, hits={1, 4, 7})
    assert target.woken == [1, 7]


def test_barge_in_while_speaking_can_be_disabled() -> None:
    target = FakeTarget([State.SPEAKING] * 5)
    listen(target, hits={2})
    assert target.woken == [2]
    target = FakeTarget([State.SPEAKING] * 5)
    listen(target, hits={2}, barge_in=False)
    assert target.woken == []


def test_echo_tail_after_speaking() -> None:
    # FRIDAY stops speaking at frame 3: frames 3 to 6 (0.35 s) are ignored.
    target = FakeTarget([State.SPEAKING] * 3 + [State.IDLE] * 8)
    detector = listen(target, hits={4, 8}, barge_in=False)
    assert target.woken == [8]
    assert detector.resets >= 1  # stale audio is dropped before listening again


# -- real "hey Jarvis" model (only when downloaded) -----------------------------------

ROOT = Path(__file__).parents[1]
WAKE_DIR = ROOT / "models" / "openwakeword"
PIPER = ROOT / "models" / "piper" / "fr_FR-siwis-medium.onnx"


@pytest.mark.skipif(
    not ((WAKE_DIR / "hey_jarvis_v0.1.onnx").exists() and PIPER.exists()),
    reason="wake word or Piper models not downloaded",
)
def test_real_hey_jarvis_model() -> None:
    from friday.adapters.wakeword_openwakeword import OpenWakeWordDetector
    from tests.test_listening import frames_of, spoken

    detector = OpenWakeWordDetector(WAKE_DIR, "hey_jarvis", threshold=0.5)

    def heard(text: str) -> bool:
        detector.reset()
        audio = np.concatenate([np.zeros(8000), spoken(text), np.zeros(16000)])
        return any([detector.push(frame) for frame in frames_of(audio)])

    assert heard("Hé, Jarvisse.")
    assert not heard("Bonjour, quelle heure est-il ?")
    assert not heard("Je suis FRIDAY, votre assistante.")


# -- hotkey, recorder, shared microphone ------------------------------------------------


@pytest.mark.parametrize(
    ("combo", "expected"),
    [("ctrl+alt+f", "<ctrl>+<alt>+f"), ("Ctrl + Shift + F12", "<ctrl>+<shift>+<f12>"),
     ("win+j", "<cmd>+j")],
)  # fmt: skip
def test_hotkey_syntax(combo: str, expected: str) -> None:
    assert to_pynput(combo) == expected


class ConstantVAD:
    def __init__(self, probabilities: list[float]) -> None:
        self.probabilities = probabilities

    def reset(self) -> None:
        pass

    def probability(self, frame: bytes) -> float:
        return self.probabilities.pop(0) if self.probabilities else 0.0


def test_record_utterance_from_a_frame_source() -> None:
    frames = [b"\x01\x00" * 512] * 200
    settings = EndpointSettings(end_silence=0.3)
    vad = ConstantVAD([0.0] * 5 + [0.9] * 30)
    clip = record_utterance(lambda _: frames.pop(0) if frames else None, vad, settings)
    assert clip is not None and clip.sample_rate == 16000
    assert 0.9 < clip.duration < 1.5
    assert record_utterance(lambda _: None, ConstantVAD([]), settings) is None


def test_shared_microphone_fans_out_frames() -> None:
    microphone = Microphone(None)  # never started: frames are delivered by hand
    first, second = microphone.subscribe(), microphone.subscribe()
    microphone.deliver(b"frame")
    assert first.get(0.1) == b"frame" and second.get(0.1) == b"frame"
    second.close()
    microphone.deliver(b"next")
    assert first.get(0.1) == b"next"
    assert second.get(0.1) is None
