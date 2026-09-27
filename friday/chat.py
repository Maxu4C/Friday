"""`friday chat`: text conversation with FRIDAY (before the audio pipeline exists).

A thin renderer over the Controller: plain sentences behave exactly like spoken
ones ("utilise Opus", "liste mes sessions"...), slash commands are shortcuts.
"""

from __future__ import annotations

import signal
from collections.abc import Callable, Iterator
from types import FrameType

from friday.console import ConsoleDisplay
from friday.core.controller import ConfirmAction, Controller, Output
from friday.core.events import Mode
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
from friday.core.messages import HEARD_NOTHING, NOT_UNDERSTOOD
from friday.core.narrator import Narrator
from friday.core.ports import Ears
from friday.core.text import normalize
from friday.core.voice import SpeechRouter

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
        ears: Ears | None = None,
    ) -> None:
        self._controller = controller
        self._write = write
        self._read = read
        self._narrator = narrator
        self._ears = ears
        self._display = ConsoleDisplay(write)
        self._speech = SpeechRouter(narrator) if narrator is not None else None

    def run(self) -> int:
        self._render(self._controller.start())
        if self._ears is not None:
            self._write("Appuyez sur Entrée (sans rien taper) pour parler. /aide pour l'aide.\n")
        else:
            self._write("Tapez /aide pour l'aide.\n")
        prompt = "\nVous (Entrée = parler) > " if self._ears is not None else "\nVous > "
        try:
            while True:
                try:
                    # PowerShell may prefix piped input with a UTF-8 byte order mark.
                    line = self._read(prompt).lstrip("﻿").strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    if self._narrator is not None and self._narrator.speaking:
                        self._narrator.stop()  # Ctrl+C while FRIDAY speaks: silence only
                        self._write("\n")
                        continue
                    self._write("\n")
                    break
                if not line and self._ears is not None:
                    if not self.listen():
                        break
                elif line and not self.handle(line):
                    break
        finally:
            self._controller.close()
        self._display.say("À bientôt.")
        if self._narrator is not None:
            self._narrator.say("À bientôt.")
            self._narrator.wait(timeout=10)
            self._narrator.close()
        return 0

    def listen(self) -> bool:
        """Push-to-talk: record one spoken sentence and handle it; return False to quit."""
        assert self._ears is not None
        if self._narrator is not None:
            self._narrator.stop()  # never record FRIDAY's own voice
        self._display.write("  [écoute… parlez]\n")
        heard = self._ears.listen()
        if heard.text is None:
            message = HEARD_NOTHING if heard.reason == "silence" else NOT_UNDERSTOOD
            self._display.say(message)
            if self._narrator is not None:
                self._narrator.say(message)
            return True
        self._display.write(f"Vous (voix) > {heard.text}\n")
        return self.handle(heard.text)

    def _confirmation_answer(self, action: ConfirmAction) -> str:
        """Typed answer, or spoken one if the user just presses Enter."""
        expected = "oui, confirme / non" if action.step == 2 else "oui / non"
        voice = " (Entrée = répondre à voix haute)" if self._ears is not None else ""
        try:
            typed = self._read(f"\nVotre réponse [{expected}]{voice} > ").lstrip("﻿").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        if typed or self._ears is None:
            return typed
        if self._narrator is not None:
            self._narrator.wait(timeout=20)  # let FRIDAY finish the question first
        heard = self._ears.listen()
        if heard.text:
            self._display.write(f"Vous (voix) > {heard.text}\n")
        return heard.text or ""

    def handle(self, line: str) -> bool:
        """Process one input line; return False to quit."""
        if self._narrator is not None:
            self._narrator.stop()  # a new request cuts the previous answer
        if self._speech is not None:
            self._speech.reset()
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
            self._display.say(f"Commande inconnue : /{command}. Tapez /aide.")
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
                self._display.show(output)
                if self._speech is not None:
                    self._speech.handle(output)
                if isinstance(output, ConfirmAction):
                    self._controller.answer_confirmation(self._confirmation_answer(output))
        finally:
            signal.signal(signal.SIGINT, previous)
            self._display.end_stream()
