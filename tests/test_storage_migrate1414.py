import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage_migrate  # noqa: E402


def _db(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(folder / "chat_history.db"))
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session TEXT, role TEXT, text TEXT, ts REAL)")
    con.executemany("INSERT INTO messages(session, role, text, ts) VALUES ('s','user','hi',0)", [()] * n)
    con.commit()
    con.close()


class MigrateTests(unittest.TestCase):
    def test_copies_older_history_once_and_keeps_old_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / "old" / "workspace", root / "new" / "workspace"
            _db(old, 50)
            (old / "bots").mkdir()
            (old / "bots" / "fay.json").write_text("{}", encoding="utf-8")
            (old.parent / ".env").write_text("GROQ_API_KEY=abc12345\nGEMINI_API_KEY=old\n", encoding="utf-8")
            _db(new, 3)
            (new.parent / ".env").write_text("GEMINI_API_KEY=new\n", encoding="utf-8")
            out = storage_migrate.migrate(new, [old])
            self.assertTrue(out["migrated"], out)
            self.assertEqual(storage_migrate._messages(new), 50)
            self.assertTrue((new / "bots" / "fay.json").is_file())
            self.assertEqual(storage_migrate._messages(old), 50)          # old left alone
            self.assertTrue(any((new / "pre_migration_backup").rglob("chat_history.db")))
            added = storage_migrate.merge_env(new.parent / ".env", old.parent / ".env")
            self.assertEqual(added, ["GROQ_API_KEY"])
            self.assertIn("GEMINI_API_KEY=new", (new.parent / ".env").read_text(encoding="utf-8"))
            self.assertFalse(storage_migrate.migrate(new, [old])["migrated"])   # once only

    def test_nothing_when_current_has_more(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db(root / "old", 2)
            _db(root / "new", 9)
            self.assertFalse(storage_migrate.migrate(root / "new", [root / "old"])["migrated"])


if __name__ == "__main__":
    unittest.main()
