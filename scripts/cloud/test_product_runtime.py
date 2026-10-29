"""An old supervisor cannot stop a replacement collaboration process."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime


class ProductOwnershipTests(unittest.TestCase):
    def test_stale_stop_refuses_replacement_before_signalling_or_removing_its_record(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            record = folder / "process.json"
            replacement = {"pid": 123, "port": 3000}
            record.write_text(json.dumps(replacement))
            with patch.object(runtime, "SERVICE", folder), patch.object(runtime, "RECORD", record), patch.object(runtime.os, "kill") as kill:
                with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                    runtime.stop(expected_record={"pid": 122, "port": 3000})
                kill.assert_not_called()
                self.assertEqual(json.loads(record.read_text()), replacement)


if __name__ == "__main__":
    unittest.main()
