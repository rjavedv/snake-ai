"""Integration contracts between the launcher and existing entry points."""
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

from snake_ai.launcher.worker import apply_settings, main


class LauncherBridgeTests(unittest.TestCase):
    def test_run_settings_override_loaded_config_without_writing_files(self):
        def load():
            os.environ.update(AI_PROVIDER='ollama', LOCAL_AI_MODEL_NAME='configured')
        request = {'action': 'play', 'mode': 'ai',
                   'settings': {'AI_PROVIDER': 'ollama', 'LOCAL_AI_MODEL_NAME': 'chosen'}}
        with patch.dict(os.environ, {}, clear=True), patch('sys.stdin', io.StringIO(json.dumps(request))), \
                patch('snake_ai.launcher.worker.load_configuration', side_effect=load), \
                patch('snake_ai.app.main') as play:
            main()
            self.assertEqual(os.environ['LOCAL_AI_MODEL_NAME'], 'chosen')
            play.assert_called_once_with(load_config=False, initial_mode='ai', exit_on_escape=True)

    def test_benchmark_preserves_paths_models_and_repeats(self):
        arguments = ['scenario with spaces.json', '--model', 'custom:model', '--repeats', '3']
        request = {'action': 'benchmark', 'settings': {'AI_PROVIDER': 'openrouter'},
                   'arguments': arguments}
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['worker']), \
                patch('sys.stdin', io.StringIO(json.dumps(request))), \
                patch('snake_ai.launcher.worker.load_configuration'), \
                patch('snake_ai.benchmark.main') as benchmark:
            main()
            self.assertEqual(sys.argv[1:], arguments)
            benchmark.assert_called_once_with(load_config=False)
            self.assertEqual(os.environ['AI_PROVIDER'], 'openrouter')

    def test_settings_bridge_rejects_credentials_and_unknown_fields(self):
        with self.assertRaises(ValueError):
            apply_settings({'OPENROUTER_API_KEY': 'not-a-shareable-setting'})

    def test_launcher_escape_exits_active_game(self):
        import pygame
        from snake_ai.app import main as play
        escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        with patch.dict(os.environ, {'SDL_VIDEODRIVER': 'dummy', 'AI_PROVIDER': 'ollama'}), \
                patch('pygame.event.get', side_effect=[[escape]]) as events:
            play(load_config=False, initial_mode='human', exit_on_escape=True)
            self.assertEqual(events.call_count, 1)


if __name__ == '__main__':
    unittest.main()
