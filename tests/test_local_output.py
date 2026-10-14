import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_config


class LocalOutputTests(unittest.TestCase):
    def test_default_output_dir_is_local_documents(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"PEDRO_OUTPUT_DIR": ""}), \
             mock.patch.object(Path, "home", return_value=Path(d)):
            out = agent_config.default_output_dir()
            self.assertEqual(out, Path(d) / "Documents" / "PedroAgent"); self.assertTrue(out.is_dir())

    def test_missing_external_drive_falls_back_locally(self):
        import gta5_agent
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"PEDRO_OUTPUT_DIR": d}), \
             mock.patch.object(gta5_agent, "_external_drive_root", return_value=None):
            self.assertEqual(gta5_agent._resolve_drive_text("external/Reports/a.xlsx"), Path(d) / "Reports" / "a.xlsx")
            self.assertIsNone(gta5_agent._resolve_drive_text("C:/Users/x/a.xlsx"))

    def test_blender_default_is_local(self):
        import blender_task
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"PEDRO_OUTPUT_DIR": d}):
            self.assertEqual(blender_task._default_output("Basket"), str(Path(d) / "Blender" / "Basket.obj"))

    def test_prompt_never_requires_drive(self):
        import gta5_agent
        self.assertIn("never require an external drive", gta5_agent.SYSTEM_PROMPT)
        self.assertIn("full path", gta5_agent.SYSTEM_PROMPT)
