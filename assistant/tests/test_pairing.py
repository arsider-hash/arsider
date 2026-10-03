from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pair_admins import write_pairing
from core import parse_admins, parse_owner


class PairingTests(unittest.TestCase):
    def test_write_pairing_replaces_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text(
                "TELEGRAM_BOT_TOKEN=x\nADMIN_IDS=\nOWNER_ID=\nDB_PATH=data/test.db\n",
                encoding="utf-8",
            )
            write_pairing([123, 456], p)
            text = p.read_text(encoding="utf-8")
            self.assertIn("ADMIN_IDS=123,456", text)
            self.assertIn("OWNER_ID=123", text)
            self.assertEqual(parse_admins("123,456"), {123, 456})
            self.assertEqual(parse_owner("123"), 123)

    def test_write_pairing_appends_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text("TELEGRAM_BOT_TOKEN=x\n", encoding="utf-8")
            write_pairing([1, 2], p)
            text = p.read_text(encoding="utf-8")
            self.assertIn("ADMIN_IDS=1,2", text)
            self.assertIn("OWNER_ID=1", text)


if __name__ == "__main__":
    unittest.main()
