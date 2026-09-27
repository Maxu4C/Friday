"""Speak what the controller produces: Claude's answer sentence by sentence, FRIDAY's own
sentences, and silence as soon as the user asks for it."""

from __future__ import annotations

from friday.core.controller import Ask, ConfirmAction, Output, Say, StopSpeaking
from friday.core.events import TextDelta, TurnCompleted
from friday.core.narrator import Narrator
from friday.core.speech import Display, Segment, Speak, SpeechStream


class SpeechRouter:
    def __init__(self, narrator: Narrator) -> None:
        self._narrator = narrator
        self._stream = SpeechStream()

    def reset(self) -> None:
        """Forget a half-received answer (new request, interruption)."""
        self._stream = SpeechStream()

    def handle(self, output: Output) -> list[Display]:
        """Speak `output` if it is meant to be heard; return the blocks meant for the screen."""
        if isinstance(output, TextDelta):
            return self._speak(self._stream.feed(output.text))
        if isinstance(output, TurnCompleted):
            return self._speak(self._stream.flush())
        if isinstance(output, Say | Ask):
            self._narrator.say(output.text)
        elif isinstance(output, ConfirmAction):
            self._narrator.say(output.question)
        elif isinstance(output, StopSpeaking):
            self._narrator.stop()
            self.reset()
        return []

    def _speak(self, segments: list[Segment]) -> list[Display]:
        shown: list[Display] = []
        for segment in segments:
            if isinstance(segment, Speak):
                self._narrator.say(segment.text)
            else:
                shown.append(segment)
        return shown
