from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import remote


class BackupTests(unittest.TestCase):
    def test_existing_backup_is_never_removed_on_name_collision(self):
        instant = datetime(2026, 10, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "backups"
            folder.mkdir()
            archive = folder / "20261030T000000.000000Z.dump"
            archive.write_bytes(b"existing backup")
            with patch.object(remote, "ROOT", root), patch.object(remote, "datetime") as clock:
                clock.now.return_value = instant
                with self.assertRaises(FileExistsError):
                    remote.Deployment().backup()
            self.assertEqual(archive.read_bytes(), b"existing backup")


if __name__ == "__main__":
    unittest.main()
