import signal
import unittest
from unittest.mock import Mock, patch

from runtime import playback as playback_module


class PlaybackControllerTest(unittest.TestCase):
    def setUp(self):
        self.controller = playback_module.PlaybackController()

    def test_terminate_known_process_reaps_registered_handle(self):
        process = Mock()
        process.pid = 4321
        process.poll.side_effect = [None, None]
        self.controller._processes[process.pid] = process

        with patch.object(self.controller, "_signal_process_group", return_value=True) as signal_group:
            self.controller._terminate_process_group(process.pid)

        process.wait.assert_called_once_with(timeout=0.75)
        self.assertEqual(signal_group.call_args_list[0].args, (process.pid, signal.SIGCONT))
        self.assertEqual(signal_group.call_args_list[1].args, (process.pid, signal.SIGTERM))
        self.assertNotIn(process.pid, self.controller._processes)

    def test_terminate_known_process_kills_after_timeout(self):
        process = Mock()
        process.pid = 9876
        process.poll.side_effect = [None, None]
        process.wait.side_effect = [
            playback_module.subprocess.TimeoutExpired(cmd="mpg123", timeout=0.75),
            None,
        ]
        self.controller._processes[process.pid] = process

        with patch.object(self.controller, "_signal_process_group", return_value=True) as signal_group:
            self.controller._terminate_process_group(process.pid)

        self.assertEqual(process.wait.call_args_list[0].kwargs["timeout"], 0.75)
        self.assertEqual(process.wait.call_args_list[1].kwargs["timeout"], 0.5)
        self.assertEqual(signal_group.call_args_list[2].args, (process.pid, signal.SIGKILL))
        self.assertNotIn(process.pid, self.controller._processes)


if __name__ == "__main__":
    unittest.main()
