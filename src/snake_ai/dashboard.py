"""Generate an offline benchmark dashboard from existing JSONL logs."""
import argparse
import json
import math
import os
from pathlib import Path
from urllib.parse import quote


def read_run(path, output):
    with path.open(encoding='utf-8') as stream:
        rows = [json.loads(line) for line in stream]
    starts = [r for r in rows if r.get('event') == 'session_start' and 'benchmark' in r]
    if not starts:
        return None
    start = starts[0]
    ends = [r for r in rows if r.get('event') == 'session_end']
    end = ends[-1] if ends else {}
    state = end.get('state') or next((r['state'] for r in reversed(rows) if 'state' in r), start['initial_state'])
    timings, costs = [], []
    responses = 0
    for row in rows:
        if row.get('event') not in ('response', 'error'):
            continue
        seconds = row.get('elapsed_seconds')
        if type(seconds) in (int, float) and math.isfinite(seconds):
            timings.append(seconds)
        if row.get('event') == 'response':
            responses += 1
            try:
                raw = json.loads(row['raw'])
                cost = raw.get('usage', {}).get('cost')
                if type(cost) in (int, float) and math.isfinite(cost):
                    costs.append(cost)
            except (ValueError, TypeError, AttributeError):
                pass
    return dict(id=path.name, model=start['model'], provider=start['provider'],
                benchmark=start['benchmark'], timestamp=start['timestamp'],
                outcome=state.get('outcome') or 'incomplete', moves=state['step'], score=state['score'],
                waiting_moves=end.get('summary', {}).get('waiting_moves'),
                food=end.get('summary', {}).get('food_events', [r for r in rows if r.get('event') == 'food_eaten']),
                seconds=sum(timings) if timings else None,
                cost=sum(costs) if costs and len(costs) == responses else None,
                log=quote(os.path.relpath(path.resolve(), output.parent.resolve()), safe='/'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=Path('logs/benchmarks'))
    parser.add_argument('--output', type=Path, default=Path('logs/benchmark-dashboard.html'))
    args = parser.parse_args()
    runs, warnings = [], []
    if not args.directory.is_dir():
        parser.error(f'Log directory does not exist: {args.directory}')
    for path in sorted(args.directory.rglob('*.jsonl')):
        try:
            result = read_run(path, args.output)
            if result:
                runs.append(result)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            warnings.append(f'{path.name}: {exc}')
    template = Path(__file__).with_name('dashboard.html').read_text()
    data = json.dumps(dict(runs=runs, warnings=warnings), allow_nan=False).replace('<', '\\u003c')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(template.replace('__BENCHMARK_DATA__', data), encoding='utf-8')
    print(f'{args.output.resolve()} ({len(runs)} runs, {len(warnings)} unreadable logs)')


if __name__ == '__main__':
    main()
