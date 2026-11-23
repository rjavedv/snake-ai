import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from snake_ai.ai import AISettings
from snake_ai.benchmark import Scenario, run
from snake_ai.dashboard import main, read_run


class DashboardTests(unittest.TestCase):
    def make_run(self, directory, decision=None):
        scenario = Scenario.from_dict(dict(name='report', version=1, width=5, height=3,
            snake=[[2,1],[1,1],[0,1]], direction='RIGHT', food=[[3,1]], food_target=1, move_limit=10))
        return run(scenario, AISettings('ollama','</script><script>alert(1)</script>','http://invalid'),
                   directory, decision=decision or (lambda *a, **k:'RIGHT'))[0]

    def test_interrupted_run_preserves_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            def interrupt(*a, **k):
                raise KeyboardInterrupt
            path = self.make_run(directory, interrupt)
            result = read_run(path, Path(directory)/'index.html')
            self.assertEqual((result['outcome'], result['moves']), ('interrupted', 0))

    def test_incomplete_log_is_not_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_run(directory)
            rows = path.read_text().splitlines()
            path.write_text(rows[0]+'\n')
            result = read_run(path, Path(directory)/'index.html')
            self.assertEqual(result['outcome'], 'incomplete')
            self.assertEqual(result['food'], [])

    def test_cost_requires_all_response_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_run(directory)
            with path.open('a') as f:
                for raw in [dict(usage=dict(cost=.03)), dict(usage=dict(cost=.02))]:
                    f.write(json.dumps(dict(event='response', raw=json.dumps(raw), elapsed_seconds=2))+'\n')
            result = read_run(path, Path(directory)/'index.html')
            self.assertAlmostEqual(result['cost'], .05)
            self.assertEqual(result['seconds'], 4)
            with path.open('a') as f:
                f.write(json.dumps(dict(event='response',raw='{}'))+'\n')
            self.assertIsNone(read_run(path, Path(directory)/'index.html')['cost'])

    def test_generated_report_escapes_embedded_data_and_reports_bad_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_run(directory)
            Path(directory,'bad.jsonl').write_text('{invalid\n')
            output = Path(directory,'report.html')
            with patch('sys.argv', ['dashboard',directory,'--output',str(output)]):
                main()
            text = output.read_text()
            self.assertNotIn('</script><script>alert(1)</script>', text)
            self.assertIn('bad.jsonl',text)
            self.assertNotIn('__BENCHMARK_DATA__',text)

    def test_wheel_includes_dashboard_template(self):
        self.assertTrue(Path(__import__('snake_ai.dashboard',fromlist=['']).__file__).with_name('dashboard.html').is_file())
