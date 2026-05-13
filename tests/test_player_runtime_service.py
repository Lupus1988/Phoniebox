import unittest
from unittest.mock import patch

from services import player_runtime_service


class PlayerRuntimeServiceTest(unittest.TestCase):
    def test_handle_player_action_standby_calls_power_off(self):
        snapshot = {
            "player": {"current_album": "Test"},
            "runtime": {},
            "settings": {},
        }

        with patch.object(player_runtime_service.runtime_service, "player_snapshot", return_value=snapshot), patch.object(
            player_runtime_service, "get_player_snapshot", return_value=snapshot
        ), patch.object(
            player_runtime_service.runtime_service, "power_off", return_value={"runtime": {}, "player": {}}
        ) as power_off:
            result, status_code = player_runtime_service.handle_player_action("standby")

        self.assertEqual(status_code, 200)
        self.assertTrue(result["ok"])
        power_off.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
