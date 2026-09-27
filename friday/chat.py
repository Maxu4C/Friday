"""`friday chat`: text conversation with FRIDAY (before the audio pipeline exists).

A thin renderer over the Controller: plain sentences behave exactly like spoken
ones ("utilise Opus", "liste mes sessions"...), slash commands are shortcuts.
"""

from __future__ import annotations

import signal
from collections.abc import Callable, Iterator
from types import FrameType

from friday.core.controller import (
    Ask,
    Controller,
    Output,
    Say,
    ShowSessions,
    StateChanged,
    StopSpeaking,
)
from friday.core.events import Mode, TextDelta, ToolResult, ToolUse, TurnCompleted
from friday.core.intents import (
    AskMode,
    AskModel,
    AskUsage,
    AutoModel,
    Command,
    CurrentSession,
    ForgetSession,
    ListSessions,
    NewSession,
    RenameSession,
    ResumeSession,
    SetMode,
)
from friday.core.messages import MODE_LABELS
from friday.core.narrator import Narrator
from friday.core.speech import Segment, Speak, SpeechStream
from friday.core.text import normalize

HELP = """Parlez normalement : « utilise Opus », « passe en mode Claude Code »,
« nouvelle session pour le projet boucherie », « liste mes sessions »,
« reprends la session boucherie », « quel modèle tu utilises ? »…

Raccourcis :
  /mode [claude|code]             mode actuel, ou changement de mode
  /model [haiku|opus|fable|auto]  modèle actuel, ou changement de modèle
  /sessions                       liste des sessions
  /session                        session actuelle
  /session nouvelle [nom]         nouvelle session
  /session reprendre <nom>        reprendre une session
  /session renommer <nom>         renommer la session actuelle
  /session oublier [nom]          oublier une session (demande confirmation)
  /etat                           session, mode, modèle et requêtes du jour
  /aide                           cette aide
  /quitter                        quitter
Ctrl+C pendant une réponse l'interrompt."""

_MODE_WORDS = {
    "claude": Mode.CLAUDE,
    "conversation": Mode.CLAUDE,
    "code": Mode.CLAUDE_CODE,
    "claude code": Mode.CLAUDE_CODE,
    "action": Mode.CLAUDE_CODE,
}


class ChatSession:
    def __init__(
        self,
        controller: Controller,
        *,
        write: Callable[[str], None],
        read: Callable[[str], str],
        narrator: Narrator | None = None,
    ) -> None:
        self._controller = controller
        self._write = write
        self._read = read
        self._narrator = narrator
        self._speech = SpeechStream()
        self._streaming = False

    def run(self) -> int:
        self._render(self._controller.start())
        self._write("Tapez /aide pour l'aide.\n")
        try:
            while True:
                try:
                    # PowerShell may prefix piped input with a UTF-8 byte order mark.
                    line = self._read("\nVous > ").lstrip("﻿").strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    if self._narrator is not None and self._narrator.speaking:
                        self._narrator.stop()  # Ctrl+C while FRIDAY speaks: silence only
                        self._write("\n")
                        continue
                    self._write("\n")
                    break
                if line and not self.handle(line):
                    break
        finally:
            self._controller.close()
        self._say("À bientôt.")
        if self._narrator is not None:
            self._narrator.say("À bientôt.")
            self._narrator.wait(timeout=10)
            self._narrator.close()
        return 0

    def handle(self, line: str) -> bool:
        """Process one input line; return False to quit."""
        if self._narrator is not None:
            self._narrator.stop()  # a new request cuts the previous answer
        self._speech = SpeechStream()
        if not line.startswith("/"):
            self._render(self._controller.handle(line))
            return True
        command, _, argument = line[1:].partition(" ")
        command, argument = normalize(command), argument.strip()
        if command in {"quitter", "quit", "exit", "q"}:
            return False
        if command in {"aide", "help"}:
            self._write(HELP + "\n")
            return True
        outputs = self._shortcut(command, argument)
        if outputs is None:
            self._say(f"Commande inconnue : /{command}. Tapez /aide.")
        else:
            self._render(outputs)
        return True

    # -- shortcuts ---------------------------------------------------------------------

    def _shortcut(self, command: str, argument: str) -> Iterator[Output] | None:
        controller = self._controller
        if command == "mode":
            if not argument:
                return controller.execute(AskMode())
            mode = _MODE_WORDS.get(normalize(argument))
            return controller.execute(SetMode(mode)) if mode else None
        if command in {"model", "modele"}:
            if not argument:
                return controller.execute(AskModel())
            if normalize(argument) in {"auto", "automatique"}:
                return controller.execute(AutoModel())
            return controller.handle(f"utilise {argument}")
        if command == "sessions":
            return controller.execute(ListSessions())
        if command == "session":
            return self._session_shortcut(argument)
        if command == "etat":
            return self._chain(controller.execute(CurrentSession()), controller.execute(AskUsage()))
        return None

    def _session_shortcut(self, argument: str) -> Iterator[Output] | None:
        verb, _, name = argument.partition(" ")
        verb, name = normalize(verb), name.strip()
        commands: dict[str, Command] = {
            "": CurrentSession(),
            "nouvelle": NewSession(name or None),
            "reprendre": ResumeSession(name or None),
            "renommer": RenameSession(name),
            "oublier": ForgetSession(name or None),
        }
        command = commands.get(verb)
        if command is None or (verb == "renommer" and not name):
            return None
        return self._controller.execute(command)

    @staticmethod
    def _chain(*outputs: Iterator[Output]) -> Iterator[Output]:
        for output in outputs:
            yield from output

    # -- rendering --------------------------------------------------------------------------

    def _render(self, outputs: Iterator[Output]) -> None:
        previous = signal.getsignal(signal.SIGINT)

        def interrupt(_signum: int, _frame: FrameType | None) -> None:
            self._controller.interrupt()
            if self._narrator is not None:
                self._narrator.stop()

        signal.signal(signal.SIGINT, interrupt)
        try:
            for output in outputs:
                self._show(output)
        finally:
            signal.signal(signal.SIGINT, previous)
            self._end_stream()

    def _show(self, output: Output) -> None:
        if isinstance(output, TextDelta):
            if not self._streaming:
                self._write("\nFRIDAY > ")
                self._streaming = True
            self._write(output.text)
            self._speak(self._speech.feed(output.text))
        elif isinstance(output, StopSpeaking):
            if self._narrator is not None:
                self._narrator.stop()
            self._speech = SpeechStream()
        elif isinstance(output, ToolUse):
            self._end_stream()
            self._write(f"  [outil] {output.name} {_brief(output.input)}\n")
        elif isinstance(output, ToolResult) and output.is_error:
            self._write(f"  [échec] {output.summary}\n")
        elif isinstance(output, TurnCompleted):
            self._end_stream()
            self._speak(self._speech.flush())
            if output.permission_denials:
                self._write(f"  [refusé] {', '.join(output.permission_denials)}\n")
        elif isinstance(output, Say | Ask):
            self._say(output.text)
            if self._narrator is not None:
                self._narrator.say(output.text)
        elif isinstance(output, ShowSessions):
            self._end_stream()
            for record in output.sessions:
                mark = "*" if record.key == output.current_key else " "
                lock = record.model_lock or "auto"
                used = record.last_used_at.strftime("%d/%m %H:%M")
                line = f"  {mark} {record.name} · {MODE_LABELS[record.mode]} · {lock} · {used}"
                self._write(line + (f" · {record.summary}" if record.summary else "") + "\n")
        elif isinstance(output, StateChanged):
            pass  # the graphical interface uses it; the text chat announces changes with Say

    def _speak(self, segments: list[Segment]) -> None:
        if self._narrator is None:
            return
        for segment in segments:
            if isinstance(segment, Speak):
                self._narrator.say(segment.text)

    def _end_stream(self) -> None:
        if self._streaming:
            self._write("\n")
            self._streaming = False

    def _say(self, text: str) -> None:
        self._end_stream()
        self._write(f"\nFRIDAY > {text}\n")


def _brief(data: dict[str, object], limit: int = 80) -> str:
    for key in ("command", "file_path", "pattern", "path", "url"):
        if key in data:
            text = str(data[key])
            return text if len(text) <= limit else text[: limit - 1] + "…"
    return ""
