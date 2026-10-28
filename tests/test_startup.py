"""Check startup failure boundaries using temporary, harmless stage helpers."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('session_stages',Path(__file__).resolve().parents[1]/'scripts/start-session-stages.py')
stages=importlib.util.module_from_spec(spec);spec.loader.exec_module(stages)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'scripts').mkdir()
        for name in ('display','audio','steam','sunshine'):
            self.helper(name)

    def helper(self,name,exit_code=0):
        code="from pathlib import Path\np=Path(__file__).resolve().parents[1]/'order'\nwith p.open('a') as f:f.write("+repr(name+'\n')+")\nraise SystemExit("+str(exit_code)+")\n"
        (self.root/'scripts'/('start-'+name+'.py')).write_text(code)

    def test_steam_initializes_before_capture(self):
        self.helper('transport');stages.start(self.root)
        self.assertEqual((self.root/'order').read_text().splitlines(),['transport','display','audio','steam','sunshine'])

    def test_failure_stops_before_starting_capture(self):
        self.helper('steam',7)
        with self.assertRaisesRegex(RuntimeError,'STAGE_FAILED: steam exited 7'):stages.start(self.root)
        self.assertEqual((self.root/'order').read_text().splitlines(),['display','audio','steam'])

    def test_hung_stage_has_a_named_bounded_failure(self):
        with patch.object(stages.subprocess,'run',side_effect=subprocess.TimeoutExpired('display',35)) as run:
            with self.assertRaisesRegex(RuntimeError,'STAGE_TIMEOUT: display'):stages.start(self.root)
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.kwargs['timeout'],35)
