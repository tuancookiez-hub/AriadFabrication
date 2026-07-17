import unittest

from ariad_fabrication.codex_conversation import (
    ConversationEvent,
    ConversationEventType,
    curate_codex_notification,
)


class CodexConversationContractTests(unittest.TestCase):
    def test_only_assistant_text_and_terminal_lifecycle_are_curated(self):
        delta = curate_codex_notification(
            {
                "method": "item/agentMessage/delta",
                "params": {"turnId": "turn_1", "delta": "Hello"},
            }
        )
        completed = curate_codex_notification(
            {
                "method": "turn/completed",
                "params": {"turnId": "turn_1", "turn": {"status": "completed"}},
            }
        )
        self.assertEqual(delta, ("assistant_text_delta", "turn_1", "Hello"))
        self.assertEqual(completed, ("turn_completed", "turn_1", ""))

    def test_reasoning_commands_files_and_raw_errors_are_not_exposed(self):
        for method in (
            "item/reasoning/delta",
            "item/commandExecution/delta",
            "item/fileChange/delta",
            "error",
            "account/updated",
        ):
            with self.subTest(method=method):
                self.assertIsNone(
                    curate_codex_notification(
                        {"method": method, "params": {"turnId": "turn_secret", "delta": "secret"}}
                    )
                )

    def test_failed_and_interrupted_turns_have_generic_bounded_events(self):
        failed = curate_codex_notification(
            {
                "method": "turn/completed",
                "params": {
                    "turnId": "turn_2",
                    "turn": {"status": "failed", "error": {"message": "private path"}},
                },
            }
        )
        interrupted = curate_codex_notification(
            {
                "method": "turn/completed",
                "params": {"turnId": "turn_3", "turn": {"status": "interrupted"}},
            }
        )
        self.assertEqual(failed, ("turn_failed", "turn_2", "Codex turn failed."))
        self.assertEqual(interrupted, ("turn_cancelled", "turn_3", ""))

    def test_event_contract_is_closed_around_public_fields(self):
        event = ConversationEvent(1, ConversationEventType.TURN_STARTED, "turn_1")
        self.assertEqual(
            set(event.to_dict()),
            {"contract_version", "sequence", "event_type", "turn_id", "text"},
        )
        with self.assertRaises(ValueError):
            ConversationEvent(0, ConversationEventType.TURN_STARTED, "turn_1")


if __name__ == "__main__":
    unittest.main()
