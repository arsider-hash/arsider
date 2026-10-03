import tempfile
import unittest
from pathlib import Path

from bot import Controller
from core import Store, can_use_pc, parse_admins, parse_owner
from router import route_task


class AssistantTests(unittest.TestCase):
    def make_controller(self):
        db = Path(tempfile.mkdtemp()) / "test.db"
        return Controller(Store(str(db)), {1, 2}, owner_id=1)

    def test_two_admin_parser(self):
        self.assertEqual(parse_admins("1,2"), {1, 2})
        self.assertEqual(parse_owner("1"), 1)

    def test_pc_capability_is_owner_only(self):
        self.assertTrue(can_use_pc(1, 1))
        self.assertFalse(can_use_pc(2, 1))

    def test_unauthorized_is_silent(self):
        ctl = self.make_controller()
        self.assertEqual(ctl.text(999, "/status"), "")

    def test_off_rejects_tasks(self):
        ctl = self.make_controller()
        self.assertIn("Sistema OFF", ctl.text(1, "cercami un pdf"))

    def test_on_queues_task(self):
        ctl = self.make_controller()
        ctl.text(1, "/on")
        reply = ctl.text(1, "cercami un pdf su Xenakis")
        self.assertIn("ROUTE: VIVO", reply)
        self.assertEqual(ctl.store.queued_count(), 1)

    def test_collaborator_cannot_use_pc(self):
        ctl = self.make_controller()
        ctl.text(1, "/on")
        reply = ctl.text(2, "normalizza tutti i wav sul Lenovo")
        self.assertIn("solo per OWNER", reply)
        self.assertEqual(ctl.store.queued_count(), 0)

    def test_owner_can_use_pc_in_dm(self):
        ctl = self.make_controller()
        ctl.text(1, "/on")
        reply = ctl.text(1, "normalizza tutti i wav sul Lenovo", source="dm")
        self.assertIn("ROUTE: PC", reply)
        self.assertEqual(ctl.store.queued_count(), 1)

    def test_group_never_routes_pc(self):
        ctl = self.make_controller()
        ctl.text(1, "/on")
        reply = ctl.text(1, "normalizza tutti i wav sul Lenovo", source="arsider")
        self.assertIn("solo in DM", reply)
        self.assertEqual(ctl.store.queued_count(), 0)

    def test_bind_arsider_owner_only(self):
        ctl = self.make_controller()
        self.assertIn("Solo OWNER", ctl.bind_arsider_chat(2, -1001))
        self.assertIn("associata", ctl.bind_arsider_chat(1, -1001))
        self.assertEqual(ctl.store.get("arsider_chat_id"), "-1001")

    def test_pc_router(self):
        self.assertEqual(route_task("normalizza tutti i wav sul Lenovo"), "pc")

    def test_stop_pauses_queue(self):
        ctl = self.make_controller()
        ctl.text(1, "/on")
        ctl.text(1, "scarica questo pdf")
        reply = ctl.text(1, "/stop")
        self.assertIn("1 task", reply)
        self.assertEqual(ctl.store.queued_count(), 0)
        self.assertEqual(ctl.store.get("system"), "OFF")


if __name__ == "__main__":
    unittest.main()
