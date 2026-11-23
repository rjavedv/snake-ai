import json
import tempfile
import unittest
from pathlib import Path

from snake_ai.engine import Game
from snake_ai.replay import Replay


class ReplayTests(unittest.TestCase):
    def load(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'run.jsonl'
        path.write_text('\n'.join(json.dumps(row) for row in rows))
        return Replay(path)

    def test_each_row_and_backtracking_preserve_states(self):
        game = Game(seed=3)
        initial = game.state()
        game.step('DOWN')
        after = game.state()
        replay = self.load([
            {'event': 'session_start', 'initial_state': initial},
            {'event': 'request', 'payload': {'state': initial}},
            {'event': 'response', 'raw': '{"answers": {}}'},
            {'event': 'transition', 'state': after},
            {'event': 'session_end', 'state': after}])
        self.assertEqual(replay.states, [initial, initial, initial, after, after])
        self.assertEqual(replay.state_rows, [1, 2, 2, 4, 5])
        replay.move(-1)
        self.assertEqual(replay.index, 0)
        for _ in range(10):
            replay.move(1)
        self.assertEqual(replay.index, 4)
        replay.move(-2)
        self.assertEqual(replay.states[replay.index], initial)

    def test_no_state_does_not_invent_positions(self):
        replay = self.load([{'event': 'response'}])
        self.assertIsNone(replay.states[0])

    def test_fatal_position_preserved(self):
        game = Game()
        game.snake = [(23, 4), (22, 4), (21, 4)]
        game.step('RIGHT')
        replay = self.load([{'event': 'game_over', 'state': game.state()}])
        self.assertEqual(replay.states[0]['snake'][0], [24, 4])

    def test_empty_and_malformed_files_report_errors(self):
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.load([])
        with self.assertRaisesRegex(ValueError, 'Row 1'):
            self.load([{'state': {'board': {'width': 0}}}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.jsonl'
            path.write_text('{"event":"start"}\nnot json\n')
            with self.assertRaisesRegex(ValueError, 'Row 2'):
                Replay(path)
