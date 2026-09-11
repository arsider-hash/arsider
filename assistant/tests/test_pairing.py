from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pair_admins import write_admins
from core import parse_admins


class PairingTests(unittest.TestCase):
    def test_write_admins_replaces_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text("TELEGRAM_BOT_TOKEN=x\nADMIN_IDS=\nDB_PATH=data/test.db\n", encoding="utf-8")
            write_admins([123, 456], p)
            text = p.read_text(encoding="utf-8")
            self.assertIn("ADMIN_IDS=123,456", text)
            self.assertEqual(parse_admins("123,456"), {123, 456})

    def test_write_admins_appends_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text("TELEGRAM_BOT_TOKEN=x\n", encoding="utf-8")
            write_admins([1, 2], p)
            self.assertIn("ADMIN_IDS=1,2", p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
