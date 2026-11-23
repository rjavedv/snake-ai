import json
from pathlib import Path
import tempfile
import unittest

from snake_ai.ai import AISettings, payload
from snake_ai.benchmark import BenchmarkGame, Scenario, run
from snake_ai.dashboard import read_run
from snake_ai.replay import Replay


def scenario(**changes):
    data = dict(name='test', version=1, width=6, height=5,
                snake=[[2, 2], [1, 2], [0, 2]], direction='RIGHT',
                food=[[3, 2], [1, 2]], food_target=2, move_limit=30)
    data.update(changes)
    return Scenario.from_dict(data)


class BenchmarkTests(unittest.TestCase):
    def test_pending_food_after_growth_activates_only_when_tail_leaves(self):
        game = BenchmarkGame(scenario())
        game.step('RIGHT')
        self.assertIsNone(game.food)
        self.assertIsNone(game.outcome)
        self.assertEqual(game.state()['benchmark']['pending_food'], [1, 2])
        game.step('UP')
        self.assertIsNone(game.food)
        game.step('LEFT')
        self.assertEqual(game.food, (1, 2))
        self.assertEqual(game.waiting_moves, 2)
        game.step('LEFT')
        game.step('DOWN')
        self.assertEqual(game.outcome, 'scenario_completed')
        self.assertEqual(game.food_events[-1], dict(item=2, coordinate=[1, 2], step=5, moves=4, waiting_moves=2))

    def test_initial_food_waits_and_no_random_spawn(self):
        s = scenario(food=[[0, 2]], food_target=1)
        a, b = BenchmarkGame(s), BenchmarkGame(s)
        self.assertIsNone(a.food)
        for move in ['RIGHT', 'UP', 'LEFT']:
            a.step(move)
            b.step(move)
            self.assertEqual(a.state(), b.state())
        self.assertEqual(a.food, (0, 2))

    def test_completion_wins_on_last_allowed_move(self):
        game = BenchmarkGame(scenario(food_target=1, move_limit=1))
        game.step('RIGHT')
        self.assertEqual(game.outcome, 'scenario_completed')

    def test_waiting_moves_are_bounded(self):
        game = BenchmarkGame(scenario(food=[[1, 2]], food_target=1, move_limit=1))
        game.step('RIGHT')
        self.assertEqual(game.outcome, 'move_limit_reached')
        self.assertEqual(game.waiting_moves, 1)

    def test_collision_takes_precedence_over_move_limit(self):
        game = BenchmarkGame(scenario(move_limit=1))
        game.step('DOWN')  # still safe
        self.assertEqual(game.outcome, 'move_limit_reached')
        game = BenchmarkGame(scenario(snake=[[5,2],[4,2],[3,2]], move_limit=1))
        game.step('RIGHT')
        self.assertEqual(game.outcome, 'wall_collision')

    def test_validation(self):
        invalid = [dict(food_target=3), dict(food_target=True), dict(move_limit=0),
                   dict(food=[[6,0]]), dict(snake=[[2,2],[0,2]]),
                   dict(direction='LEFT'), dict(width=2), dict(food_target=30, food=[[1,1]]*30)]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                scenario(**change)

    def test_fingerprint_covers_rules(self):
        self.assertEqual(scenario().fingerprint, scenario().fingerprint)
        self.assertNotEqual(scenario().fingerprint, scenario(move_limit=31).fingerprint)

    def test_replay_and_report_from_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            def decision(*args, **kwargs):
                return 'RIGHT'
            path, outcome = run(scenario(food_target=1), AISettings('ollama','fake','http://example'), directory, decision=decision)
            self.assertEqual(outcome, 'scenario_completed')
            replay = Replay(path)
            self.assertEqual(replay.states[-1]['score'], 1)
            report = read_run(path, Path(directory)/'report.html')
            self.assertEqual(report['food'][0]['moves'], 1)
            self.assertEqual(report['waiting_moves'], 0)
            self.assertIsNone(report['cost'])

    def test_model_error_is_distinct_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            def fail(*args, **kwargs):
                raise RuntimeError('secret-key')
            path, outcome = run(scenario(), AISettings('openrouter','fake','http://example','secret-key'), directory, decision=fail)
            self.assertEqual(outcome, 'model_error')
            self.assertNotIn('secret-key', path.read_text())
            self.assertEqual(Replay(path).states[-1]['step'], 0)

    def test_benchmark_prompt_explains_pending_food(self):
        request = payload('fake', BenchmarkGame(scenario()).state())
        self.assertIn('pending_food', request['questions']['move']['instructions'])

    def test_examples_validate(self):
        for path in Path('scenarios').glob('*.json'):
            Scenario.from_dict(json.loads(path.read_text()))


class ModelLifecycleTests(unittest.TestCase):
    def test_unload_request_and_acknowledgement(self):
        from unittest.mock import patch
        from snake_ai.benchmark import unload_ollama
        with patch('snake_ai.benchmark.urlopen') as transport:
            transport.return_value.__enter__.return_value.read.return_value = b'{"done":true,"done_reason":"unload"}'
            unload_ollama(AISettings('ollama', 'model-a', 'http://localhost:11434/'), 12)
            request = transport.call_args.args[0]
            self.assertEqual(request.full_url, 'http://localhost:11434/api/generate')
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(json.loads(request.data), dict(model='model-a', prompt='', keep_alive=0, stream=False))
            self.assertEqual(transport.call_args.kwargs['timeout'], 12)
            transport.return_value.__enter__.return_value.read.return_value = b'{"done":true}'
            with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
                unload_ollama(AISettings('ollama', 'model-a', 'http://localhost:11434'))

    def run_batch(self, directory, events, outcome='scenario_completed', provider='ollama', unload_error=None, run_error=None):
        from unittest.mock import patch
        from snake_ai.benchmark import main
        path = Path(directory)/'scenario.json'
        path.write_text(json.dumps(scenario().as_dict()))
        def fake_run(s, setting, *args):
            events.append(('run', setting.model))
            if run_error:
                raise run_error
            return Path('fake.jsonl'), outcome
        def fake_unload(setting, timeout):
            events.append(('unload', setting.model))
            if unload_error:
                raise unload_error
        with patch('sys.argv', ['benchmark', str(path), '--model', 'a', '--model', 'b', '--repeats', '2']), \
             patch('snake_ai.benchmark.load_configuration'), \
             patch('snake_ai.benchmark.AISettings.from_env', return_value=AISettings(provider,'default','http://example','key')), \
             patch.dict('os.environ', {'AI_TIMEOUT_SECONDS':'120'}), \
             patch('snake_ai.benchmark.run', side_effect=fake_run), \
             patch('snake_ai.benchmark.unload_ollama', side_effect=fake_unload), \
             patch('builtins.print'):
            main()

    def test_unloads_before_next_model_and_after_final_model(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            self.run_batch(directory, events)
            self.assertEqual(events, [('run','a'),('run','a'),('unload','a'),('run','b'),('run','b'),('unload','b')])

    def test_cleanup_on_errors_and_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            for outcome in ('model_error','interrupted'):
                events = []
                self.run_batch(directory, events, outcome=outcome)
                self.assertIn(('unload','a'),events)
                if outcome == 'interrupted':
                    self.assertEqual(events, [('run','a'),('unload','a')])
            events = []
            with self.assertRaises(KeyboardInterrupt):
                self.run_batch(directory, events, run_error=KeyboardInterrupt())
            self.assertEqual(events, [('run','a'),('unload','a')])
            events = []
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                self.run_batch(directory, events, run_error=RuntimeError('unexpected'))
            self.assertEqual(events, [('run','a'),('unload','a')])

    def test_unload_failure_stops_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            with self.assertRaises(SystemExit) as exc:
                self.run_batch(directory, events, unload_error=TimeoutError('timed out'))
            self.assertEqual(exc.exception.code, 1)
            self.assertEqual(events, [('run','a'),('run','a'),('unload','a')])

    def test_openrouter_never_unloads(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            self.run_batch(directory, events, provider='openrouter')
            self.assertTrue(all(kind == 'run' for kind, model in events))
