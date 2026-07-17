"""Persistent read-only local Codex conversation boundary.

The adapter intentionally registers no Ariad tools. It exposes only curated
assistant-text and lifecycle events while keeping raw app-server messages,
reasoning, account metadata, and host details inside the process boundary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Event, Lock, Thread
from typing import Any, Mapping, TextIO

from .local_codex import MAX_CODEX_LINE_BYTES, _codex_environment


CONVERSATION_CONTRACT_VERSION = "1.0.0"
MAX_CONVERSATION_PROMPT_BYTES = 16 * 1024
MAX_CONVERSATION_EVENTS = 1_000
MAX_EVENT_TEXT_CHARS = 4_096
MAX_TURN_SECONDS = 120.0


class ConversationEventType(str, Enum):
    TURN_STARTED = "turn_started"
    ASSISTANT_TEXT_DELTA = "assistant_text_delta"
    TURN_COMPLETED = "turn_completed"
    TURN_FAILED = "turn_failed"
    TURN_CANCELLED = "turn_cancelled"


@dataclass(frozen=True)
class ConversationEvent:
    sequence: int
    event_type: ConversationEventType
    turn_id: str
    text: str = ""
    contract_version: str = CONVERSATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != CONVERSATION_CONTRACT_VERSION:
            raise ValueError("unsupported conversation event contract")
        if self.sequence < 1:
            raise ValueError("conversation event sequence must be positive")
        object.__setattr__(self, "event_type", ConversationEventType(self.event_type))
        if not self.turn_id or len(self.turn_id) > 160:
            raise ValueError("conversation turn_id is invalid")
        if len(self.text) > MAX_EVENT_TEXT_CHARS:
            raise ValueError("conversation event text is too long")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "turn_id": self.turn_id,
            "text": self.text,
        }


def curate_codex_notification(message: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """Reduce one app-server notification to event type, turn id, and text."""

    method = message.get("method")
    params = message.get("params")
    if not isinstance(method, str) or not isinstance(params, Mapping):
        return None
    turn_id = params.get("turnId")
    if method == "item/agentMessage/delta":
        delta = params.get("delta")
        if isinstance(turn_id, str) and isinstance(delta, str):
            return ConversationEventType.ASSISTANT_TEXT_DELTA.value, turn_id, delta
        return None
    if method != "turn/completed":
        return None
    turn = params.get("turn")
    if not isinstance(turn_id, str) or not isinstance(turn, Mapping):
        return None
    status = turn.get("status")
    if status == "completed":
        return ConversationEventType.TURN_COMPLETED.value, turn_id, ""
    if status == "interrupted":
        return ConversationEventType.TURN_CANCELLED.value, turn_id, ""
    return ConversationEventType.TURN_FAILED.value, turn_id, "Codex turn failed."


class LocalCodexConversation:
    """Own one ephemeral Codex thread with at most one active turn."""

    def __init__(self, executable: Path, workspace: Path, *, timeout_seconds: float = 30.0):
        self.executable = executable.expanduser().resolve()
        self.workspace = workspace.expanduser().resolve()
        if not self.executable.is_file() or self.executable.suffix.lower() != ".exe":
            raise ValueError("a native Codex executable is required")
        if not self.workspace.is_dir():
            raise ValueError("Codex conversation workspace must already exist")
        if not 1.0 <= timeout_seconds <= 60.0:
            raise ValueError("conversation request timeout must be between 1 and 60 seconds")
        self.timeout_seconds = timeout_seconds
        self._write_lock = Lock()
        self._state_lock = Lock()
        self._responses: dict[int, Queue[object]] = {}
        self._events: deque[ConversationEvent] = deque(maxlen=MAX_CONVERSATION_EVENTS)
        self._next_request_id = 1
        self._next_sequence = 1
        self._thread_id: str | None = None
        self._active_turn_id: str | None = None
        self._closed = False
        self._shutdown = Event()
        self._process = self._start_process()
        if self._process.stdin is None or self._process.stdout is None:
            self.close()
            raise RuntimeError("Codex app-server pipes are unavailable")
        self._stdin = self._process.stdin
        self._reader = Thread(target=self._read_loop, args=(self._process.stdout,), daemon=True)
        self._reader.start()
        self._initialize()

    def _start_process(self) -> subprocess.Popen[str]:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            [
                str(self.executable),
                "app-server",
                "--listen",
                "stdio://",
                "-c",
                'web_search="disabled"',
                "-c",
                "mcp_servers={}",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_codex_environment(),
            creationflags=creationflags,
        )

    def _read_loop(self, stream: TextIO) -> None:
        try:
            for line in stream:
                if len(line.encode("utf-8", errors="replace")) > MAX_CODEX_LINE_BYTES:
                    self._fail_waiters(ValueError("Codex emitted an oversized protocol line"))
                    return
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._fail_waiters(ValueError("Codex emitted invalid JSON"))
                    return
                if not isinstance(message, Mapping):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int):
                    with self._state_lock:
                        waiter = self._responses.get(request_id)
                    if waiter is not None:
                        waiter.put(message)
                    continue
                curated = curate_codex_notification(message)
                if curated is not None:
                    self._append_event(*curated)
        finally:
            self._fail_waiters(EOFError("Codex app-server closed"))

    def _fail_waiters(self, error: BaseException) -> None:
        with self._state_lock:
            waiters = tuple(self._responses.values())
        for waiter in waiters:
            waiter.put(error)

    def _append_event(self, event_type: str, turn_id: str, text: str) -> None:
        if len(text) > MAX_EVENT_TEXT_CHARS:
            text = text[:MAX_EVENT_TEXT_CHARS]
        with self._state_lock:
            event = ConversationEvent(
                sequence=self._next_sequence,
                event_type=ConversationEventType(event_type),
                turn_id=turn_id,
                text=text,
            )
            self._events.append(event)
            self._next_sequence += 1
            if event.event_type in {
                ConversationEventType.TURN_COMPLETED,
                ConversationEventType.TURN_FAILED,
                ConversationEventType.TURN_CANCELLED,
            }:
                self._active_turn_id = None

    def _send(self, method: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("Codex conversation is closed")
            request_id = self._next_request_id
            self._next_request_id += 1
            waiter: Queue[object] = Queue(maxsize=1)
            self._responses[request_id] = waiter
        message = {"method": method, "id": request_id, "params": dict(params or {})}
        try:
            with self._write_lock:
                self._stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                self._stdin.flush()
            try:
                response = waiter.get(timeout=self.timeout_seconds)
            except Empty as exc:
                raise TimeoutError(f"Codex request {method} timed out") from exc
            if isinstance(response, BaseException):
                raise response
            if not isinstance(response, Mapping) or "error" in response:
                raise RuntimeError(f"Codex request {method} failed")
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise RuntimeError(f"Codex request {method} returned no result")
            return result
        finally:
            with self._state_lock:
                self._responses.pop(request_id, None)

    def _notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        message = {"method": method, "params": dict(params or {})}
        with self._write_lock:
            self._stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self._stdin.flush()

    def _initialize(self) -> None:
        self._send(
            "initialize",
            {
                "clientInfo": {
                    "name": "ariad_fabrication",
                    "title": "Ariad Fabrication",
                    "version": CONVERSATION_CONTRACT_VERSION,
                }
            },
        )
        self._notify("initialized")
        result = self._send(
            "thread/start",
            {
                "cwd": str(self.workspace),
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "ephemeral": True,
                "baseInstructions": (
                    "You are the conversational fabrication agent inside Ariad. "
                    "This thread has no Ariad fabrication tools yet. Reply directly and do not "
                    "use shell commands, files, web search, MCP, skills, or external context. "
                    "Never claim CAD generation, validation, slicing, printing, or physical proof."
                ),
            },
        )
        thread = result.get("thread")
        if not isinstance(thread, Mapping) or not isinstance(thread.get("id"), str):
            raise RuntimeError("Codex did not create a thread")
        self._thread_id = thread["id"]

    def start_turn(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("conversation prompt is required")
        prompt = prompt.strip()
        if len(prompt.encode("utf-8")) > MAX_CONVERSATION_PROMPT_BYTES:
            raise ValueError("conversation prompt exceeds the UTF-8 byte ceiling")
        with self._state_lock:
            if self._active_turn_id is not None:
                raise RuntimeError("a Codex turn is already active")
            thread_id = self._thread_id
        if thread_id is None:
            raise RuntimeError("Codex thread is unavailable")
        result = self._send(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            },
        )
        turn = result.get("turn")
        if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
            raise RuntimeError("Codex did not create a turn")
        turn_id = turn["id"]
        with self._state_lock:
            self._active_turn_id = turn_id
        self._append_event(ConversationEventType.TURN_STARTED.value, turn_id, "")
        Thread(target=self._turn_watchdog, args=(turn_id,), daemon=True).start()
        return turn_id

    def _turn_watchdog(self, turn_id: str) -> None:
        if self._shutdown.wait(MAX_TURN_SECONDS):
            return
        with self._state_lock:
            active = self._active_turn_id == turn_id
        if active:
            try:
                self.cancel_active_turn()
            except (OSError, RuntimeError, TimeoutError):
                self._append_event(
                    ConversationEventType.TURN_FAILED.value,
                    turn_id,
                    "Codex turn exceeded the time boundary.",
                )

    def events_after(self, sequence: int = 0) -> tuple[ConversationEvent, ...]:
        if sequence < 0:
            raise ValueError("event sequence cannot be negative")
        with self._state_lock:
            return tuple(event for event in self._events if event.sequence > sequence)

    def cancel_active_turn(self) -> bool:
        with self._state_lock:
            turn_id = self._active_turn_id
            thread_id = self._thread_id
        if turn_id is None or thread_id is None:
            return False
        self._send("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        return True

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._shutdown.set()
        try:
            if hasattr(self, "_stdin"):
                self._stdin.close()
        finally:
            process = getattr(self, "_process", None)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def __enter__(self) -> "LocalCodexConversation":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = [
    "CONVERSATION_CONTRACT_VERSION",
    "ConversationEvent",
    "ConversationEventType",
    "LocalCodexConversation",
    "MAX_CONVERSATION_EVENTS",
    "MAX_CONVERSATION_PROMPT_BYTES",
    "MAX_TURN_SECONDS",
    "curate_codex_notification",
]
