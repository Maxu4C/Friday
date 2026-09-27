"""Local detection of FRIDAY's own commands (model, mode, sessions, state, control).

Everything here runs without calling Claude, so these commands never use quota.
Matching works on normalized text (lowercase, no accents, no punctuation) while
names and follow-up requests are cut from the original text to keep accents.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from friday.core.events import Mode
from friday.core.text import normalize

# -- intents -------------------------------------------------------------------


@dataclass(frozen=True)
class SetModel:
    alias: str
    rest: str = ""  # request that followed the command ("utilise Opus pour ...")


@dataclass(frozen=True)
class AutoModel:
    pass


@dataclass(frozen=True)
class SetMode:
    mode: Mode
    rest: str = ""


@dataclass(frozen=True)
class NewSession:
    name: str | None = None


@dataclass(frozen=True)
class ResumeSession:
    name: str | None = None  # None: the previous session


@dataclass(frozen=True)
class ListSessions:
    pass


@dataclass(frozen=True)
class RenameSession:
    name: str


@dataclass(frozen=True)
class ForgetSession:
    name: str | None = None  # None: the current session


@dataclass(frozen=True)
class CurrentSession:
    pass


@dataclass(frozen=True)
class AskModel:
    pass


@dataclass(frozen=True)
class AskMode:
    pass


@dataclass(frozen=True)
class AskUsage:
    pass


@dataclass(frozen=True)
class Stop:
    pass


@dataclass(frozen=True)
class Cancel:
    pass


@dataclass(frozen=True)
class Repeat:
    pass


@dataclass(frozen=True)
class MuteMic:
    pass


@dataclass(frozen=True)
class UnmuteMic:
    pass


@dataclass(frozen=True)
class OpenClaudeWeb:
    pass


Command = (
    SetModel | AutoModel | SetMode | NewSession | ResumeSession | ListSessions | RenameSession
    | ForgetSession | CurrentSession | AskModel | AskMode | AskUsage | Stop | Cancel | Repeat
    | MuteMic | UnmuteMic | OpenClaudeWeb
)  # fmt: skip


@dataclass(frozen=True)
class Unclear:
    """Looks like a command without matching exactly: FRIDAY asks before acting."""

    guess: Command


Intent = Command | Unclear

# -- vocabulary ------------------------------------------------------------------


def _verbs(*stems: str) -> str:
    return "(?:" + "|".join(stems) + ")"


# Imperative (tu / vous) and infinitive forms: "passe", "passez", "passer".
_USE = _verbs(
    r"utilise[rsz]?", r"utilisez", r"prends", r"prenez", r"prendre", r"passe[rsz]?", r"passez",
    r"repasse[rsz]?", r"repassez", r"bascule[rsz]?", r"basculez", r"mets", r"mettez",
    r"mettre", r"choisis", r"choisissez", r"choisir", r"change[rsz]?", r"changez",
)  # fmt: skip
_SWITCH = _verbs(
    r"passe[rsz]?", r"passez", r"repasse[rsz]?", r"repassez", r"bascule[rsz]?", r"basculez",
    r"mets toi", r"mettez vous", r"se mettre", r"te mettre", r"vous mettre", r"reviens",
    r"revenez", r"revenir", r"retourne[rsz]?", r"retournez", r"active[rsz]?", r"activez",
    r"change[rsz]?", r"changez",
)  # fmt: skip
_CREATE = _verbs(
    r"cree[rsz]?", r"creez", r"ouvre[sz]?", r"ouvrez", r"ouvrir", r"demarre[rsz]?",
    r"demarrez", r"lance[rsz]?", r"lancez", r"commence[rsz]?", r"commencez", r"fais",
    r"faites", r"faire",
)  # fmt: skip
_RESUME = _verbs(
    r"reprends", r"reprenez", r"reprend", r"reprendre", r"retourne[rsz]? sur",
    r"retournez sur", r"reviens sur", r"revenez sur", r"revenir sur", r"reviens a",
    r"revenez a", r"rouvre[sz]?", r"rouvrez", r"rouvrir", r"ouvre[sz]?", r"ouvrez", r"ouvrir",
    r"va sur", r"allez sur", r"aller sur", r"bascule[rsz]? sur", r"basculez sur",
    r"passe[rsz]? sur", r"passez sur",
)  # fmt: skip
_SHOW = _verbs(
    r"liste[rsz]?", r"listez", r"montre[rsz]?", r"montrez", r"affiche[rsz]?", r"affichez",
    r"donne[sz]? moi", r"donnez moi", r"enumere[rsz]?", r"enumerez", r"dis moi",
    r"dites moi", r"rappelle moi", r"rappelez moi",
)  # fmt: skip
_RENAME = _verbs(r"renomme[rsz]?", r"renommez", r"appelle[rsz]?", r"appelez", r"nomme[rsz]?")
_FORGET = _verbs(
    r"oublie[rsz]?", r"oubliez", r"supprime[rsz]?", r"supprimez", r"efface[rsz]?", r"effacez",
    r"retire[rsz]?", r"retirez",
)  # fmt: skip

_MODE_NAMES: dict[str, Mode] = {
    "claude code": Mode.CLAUDE_CODE,
    "cloud code": Mode.CLAUDE_CODE,
    "clode code": Mode.CLAUDE_CODE,
    "clod code": Mode.CLAUDE_CODE,
    "claude codeur": Mode.CLAUDE_CODE,
    "code": Mode.CLAUDE_CODE,
    "action": Mode.CLAUDE_CODE,
    "actions": Mode.CLAUDE_CODE,
    "agent": Mode.CLAUDE_CODE,
    "claude classique": Mode.CLAUDE,
    "claude": Mode.CLAUDE,
    "cloud": Mode.CLAUDE,
    "clode": Mode.CLAUDE,
    "conversation": Mode.CLAUDE,
    "discussion": Mode.CLAUDE,
    "classique": Mode.CLAUDE,
}

_LEADING = (
    "hey friday", "he friday", "dis friday", "ok friday", "okay friday", "friday", "euh", "alors",
    "bon", "donc", "s il te plait", "s il vous plait", "stp", "svp",
    "est ce que tu peux", "est ce que vous pouvez", "est ce que tu pourrais",
    "est ce que vous pourriez", "tu peux", "peux tu", "vous pouvez", "pouvez vous",
    "tu pourrais", "pourrais tu", "vous pourriez", "pourriez vous", "je veux que tu",
    "je voudrais que tu", "j aimerais que tu", "je veux que vous", "je voudrais que vous",
    "j aimerais que vous",
)  # fmt: skip
_TRAILING = ("s il te plait", "s il vous plait", "stp", "svp", "merci", "friday", "please")
_REST_CONNECTORS = ("pour", "et", "puis", "ensuite", "afin de")


def _alternation(names: Iterable[str]) -> str:
    return "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))


# -- tokens: normalized words that remember where they come from -----------------


@dataclass(frozen=True)
class _Token:
    word: str
    start: int
    end: int


class _Text:
    def __init__(self, original: str) -> None:
        self.original = original
        tokens = (
            _Token(normalize(match.group()), match.start(), match.end())
            for match in re.finditer(r"[^\W_]+", original)
        )
        self.tokens = [t for t in tokens if t.word]
        self.end = len(original)  # where trailing politeness starts, once stripped

    def strip(self) -> None:
        """Drop politeness and wake words around the command."""
        changed = True
        while changed:
            changed = False
            for phrase in _LEADING:
                words = phrase.split()
                if len(self.tokens) > len(words) and self._words(0, len(words)) == words:
                    self.tokens = self.tokens[len(words) :]
                    changed = True
            for phrase in _TRAILING:
                words = phrase.split()
                size = len(self.tokens)
                if size > len(words) and self._words(size - len(words), size) == words:
                    self.end = self.tokens[-len(words)].start
                    self.tokens = self.tokens[: -len(words)]
                    changed = True

    def _words(self, start: int, end: int) -> list[str]:
        return [t.word for t in self.tokens[start:end]]

    @property
    def normalized(self) -> str:
        return " ".join(t.word for t in self.tokens)

    def original_span(self, start: int, end: int) -> str:
        """Original text covering the normalized characters [start, end).

        A span that reaches the last word keeps what follows it in the original
        (closing quotes, question mark), up to any stripped politeness.
        """
        position, selected = 0, []
        for token in self.tokens:
            token_end = position + len(token.word)
            if position >= start and token_end <= end:
                selected.append(token)
            position = token_end + 1
        if not selected:
            return ""
        stop = self.end if selected[-1] is self.tokens[-1] else selected[-1].end
        return self.original[selected[0].start : stop].strip(" \t\n,;")


# -- parser -------------------------------------------------------------------------


class IntentParser:
    def __init__(self, model_names: Mapping[str, Iterable[str]]) -> None:
        """`model_names`: model alias -> spoken names (e.g. "opus" -> ["opus", "opus 5.5"])."""
        self._models: dict[str, str] = {}
        for alias, names in model_names.items():
            for name in (alias, *names):
                spoken = normalize(name)
                if spoken:
                    self._models[spoken] = alias
        models = _alternation(self._models)
        modes = _alternation(_MODE_NAMES)
        rest = r"(?: (?P<rest>(?:" + "|".join(_REST_CONNECTORS) + r") .+))?"
        filler = r"(?: (?:sur|a|au|en|vers|pour|avec|de|du|le|la|l|modele|claude|version))*"
        self._model_patterns = [
            re.compile(rf"{_USE}{filler} (?P<model>{models}){rest}"),
            re.compile(rf"(?:avec|en|sur) (?:le )?(?:modele )?(?P<model>{models}){rest}"),
            re.compile(rf"(?:le )?modele (?P<model>{models})"),
        ]
        self._mode_patterns = [
            re.compile(
                rf"{_SWITCH}(?: (?:en|sur|au|dans|le|la|mode))* (?P<mode>{modes})(?: mode)?{rest}"
            ),
            re.compile(rf"(?:en )?mode (?P<mode>{modes}){rest}"),
        ]
        self._models_only = re.compile(rf"(?:et )?(?:le )?(?:modele )?(?P<model>{models})")

    def parse(self, text: str) -> Intent | None:
        parsed = _Text(text)
        parsed.strip()
        normalized = parsed.normalized
        if not normalized:
            return None
        for family in (
            self._control,
            self._state,
            self._sessions,
            self._auto_model,
            self._mode,
            self._model,
        ):
            intent = family(normalized, parsed)
            if intent is not None:
                return intent
        return self._unclear(normalized)

    # -- families ---------------------------------------------------------------

    def _control(self, s: str, _: _Text) -> Command | None:
        if re.fullmatch(
            r"stop(?: friday)?|stoppe[rz]?|arrete[rz]?(?: toi| vous| tout)?|tais toi|"
            r"taisez vous|silence|chut|ca suffit",
            s,
        ):
            return Stop()
        if re.fullmatch(r"annule[rz]?(?: ca| tout)?|laisse[rz]? tomber|oublie[rz]? ca", s):
            return Cancel()
        if re.fullmatch(
            r"repete[rz]?(?: ca)?|repeter|redis(?: le| ca)?|redites(?: le)?|redire|"
            r"(?:j ai pas|je n ai pas) (?:compris|entendu)|pardon|hein|quoi",
            s,
        ):
            return Repeat()
        if re.fullmatch(
            r"(?:coupe[rsz]?|coupez|desactive[rsz]?|desactivez|eteins|eteignez|mute[rz]?) "
            r"(?:le |ton |votre |ce )?micro(?:phone)?",
            s,
        ):
            return MuteMic()
        if re.fullmatch(
            r"(?:reactive[rsz]?|reactivez|active[rsz]?|activez|rallume[rsz]?|rallumez|"
            r"allume[rsz]?|allumez|remets|remettez|ouvre[sz]?|ouvrez) "
            r"(?:le |ton |votre |ce )?micro(?:phone)?",
            s,
        ):
            return UnmuteMic()
        if re.fullmatch(
            r"(?:ouvre[rsz]?|ouvrez|lance[rsz]?|lancez|affiche[rsz]?|affichez) "
            r"(?:le site (?:de )?|l appli (?:de )?)?claude(?: ai)?"
            r"(?: (?:dans|sur) (?:le |mon |un |votre )?navigateur)?",
            s,
        ):
            return OpenClaudeWeb()
        return None

    def _state(self, s: str, _: _Text) -> Command | None:
        if re.fullmatch(
            r"(?:(?:tu utilises|vous utilisez|on utilise|tu tournes sur|vous tournez sur|"
            r"c est|on est sur|tu es sur|vous etes sur) )?(?:sur )?quel(?:le)? modele"
            r"(?: (?:tu utilises|utilises tu|vous utilisez|utilisez vous|est actif|"
            r"est utilise|on utilise|actuel|as tu|avez vous|es tu|etes vous))?|"
            r"(?:c est quoi |quel est )?le modele (?:actuel|actif|utilise)",
            s,
        ):
            return AskModel()
        if re.fullmatch(
            r"(?:(?:on est|nous sommes|tu es|vous etes|c est) )?(?:dans |en )?quel mode"
            r"(?: (?:on est|sommes nous|es tu|etes vous|est actif|actuel))?|"
            r"(?:c est quoi |quel est )?le mode (?:actuel|actif)",
            s,
        ):
            return AskMode()
        if re.search(r"\bcombien (?:de |d )(?:requetes|demandes|messages|questions)\b", s) and (
            len(s.split()) <= 10
        ):
            return AskUsage()
        return None

    def _sessions(self, s: str, parsed: _Text) -> Command | None:
        name = r"(?:(?:du|de|de la|des|pour|sur) )?(?:(?:le|la|les|l|mon|ma|mes) )?(?:projet )?"
        name += r"(?P<name>.+)"
        previous = r"(?:precedente|d avant|derniere|d hier|anterieure)"

        match = re.fullmatch(
            rf"(?:{_CREATE} )?(?:une )?nouvelle session"
            rf"(?: (?:pour|sur|appelee|nommee|intitulee|qui s appelle|du|de)"
            rf"(?: (?:le|la|les|l|mon|ma))?(?: projet)? (?P<name>.+))?",
            s,
        )
        if match:
            return NewSession(_name(parsed, match))
        if re.fullmatch(rf"(?:{_RESUME} )?(?:la |a la )?session {previous}", s):
            return ResumeSession(None)
        if re.fullmatch(rf"(?:{_RESUME} )?(?:la |a la )?{previous} session", s):
            return ResumeSession(None)
        match = re.fullmatch(rf"{_RESUME} (?:la |a la )?session {name}", s)
        if match:
            return ResumeSession(_name(parsed, match))
        if re.fullmatch(
            rf"(?:{_SHOW}(?: moi| nous)? )?(?:la liste (?:de |des )?)?"
            r"(?:mes|les|toutes les|nos) sessions|"
            r"liste des sessions|"
            r"quelles (?:sont les |sont mes )?sessions(?: (?:j ai|ai je|est ce que j ai|"
            r"avons nous|existent|il y a|as tu|avez vous))?|"
            r"(?:j ai|ai je|on a) quelles sessions|combien (?:de sessions|j ai de sessions)",
            s,
        ):
            return ListSessions()
        match = re.fullmatch(
            rf"{_RENAME} (?:cette|la|notre) session(?: actuelle)? (?:en |comme |par )?{name}", s
        )
        if match:
            return RenameSession(_name(parsed, match) or "")
        if re.fullmatch(rf"{_FORGET} (?:cette|la) session(?: actuelle| courante| en cours)?", s):
            return ForgetSession(None)
        match = re.fullmatch(rf"{_FORGET} (?:la )?session {name}", s)
        if match:
            return ForgetSession(_name(parsed, match))
        if re.fullmatch(
            r"(?:(?:on est|nous sommes|tu es|vous etes|c est) )?(?:sur |dans )?quelle session"
            r"(?: (?:on est|sommes nous|est active|est ce|on utilise|j utilise|es tu|"
            r"etes vous|actuelle))?|"
            r"(?:c est quoi |quelle est )?la session (?:actuelle|courante|en cours)",
            s,
        ):
            return CurrentSession()
        return None

    def _auto_model(self, s: str, _: _Text) -> Command | None:
        words = s.split()
        automatic = {"automatique", "auto", "automatiquement"} & set(words)
        if automatic and "modele" in words and len(words) <= 8:
            return AutoModel()
        if re.fullmatch(r"(?:choisis|choisissez|choisir) (?:le modele )?(?:toi|vous) meme", s):
            return AutoModel()
        return None

    def _mode(self, s: str, parsed: _Text) -> Command | None:
        for pattern in self._mode_patterns:
            match = pattern.fullmatch(s)
            if match:
                return SetMode(_MODE_NAMES[match.group("mode")], _rest(parsed, match))
        return None

    def _model(self, s: str, parsed: _Text) -> Command | None:
        for pattern in self._model_patterns:
            match = pattern.fullmatch(s)
            if match:
                return SetModel(self._models[match.group("model")], _rest(parsed, match))
        return None

    def _unclear(self, s: str) -> Unclear | None:
        match = self._models_only.fullmatch(s)
        if match:
            return Unclear(SetModel(self._models[match.group("model")]))
        words = s.split()
        if 1 < len(words) <= 3 and words[0] == "session":
            return Unclear(ResumeSession(" ".join(words[1:])))
        if len(words) <= 4 and words[-1] in _MODE_NAMES and "mode" in words:
            return Unclear(SetMode(_MODE_NAMES[words[-1]]))
        return None


def _name(parsed: _Text, match: re.Match[str]) -> str | None:
    if match.groupdict().get("name") is None:
        return None
    return parsed.original_span(*match.span("name")).rstrip(" .?!…»\"'").lstrip("«\"' ") or None


def _rest(parsed: _Text, match: re.Match[str]) -> str:
    if match.groupdict().get("rest") is None:
        return ""
    start, end = match.span("rest")
    connector = next(
        c for c in sorted(_REST_CONNECTORS, key=len, reverse=True) if match["rest"].startswith(c)
    )
    return parsed.original_span(start + len(connector) + 1, end)
