"""Fixed-scenario Snake benchmarks; no display or model calls during reporting."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from .ai import AISettings, SessionLog, decide
from .config import load_configuration
from .engine import DIRECTIONS, Game


@dataclass(frozen=True)
class Scenario:
    name: str
    version: int
    width: int
    height: int
    snake: tuple
    direction: str
    food: tuple
    food_target: int
    move_limit: int

    @classmethod
    def from_dict(cls, data):
        def integer(key, low, high):
            value = data[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{key} must be an integer from {low} to {high}')
            return value
        width, height = integer('width', 1, 200), integer('height', 1, 200)
        def points(key):
            values = data[key]
            if not isinstance(values, list) or not values:
                raise ValueError(f'{key} must be a nonempty coordinate list')
            for p in values:
                if (not isinstance(p, list) or len(p) != 2 or
                    any(type(v) is not int for v in p) or
                    not (0 <= p[0] < width and 0 <= p[1] < height)):
                    raise ValueError(f'Invalid {key} coordinate: {p}')
            return tuple(tuple(p) for p in values)
        snake, food = points('snake'), points('food')
        if len(set(snake)) != len(snake):
            raise ValueError('Starting snake contains duplicate cells')
        if any(abs(a[0]-b[0]) + abs(a[1]-b[1]) != 1 for a, b in zip(snake, snake[1:])):
            raise ValueError('Starting snake must be contiguous, head first')
        direction = data['direction']
        if direction not in DIRECTIONS:
            raise ValueError('Invalid starting direction')
        if len(snake) > 1:
            dx, dy = DIRECTIONS[direction]
            if (snake[0][0]-snake[1][0], snake[0][1]-snake[1][1]) != (dx, dy):
                raise ValueError('Starting direction must point away from the neck')
        target = integer('food_target', 1, width * height)
        if len(food) < target or len(snake) + target > width * height:
            raise ValueError('Food sequence is too short or target growth exceeds board capacity')
        if not isinstance(data['name'], str) or not data['name'].strip():
            raise ValueError('Scenario name must be nonempty')
        return cls(data['name'], integer('version', 1, 1000000), width, height,
                   snake, direction, food, target, integer('move_limit', 1, 100000000))

    def as_dict(self):
        return dict(name=self.name, version=self.version, width=self.width, height=self.height,
                    snake=[list(p) for p in self.snake], direction=self.direction,
                    food=[list(p) for p in self.food], food_target=self.food_target,
                    move_limit=self.move_limit)

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()


class BenchmarkGame(Game):
    def __init__(self, scenario):
        self.scenario = scenario
        super().__init__(scenario.width, scenario.height)
        self.snake = list(scenario.snake)
        self.direction = scenario.direction
        self.food = self.spawn_food()
        self.waiting_moves = 0
        self.food_events = []
        self.last_food_step = self.last_waiting_moves = 0

    def spawn_food(self):
        if self.score >= self.scenario.food_target:
            return None
        point = self.scenario.food[self.score]
        return point if point not in self.snake else None

    def state(self):
        state = super().state()
        state['benchmark'] = dict(food_target=self.scenario.food_target,
                                  move_limit=self.scenario.move_limit,
                                  waiting_for_food=self.food is None and self.outcome is None,
                                  pending_food=list(self.scenario.food[self.score])
                                  if self.food is None and self.score < self.scenario.food_target else None)
        return state

    def step(self, requested):
        # Count only valid physical moves; activation happens after the tail vacates.
        waiting = self.food is None
        previous_score = self.score
        applied = super().step(requested)
        self.waiting_moves += int(waiting)
        if self.score != previous_score:
            self.food_events.append(dict(item=self.score, coordinate=list(self.scenario.food[self.score-1]),
                                         step=self.steps, moves=self.steps-self.last_food_step,
                                         waiting_moves=self.waiting_moves-self.last_waiting_moves))
            self.last_food_step, self.last_waiting_moves = self.steps, self.waiting_moves
            # Base Snake interprets no food as a full board; here it can be pending.
            if self.outcome == 'won':
                self.outcome = 'scenario_completed' if self.score == self.scenario.food_target else None
        if self.outcome is None:
            self.food = self.spawn_food()
            if self.steps >= self.scenario.move_limit:
                self.outcome = 'move_limit_reached'
        return applied


def run(scenario, settings, directory, timeout=120, repeat=1, decision=decide):
    settings.validate()
    game = BenchmarkGame(scenario)
    log = SessionLog(directory)
    log.write('session_start', model=settings.model, provider=settings.provider,
              endpoint=settings.base_url, timeout_seconds=timeout, initial_state=game.state(),
              benchmark=dict(schema_version=1, scenario=scenario.as_dict(),
                             fingerprint=scenario.fingerprint, repeat=repeat))
    try:
        while game.outcome is None:
            move = decision(settings.model, game.state(), settings.base_url, timeout, log,
                            provider=settings.provider, api_key=settings.api_key)
            previous_score = game.score
            applied = game.step(move)
            log.write('transition', requested_key=move, applied_direction=applied, state=game.state())
            if game.score > previous_score:
                log.write('food_eaten', **game.food_events[-1])
    except KeyboardInterrupt:
        game.outcome = 'interrupted'
    except Exception as exc:
        game.outcome = 'model_error'
        message = str(exc).replace(settings.api_key, '[REDACTED]') if settings.api_key else str(exc)
        log.write('error', error=message, step=game.steps)
    log.write('game_over', state=game.state())
    log.write('session_end', reason=game.outcome, state=game.state(),
              summary=dict(food_eaten=game.score, food_target=scenario.food_target,
                           total_moves=game.steps,
                           moves_to_completion=game.steps if game.outcome == 'scenario_completed' else None,
                           waiting_moves=game.waiting_moves, food_events=game.food_events))
    return log.path, game.outcome



def unload_ollama(settings, timeout=30):
    """Wait for Ollama to acknowledge unloading before another model can start."""
    request = Request(settings.base_url.rstrip('/') + '/api/generate',
                      data=json.dumps(dict(model=settings.model, prompt='', keep_alive=0,
                                           stream=False)).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read())
    if result.get('done') is not True or result.get('done_reason') != 'unload':
        raise RuntimeError('Ollama did not confirm that the model was unloaded')


def main(*, load_config=True):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenarios', nargs='+', type=Path)
    parser.add_argument('--model', action='append', help='Repeat to compare models on the configured provider')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--output', type=Path, default=Path('logs/benchmarks'))
    args = parser.parse_args()
    if load_config:
        load_configuration()
    try:
        scenarios = [Scenario.from_dict(json.loads(p.read_text())) for p in args.scenarios]
        base = AISettings.from_env()
        settings = [AISettings(base.provider, model, base.base_url, base.api_key)
                    for model in (args.model or [base.model])]
        timeout = float(os.getenv('AI_TIMEOUT_SECONDS', '120'))
        if args.repeats < 1 or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError('Repeats must be positive; timeout must be between 0 and 3600 seconds')
        for setting in settings:
            setting.validate()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    # Keep repeats and scenarios together so only one benchmark model is resident.
    for setting in settings:
        try:
            for scenario in scenarios:
                for repeat in range(1, args.repeats+1):
                    path, outcome = run(scenario, setting, args.output, timeout, repeat)
                    print(f'{scenario.name} | {setting.provider}/{setting.model} | {outcome} | {path}', flush=True)
                    if outcome == 'interrupted':
                        return
        finally:
            if setting.provider == 'ollama':
                print(f'Unloading Ollama model: {setting.model}', flush=True)
                try:
                    unload_ollama(setting, min(timeout, 30))
                except Exception as exc:
                    print(f'Could not confirm unloading {setting.model}: {exc}. '
                          'Stopping the benchmark batch before loading another model.', file=sys.stderr)
                    raise SystemExit(1) from None
                print(f'Unloaded Ollama model: {setting.model}', flush=True)


if __name__ == '__main__':
    main()
