import json
import os
import tempfile
import unittest
from unittest.mock import patch
from snake_ai.ai import AISettings, SessionLog, decide
from snake_ai.engine import Game
from snake_ai.replay import Replay


class ProviderTests(unittest.TestCase):
    def test_configuration_selection_and_legacy_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(AISettings.from_env().provider, 'ollama')
        with patch.dict(os.environ, {'AI_PROVIDER': ' OPENROUTER ', 'OPENROUTER_API_KEY': 'secret'}, clear=True):
            settings = AISettings.from_env()
            self.assertEqual(settings.model, 'typesafe/jev-1.14')
            self.assertEqual(settings.base_url, 'https://openrouter.ai/api')
            settings.validate()
            self.assertNotIn('secret', repr(settings))
        with patch.dict(os.environ, {'AI_PROVIDER': 'other'}, clear=True):
            with self.assertRaises(ValueError):
                AISettings.from_env()

    def test_openrouter_auth_same_payload_and_replay(self):
        response = {'answers': {'move': {'probabilities': {'UP': .2, 'DOWN': .1, 'RIGHT': .7}}},
                    'usage': {'cost': .00001}}
        with tempfile.TemporaryDirectory() as directory:
            log = SessionLog(directory)
            with patch('snake_ai.ai.urlopen') as transport:
                transport.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
                move = decide('typesafe/jev-1.14', Game().state(), 'https://openrouter.ai/api', 3, log,
                              provider='openrouter', api_key='secret')
                request = transport.call_args.args[0]
                self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/systemone')
                self.assertEqual(request.get_header('Authorization'), 'Bearer secret')
                self.assertEqual(json.loads(request.data)['model'], 'typesafe/jev-1.14')
                self.assertEqual(move, 'RIGHT')
            self.assertNotIn('secret', log.path.read_text())
            replay = Replay(log.path)
            self.assertEqual(len(replay.rows), 2)
            self.assertEqual(replay.rows[0]['provider'], 'openrouter')
            self.assertEqual(json.loads(replay.rows[1]['raw'])['usage']['cost'], .00001)

    def test_configured_openrouter_base_url_reaches_request_and_log(self):
        from pathlib import Path
        from snake_ai.config import load_configuration
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            (root / '.config').write_text('AI_PROVIDER=openrouter\nOPENROUTER_BASE_URL=https://gateway.example/api/\n')
            (root / '.env').write_text('OPENROUTER_API_KEY=secret\n')
            load_configuration(root)
            settings = AISettings.from_env()
            log = SessionLog(root / 'logs')
            with patch('snake_ai.ai.urlopen') as transport:
                transport.return_value.__enter__.return_value.read.return_value = b'{"answers":{"move":{"probabilities":{"UP":0.2,"DOWN":0.1,"RIGHT":0.7}}}}'
                decide(settings.model, Game().state(), settings.base_url, 3, log,
                       provider=settings.provider, api_key=settings.api_key)
                self.assertEqual(transport.call_args.args[0].full_url,
                                 'https://gateway.example/api/v1/systemone')
            record = json.loads(log.path.read_text().splitlines()[0])
            self.assertEqual(record['endpoint'], 'https://gateway.example/api/v1/systemone')

    def test_missing_key_never_sends_request(self):
        with tempfile.TemporaryDirectory() as directory, patch('snake_ai.ai.urlopen') as transport:
            with self.assertRaisesRegex(ValueError, 'OPENROUTER_API_KEY'):
                decide('typesafe/jev-1.14', Game().state(), 'https://openrouter.ai/api', 3,
                       SessionLog(directory), provider='openrouter')
            transport.assert_not_called()

    def test_ollama_does_not_send_cloud_key(self):
        with tempfile.TemporaryDirectory() as directory, patch('snake_ai.ai.urlopen') as transport:
            transport.return_value.__enter__.return_value.read.return_value = b'{"answers":{"move":{"probabilities":{"UP":0.2,"DOWN":0.1,"RIGHT":0.7}}}}'
            decide('local', Game().state(), 'http://localhost:11434', 3, SessionLog(directory))
            self.assertIsNone(transport.call_args.args[0].get_header('Authorization'))

    def test_error_key_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            log = SessionLog(directory)
            with patch('snake_ai.ai.urlopen', side_effect=ValueError('bad secret')):
                with self.assertRaisesRegex(RuntimeError, r'bad \[REDACTED\]'):
                    decide('typesafe/jev-1.14', Game().state(), 'https://openrouter.ai/api', 3,
                           log, provider='openrouter', api_key='secret')
            self.assertNotIn('secret', log.path.read_text())
