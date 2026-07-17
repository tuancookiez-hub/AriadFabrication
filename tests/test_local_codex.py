from pathlib import Path
import unittest

from ariad_fabrication.local_codex import (
    LocalCodexStatus,
    probe_local_codex,
    snapshot_from_account_response,
)


class LocalCodexContractTests(unittest.TestCase):
    def test_chatgpt_account_is_reduced_without_email_or_tokens(self):
        snapshot = snapshot_from_account_response(
            "codex-cli 0.144.5",
            {
                "id": 2,
                "result": {
                    "account": {
                        "type": "chatgpt",
                        "email": "private@example.invalid",
                        "planType": "pro",
                        "accessToken": "must-not-survive",
                    },
                    "requiresOpenaiAuth": True,
                },
            },
        )
        value = snapshot.to_dict()
        self.assertEqual(snapshot.status, LocalCodexStatus.READY)
        self.assertTrue(snapshot.conversation_available)
        self.assertEqual(value["authentication"], "chatgpt")
        self.assertNotIn("email", str(value).lower())
        self.assertNotIn("token", str(value).lower())
        self.assertFalse(value["conversation_started"])
        self.assertFalse(value["workspace_mutated"])
        self.assertFalse(value["hardware_actions"])

    def test_missing_account_is_explicitly_unauthenticated(self):
        snapshot = snapshot_from_account_response(
            "codex-cli 0.137.0",
            {"result": {"account": None, "requiresOpenaiAuth": True}},
        )
        self.assertEqual(snapshot.status, LocalCodexStatus.UNAUTHENTICATED)
        self.assertIsNone(snapshot.authentication)
        self.assertFalse(snapshot.conversation_available)

    def test_authenticated_old_cli_is_incompatible_not_ready(self):
        snapshot = snapshot_from_account_response(
            "codex-cli 0.137.0",
            {
                "result": {
                    "account": {"type": "chatgpt", "email": "private@example.invalid", "planType": "pro"},
                    "requiresOpenaiAuth": True,
                }
            },
        )
        self.assertEqual(snapshot.status, LocalCodexStatus.INCOMPATIBLE)
        self.assertFalse(snapshot.conversation_available)

    def test_invalid_or_unconfigured_executable_is_never_launched(self):
        snapshot = probe_local_codex(Path("missing-codex.exe"))
        self.assertEqual(snapshot.status, LocalCodexStatus.UNAVAILABLE)
        self.assertEqual(snapshot.tools_registered, 0)
        self.assertFalse(snapshot.hardware_actions)

    def test_malformed_account_response_fails_closed(self):
        for value in (
            {},
            {"result": None},
            {"result": {"account": None}},
            {"result": {"account": "yes", "requiresOpenaiAuth": True}},
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    snapshot_from_account_response("codex-cli 0.137.0", value)


if __name__ == "__main__":
    unittest.main()
