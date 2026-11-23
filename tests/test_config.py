import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from snake_ai.config import load_configuration
from snake_ai.ai import AISettings


class ConfigurationTests(unittest.TestCase):
    def test_settings_and_credentials_are_loaded_separately(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            (root / '.config').write_text('AI_PROVIDER=openrouter\nGAME_SPEED=-5\nOPENROUTER_API_KEY=wrong\n')
            (root / '.env').write_text('OPENROUTER_API_KEY=private\nGAME_SPEED=10\nAI_PROVIDER=ollama\n')
            load_configuration(root)
            self.assertEqual(os.environ['GAME_SPEED'], '-5')
            self.assertEqual(AISettings.from_env().provider, 'openrouter')
            self.assertEqual(AISettings.from_env().api_key, 'private')

    def test_file_settings_override_stale_environment_but_exported_key_wins(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'GAME_SPEED': '10', 'OPENROUTER_API_KEY': 'exported'}, clear=True):
            root = Path(directory)
            (root / '.config').write_text('GAME_SPEED=-3\n')
            (root / '.env').write_text('OPENROUTER_API_KEY=file-key\n')
            load_configuration(root)
            self.assertEqual(os.environ['GAME_SPEED'], '-3')
            self.assertEqual(os.environ['OPENROUTER_API_KEY'], 'exported')

    def test_missing_files_use_defaults(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            load_configuration(directory)
            self.assertEqual(AISettings.from_env().provider, 'ollama')

    def test_interpolation_cannot_copy_key_into_shared_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'OPENROUTER_API_KEY': 'private'}, clear=True):
            root = Path(directory)
            (root / '.config').write_text('AI_LOG_DIR=${OPENROUTER_API_KEY}\n')
            load_configuration(root)
            self.assertEqual(os.environ['AI_LOG_DIR'], '${OPENROUTER_API_KEY}')
