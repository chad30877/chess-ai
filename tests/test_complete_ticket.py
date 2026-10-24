"""結案命令需先同步及讀回，不能把失敗或未驗收工作關閉。"""

import unittest

from scripts.complete_ticket import complete_ticket


def body(done):
    return f"## 驗收條件\n- [{'x' if done else ' '}] 完成 UI 流程驗證\n"


class MemoryTicket:
    def __init__(self, checked=False, state="OPEN", ignore_update=False, ignore_close=False):
        self.data = {"body": body(checked), "state": state}
        self.writes = []
        self.ignore_update = ignore_update
        self.ignore_close = ignore_close

    def read(self):
        return dict(self.data)

    def update(self, text):
        self.writes.append("update")
        if not self.ignore_update:
            self.data["body"] = text

    def close(self):
        self.writes.append("close")
        if not self.ignore_close:
            self.data["state"] = "CLOSED"


class CompleteTicketTests(unittest.TestCase):
    def test_syncs_verifies_then_closes_and_is_safe_to_repeat(self):
        api = MemoryTicket()
        self.assertEqual(complete_ticket(body(True), api)["state"], "CLOSED")
        self.assertEqual(api.writes, ["update", "close"])
        complete_ticket(body(True), api)
        self.assertEqual(api.writes, ["update", "close"])

    def test_unchecked_local_acceptance_never_writes(self):
        api = MemoryTicket()
        with self.assertRaises(ValueError):
            complete_ticket(body(False), api)
        self.assertEqual(api.writes, [])

    def test_changed_requirement_never_overwrites_remote(self):
        api = MemoryTicket()
        with self.assertRaises(ValueError):
            complete_ticket(body(True).replace("UI", "另一個"), api)
        self.assertEqual(api.writes, [])

    def test_failed_update_readback_does_not_close(self):
        api = MemoryTicket(ignore_update=True)
        with self.assertRaises(ValueError):
            complete_ticket(body(True), api)
        self.assertEqual(api.writes, ["update"])

    def test_failed_close_readback_is_not_reported_complete(self):
        api = MemoryTicket(ignore_close=True)
        with self.assertRaises(ValueError):
            complete_ticket(body(True), api)
        self.assertEqual(api.data["state"], "OPEN")

    def test_retry_after_close_failure_reuses_synced_body(self):
        api = MemoryTicket(ignore_close=True)
        with self.assertRaises(ValueError):
            complete_ticket(body(True), api)
        api.ignore_close = False
        self.assertEqual(complete_ticket(body(True), api)["state"], "CLOSED")
        self.assertEqual(api.writes.count("update"), 1)
