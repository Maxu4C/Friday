"""Phase 6: permission requests from Claude Code, safety policy, spoken confirmations."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from friday.adapters.claude_stream import parse_event
from friday.chat import ChatSession
from friday.core.controller import ConfirmAction, Say
from friday.core.events import Mode, PermissionRequest
from friday.core.ports import Heard
from friday.core.safety import Risk, assess, is_final_confirmation
from tests.fakes import needs_permission
from tests.test_brain_claude_code import FakeProcess, init
from tests.test_brain_claude_code import Harness as BrainHarness
from tests.test_controller import Harness
from tests.test_wake import Running, ScriptedEars

FIXTURES = Path(__file__).parent / "fixtures" / "stream"
DELETE = {"command": 'Remove-Item -Path "bidon.txt" -Force'}

# -- safety policy ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "tool_input", "risk", "reason"),
    [
        ("PowerShell", DELETE, Risk.CONFIRM, ""),
        ("PowerShell", {"command": "Remove-Item C:\\Temp\\x -Recurse -Force"}, Risk.DANGEROUS,
         "suppression récursive"),
        ("Bash", {"command": "rm -rf build/"}, Risk.DANGEROUS, "suppression récursive"),
        ("Bash", {"command": "del /s /q *.log"}, Risk.DANGEROUS, "suppression récursive"),
        ("PowerShell", {"command": "Format-Volume -DriveLetter E"}, Risk.DANGEROUS,
         "formatage d'un disque"),
        ("Bash", {"command": "diskpart"}, Risk.DANGEROUS, "modification des disques"),
        ("Bash", {"command": "reg delete HKCU\\Software\\X /f"}, Risk.DANGEROUS,
         "modification du registre"),
        ("PowerShell", {"command": "Set-ItemProperty -Path HKLM:\\Software\\X -Name A -Value 1"},
         Risk.DANGEROUS, "modification du registre"),
        ("Bash", {"command": "shutdown /s /t 0"}, Risk.DANGEROUS, "extinction ou redémarrage"),
        ("PowerShell", {"command": "Restart-Computer"}, Risk.DANGEROUS,
         "extinction ou redémarrage"),
        ("Bash", {"command": "winget uninstall Spotify"}, Risk.DANGEROUS, "désinstallation"),
        ("PowerShell", {"command": "Send-MailMessage -To a@b.c -Subject x"}, Risk.DANGEROUS,
         "envoi d'un e-mail ou d'un message"),
        ("Write", {"file_path": "C:\\Windows\\System32\\drivers\\etc\\hosts"}, Risk.DANGEROUS,
         "dossier Windows"),
        ("Bash", {"command": "git push --force origin main"}, Risk.DANGEROUS,
         "perte de travail git"),
        ("Write", {"file_path": "C:\\Users\\me\\Documents\\notes.txt"}, Risk.CONFIRM, ""),
        ("Bash", {"command": "python script.py"}, Risk.CONFIRM, ""),
    ],
)  # fmt: skip
def test_risk_assessment(tool: str, tool_input: dict[str, Any], risk: Risk, reason: str) -> None:
    assessment = assess(tool, tool_input)
    assert assessment.risk is risk
    assert assessment.reason == reason


def test_spoken_summary_uses_claude_description_and_detail_keeps_the_command() -> None:
    assessment = assess("PowerShell", DELETE, "Supprime le fichier bidon.txt")
    assert assessment.spoken == (
        "Je dois exécuter une commande PowerShell : Supprime le fichier bidon.txt"
    )
    assert assessment.detail == 'PowerShell : Remove-Item -Path "bidon.txt" -Force'
    assert assess("Write", {"file_path": "C:\\a\\b\\notes.txt"}).spoken == (
        "Je dois écrire le fichier notes.txt"
    )


@pytest.mark.parametrize(
    ("answer", "final"),
    [("oui, confirme", True), ("Oui je confirme", True), ("confirmez", True), ("oui", False),
     ("oui oui", False), ("non", False)],
)  # fmt: skip
def test_final_confirmation_needs_the_word(answer: str, final: bool) -> None:
    assert is_final_confirmation(answer) is final


# -- stream-json and the brain -----------------------------------------------------------


def test_real_permission_request_is_parsed() -> None:
    lines = (FIXTURES / "permission_denied.jsonl").read_text(encoding="utf-8").splitlines()
    requests = [
        event
        for line in lines
        for event in parse_event(json.loads(line))
        if isinstance(event, PermissionRequest)
    ]
    assert len(requests) == 1
    assert requests[0].tool == "PowerShell"
    assert requests[0].input["command"] == 'Remove-Item -Path "bidon.txt" -Force'
    assert requests[0].description == "Supprime le fichier bidon.txt"


def asking(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    if payload["type"] == "user":
        return [
            init(),
            {"type": "control_request", "request_id": "r1", "request": {
                "subtype": "can_use_tool", "tool_name": "PowerShell", "input": DELETE,
                "description": "Supprime"}},
            {"type": "control_request", "request_id": "r2", "request": {"subtype": "mystery"}},
        ]  # fmt: skip
    if payload["type"] == "control_response" and payload["response"].get("subtype") == "success":
        return [{"type": "result", "subtype": "success", "is_error": False, "result": "ok",
                 "session_id": "sid-1"}]  # fmt: skip
    return []


def test_brain_forwards_the_request_and_sends_the_decision(tmp_path: Path) -> None:
    harness = BrainHarness(tmp_path, asking, mode=Mode.CLAUDE_CODE)
    harness.brain.send("Supprime bidon.txt")
    events = harness.brain.events()
    request = next(e for e in events if isinstance(e, PermissionRequest))
    harness.brain.respond_permission(request, allow=False, message="Non merci")
    list(events)
    process: FakeProcess = harness.processes[0]
    responses = [p for p in process.received if p["type"] == "control_response"]
    assert responses[0]["response"] == {
        "subtype": "error",
        "request_id": "r2",
        "error": "Non pris en charge par FRIDAY",
    }
    decision = responses[1]["response"]
    assert decision["request_id"] == "r1"
    assert decision["response"] == {"behavior": "deny", "message": "Non merci"}


def test_allowed_request_passes_the_input_back(tmp_path: Path) -> None:
    harness = BrainHarness(tmp_path, asking, mode=Mode.CLAUDE_CODE)
    harness.brain.send("Supprime bidon.txt")
    events = harness.brain.events()
    request = next(e for e in events if isinstance(e, PermissionRequest))
    harness.brain.respond_permission(request, allow=True)
    list(events)
    decision = harness.processes[0].received[-1]["response"]["response"]
    assert decision == {"behavior": "allow", "updatedInput": DELETE}


# -- controller ------------------------------------------------------------------------------


def run_with_answers(harness: Harness, request: str, *answers: str | None) -> list[object]:
    """Handle `request`, answering each ConfirmAction with the next answer (None: silence)."""
    replies = list(answers)
    outputs: list[object] = []
    for output in harness.controller.handle(request):
        outputs.append(output)
        if isinstance(output, ConfirmAction):
            answer = replies.pop(0)
            if answer is not None:
                harness.controller.answer_confirmation(answer)
    return outputs


def said(outputs: list[object]) -> list[str]:
    return [o.text for o in outputs if isinstance(o, Say)]


def questions(outputs: list[object]) -> list[ConfirmAction]:
    return [o for o in outputs if isinstance(o, ConfirmAction)]


def code_harness(*replies: Any) -> Harness:
    harness = Harness(list(replies))
    harness.run("passe en mode Claude Code")
    return harness


def test_simple_action_confirmed_with_oui() -> None:
    harness = code_harness(needs_permission("PowerShell", DELETE, "Supprime le fichier bidon.txt"))
    outputs = run_with_answers(harness, "Supprime bidon.txt", "oui")
    [question] = questions(outputs)
    assert question.question == (
        "Je dois exécuter une commande PowerShell : Supprime le fichier bidon.txt. Vous confirmez ?"
    )
    assert not question.dangerous
    assert harness.brain.permissions == [("PowerShell", True, "")]
    assert "Entendu." in said(outputs)


@pytest.mark.parametrize(
    ("answer", "message"),
    [("non", "D'accord, je refuse."), ("stop", "D'accord, je refuse."),
     ("peut-être demain", "Je n'ai pas compris, je refuse par sécurité."),
     (None, "Sans réponse de votre part, j'ai refusé.")],
)  # fmt: skip
def test_refusals(answer: str | None, message: str) -> None:
    harness = code_harness(needs_permission("PowerShell", DELETE))
    outputs = run_with_answers(harness, "Supprime bidon.txt", answer)
    assert harness.brain.permissions[0][1] is False
    assert message in said(outputs)


def test_late_answer_is_a_refusal() -> None:
    harness = code_harness(needs_permission("PowerShell", DELETE))
    outputs: list[object] = []
    for output in harness.controller.handle("Supprime bidon.txt"):
        outputs.append(output)
        if isinstance(output, ConfirmAction):
            harness.controller._now.now += timedelta(seconds=45)  # type: ignore[attr-defined]
            harness.controller.answer_confirmation("oui")
    assert harness.brain.permissions[0][1] is False
    assert "Sans réponse de votre part, j'ai refusé." in said(outputs)


RECURSIVE = {"command": "Remove-Item C:\\Temp\\projet -Recurse -Force"}


def test_dangerous_action_needs_two_steps() -> None:
    harness = code_harness(needs_permission("PowerShell", RECURSIVE, "Supprime le dossier projet"))
    outputs = run_with_answers(harness, "Supprime le dossier projet", "oui", "oui, confirme")
    first, second = questions(outputs)
    assert first.dangerous and first.step == 1
    assert "Attention, action à risque : suppression récursive." in first.question
    assert second.step == 2 and "oui, confirme" in second.question
    assert harness.brain.permissions[0][1] is True


@pytest.mark.parametrize("second_answer", ["oui", "non", None])
def test_dangerous_action_without_explicit_confirmation_is_refused(
    second_answer: str | None,
) -> None:
    harness = code_harness(needs_permission("PowerShell", RECURSIVE))
    outputs = run_with_answers(harness, "Supprime le dossier projet", "oui", second_answer)
    assert harness.brain.permissions[0][1] is False
    assert "Sans confirmation explicite, j'ai refusé." in said(outputs)


# -- consumers: text chat and voice assistant ---------------------------------------------


def test_chat_asks_and_reads_the_typed_answer() -> None:
    harness = code_harness(needs_permission("PowerShell", DELETE))
    output: list[str] = []
    typed = iter(["oui"])
    chat = ChatSession(harness.controller, write=output.append, read=lambda _: next(typed))
    chat.handle("Supprime bidon.txt")
    text = "".join(output)
    assert '[confirmation] PowerShell : Remove-Item -Path "bidon.txt" -Force' in text
    assert harness.brain.permissions[0][1] is True


def test_assistant_hears_the_spoken_answer() -> None:
    harness = code_harness(needs_permission("PowerShell", DELETE))
    ears = ScriptedEars(Heard("Supprime bidon.txt"), Heard("oui"))
    app = Running(harness, ears)
    app.assistant.wake()
    app.settle(lambda: harness.brain.permissions)
    app.stop()
    assert harness.brain.permissions[0][1] is True
    assert ears.calls == 2


class SlowEars(ScriptedEars):
    """Hears the request, then nobody speaks during the confirmation."""

    def listen(self) -> Heard:
        if self.calls == 1:
            self.calls += 1
            time.sleep(1.0)
            return Heard(None, "silence")
        return super().listen()


def test_assistant_accepts_a_typed_answer_while_listening() -> None:
    harness = code_harness(needs_permission("PowerShell", DELETE))
    app = Running(harness, SlowEars(Heard("Supprime bidon.txt")))
    app.assistant.wake()
    app.settle(lambda: app.assistant._confirmation is not None)
    app.assistant.submit_text("non")
    app.settle(lambda: harness.brain.permissions)
    app.stop()
    assert harness.brain.permissions[0][1] is False
