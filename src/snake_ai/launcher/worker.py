"""Subprocess bridge: reuse the utilities without sharing Tk's event loop."""
import json
import os
import sys

from ..config import SETTINGS, load_configuration


def apply_settings(values):
    # GUI values take priority for this process only, never rewriting .config.
    for key, value in values.items():
        if key not in SETTINGS:
            raise ValueError(f"Unsupported setting: {key}")
        os.environ[key] = str(value)


def main():
    request = json.load(sys.stdin)
    load_configuration()
    apply_settings(request.get('settings', {}))
    action = request['action']
    if action == 'play':
        from ..app import main as play
        play(load_config=False, initial_mode=request['mode'], exit_on_escape=True)
    elif action == 'benchmark':
        from ..benchmark import main as benchmark
        sys.argv = ['snake-ai-benchmark', *request['arguments']]
        benchmark(load_config=False)
    elif action == 'replay':
        from ..replay import main as replay
        sys.argv = ['snake-ai-replay', request['path']]
        replay()
    elif action == 'dashboard':
        from ..dashboard import main as dashboard
        sys.argv = ['snake-ai-dashboard', *request['arguments']]
        dashboard()
    else:
        raise ValueError(f'Unknown activity: {action}')


if __name__ == '__main__':
    main()
