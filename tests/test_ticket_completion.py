"""工作票結案檢查，避免未驗收或未同步就宣告完成。"""

import json
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_ticket_completion import check_ticket, inspect_tickets, main


def ticket(done=True, text="實際操作驗收"):
    return f"## 驗收條件\n\n- [{'x' if done else ' '}] {text}\n\n## 備註\n- [ ] 後續建議\n"


class TicketCompletionTests(unittest.TestCase):
    def test_closed_with_pending_manual_acceptance_is_rejected(self):
        body = ticket(False)
        errors = check_ticket(body, {"state": "CLOSED", "body": body})
        self.assertTrue(any("本機驗收未完成" in error for error in errors))
        self.assertTrue(any("GitHub驗收未完成" in error for error in errors))

    def test_open_pending_work_is_valid_but_not_ready_to_close(self):
        remote = {"state": "OPEN", "body": ticket(False)}
        self.assertEqual(check_ticket(ticket(False), remote), [])
        self.assertTrue(check_ticket(ticket(False), remote, "before-close"))

    def test_after_close_detects_forgotten_remote_close(self):
        remote = {"state": "OPEN", "body": ticket()}
        self.assertEqual(check_ticket(ticket(), remote, "before-close"), [])
        self.assertTrue(check_ticket(ticket(), remote, "after-close"))

    def test_checked_but_different_requirements_are_not_synchronized(self):
        errors = check_ticket(ticket(), {"state": "CLOSED", "body": ticket(text="另一項驗收")})
        self.assertTrue(any("不一致" in error for error in errors))

    def test_completed_ticket_ignores_optional_followup_checklist(self):
        self.assertEqual(check_ticket(ticket(), {"state": "CLOSED", "body": ticket()}), [])

    def test_missing_acceptance_cannot_pass_vacuously(self):
        self.assertTrue(check_ticket("", {"state": "CLOSED", "body": ""}))

    def test_github_failure_is_unverified_instead_of_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ticket.md").write_text(ticket(), encoding="utf-8")
            manifest = root / "publication.json"
            manifest.write_text(json.dumps({"repository": "owner/repo", "tickets": [
                {"number": 2, "file": "ticket.md"},
            ]}), encoding="utf-8")
            with patch("scripts.check_ticket_completion.shutil.which", return_value="gh"), patch(
                "scripts.check_ticket_completion.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="offline"),
            ), redirect_stderr(StringIO()) as errors:
                self.assertEqual(main(["--manifest", str(manifest)]), 2)
            self.assertIn("offline", errors.getvalue())

    def test_manifest_maps_file_to_live_issue_without_using_publication_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ticket.md").write_text(ticket(), encoding="utf-8")
            manifest = root / "publication.json"
            manifest.write_text(json.dumps({
                "repository": "owner/repo", "spec": {"number": 1},
                "tickets": [{"number": 2, "file": "ticket.md", "body_sha256": "old-publication"}],
            }), encoding="utf-8")
            def fetch(repo, number):
                self.assertEqual((repo, number), ("owner/repo", 2))
                return {"number": number, "state": "CLOSED", "body": ticket()}
            self.assertEqual(inspect_tickets(manifest, 2, "after-close", fetch), [])
            with self.assertRaises(ValueError):
                inspect_tickets(manifest, 1, "audit", fetch)
