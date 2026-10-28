"""Regression tests for hung Steam IPC, game protection and PID reuse."""
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import session_shutdown as shutdown


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_game_prevents_any_shutdown(self):
        with patch.object(shutdown.subprocess,'run') as run,patch.object(shutdown.os,'kill') as kill:
            with self.assertRaisesRegex(RuntimeError,'GAME_RUNNING'):
                shutdown.stop_steam(self.root,lambda:True)
            run.assert_not_called();kill.assert_not_called()

    def test_already_stopped_is_noop(self):
        with patch.object(shutdown,'_steam_masters',return_value={}),patch.object(shutdown.subprocess,'run') as run,patch.object(shutdown.os,'kill') as kill:
            self.assertEqual(shutdown.stop_steam(self.root,lambda:False)['method'],'already-stopped')
            run.assert_not_called();kill.assert_not_called()

    def test_normal_ipc_exit_never_signals(self):
        with patch.object(shutdown,'_steam_masters',return_value={42:(100,'private-steam')}),patch.object(shutdown,'_wait_steam',return_value=True),patch.object(shutdown.subprocess,'run'),patch.object(shutdown.os,'kill') as kill:
            self.assertEqual(shutdown.stop_steam(self.root,lambda:False)['method'],'steam-ipc')
            kill.assert_not_called()

    def test_hung_ipc_terminates_only_verified_master(self):
        identity=(100,'private-steam')
        with patch.object(shutdown,'_steam_masters',return_value={42:identity}),patch.object(shutdown,'_steam_identity',return_value=identity),patch.object(shutdown,'_wait_steam',side_effect=[False,True]),patch.object(shutdown.subprocess,'run'),patch.object(shutdown.os,'kill') as kill:
            result=shutdown.stop_steam(self.root,lambda:False)
            self.assertEqual(result,{'method':'steam-sigterm','term_pids':[42]})
            kill.assert_called_once_with(42,signal.SIGTERM)

    def test_pid_reuse_is_not_signalled(self):
        with patch.object(shutdown,'_steam_masters',return_value={42:(100,'private-steam')}),patch.object(shutdown,'_steam_identity',return_value=(200,'private-steam')),patch.object(shutdown,'_wait_steam',side_effect=[False,True]),patch.object(shutdown.subprocess,'run'),patch.object(shutdown.os,'kill') as kill:
            shutdown.stop_steam(self.root,lambda:False)
            kill.assert_not_called()

    def test_game_started_during_ipc_is_protected(self):
        with patch.object(shutdown,'_steam_masters',return_value={42:(100,'private-steam')}),patch.object(shutdown,'_wait_steam',return_value=False),patch.object(shutdown.subprocess,'run'),patch.object(shutdown.os,'kill') as kill:
            responses=iter([False,True])
            with self.assertRaisesRegex(RuntimeError,'GAME_RUNNING'):
                shutdown.stop_steam(self.root,lambda:next(responses))
            kill.assert_not_called()

    def test_unresponsive_sigterm_fails_without_force_kill(self):
        identity=(100,'private-steam')
        with patch.object(shutdown,'_steam_masters',return_value={42:identity}),patch.object(shutdown,'_steam_identity',return_value=identity),patch.object(shutdown,'_wait_steam',return_value=False),patch.object(shutdown.subprocess,'run'),patch.object(shutdown.os,'kill') as kill:
            with self.assertRaisesRegex(RuntimeError,'STEAM_STILL_RUNNING'):
                shutdown.stop_steam(self.root,lambda:False)
            kill.assert_called_once_with(42,signal.SIGTERM)


if __name__=='__main__':unittest.main()
