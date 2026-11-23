# Snake AI

Pygame Snake with human play and local Ollama decision models. Requires Python 3.12+ and uv.

## Run

### Desktop control panel

```sh
uv sync
uv run snake-ai-launcher
```

Run from the project folder so the launcher can find `.config`, `.env`, and
`scenarios/`. Python must include Tkinter (the same requirement as replay).
The launcher provides four tabs:

- **Play:** choose human or AI, provider, editable model name, and speed. The
  Pygame window opens separately; **Esc** closes it and restores the launcher.
- **Replay:** browse for a JSONL log and open the existing board/JSON viewer.
  Closing the viewer restores the launcher.
- **Benchmark:** select scenarios (use Command/Ctrl or Shift for multiple),
  optionally add scenario files, enter models one per line, and choose repeats
  and an output folder. A blank model list uses the shared model field.
  Models in a batch use the selected provider. Completed runs appear in the
  activity output; Ollama models are unloaded between models as in the CLI.
- **Results:** generate the HTML dashboard from a benchmark log folder, then
  click its file link to open it with the OS default HTML application.

Provider, model, timeout, log folder, and speed defaults come from `.config`.
Switching provider remembers each provider's model field. Server URLs come from
`.config`; OpenRouter credentials come from `.env` or the exported environment.
Changes in the launcher apply only to the next activity and never rewrite these
files. Settings and output remain visible when an activity finishes.

The launcher runs one activity at a time. Benchmarks and report generation leave
it responsive. **Stop activity** ends the running process; completed benchmark
logs remain usable, but the active log may lack its final records, and forced
stopping does not perform the benchmark's normal Ollama unload step.

The interface and subprocess bridge live in `src/snake_ai/launcher/`. Existing
command-line entry points remain available; game rules, AI requests, replay,
and dashboard generation are reused.

### Standalone game

```sh
uv sync
uv run snake-ai
```

Press **H** for human play or **A** for AI play. Arrow keys control the human snake.
**Esc** returns to the menu (or quits from the menu). After a loss or AI error,
**R** returns to mode selection to start a fresh game.

## Configuration

Game and provider settings live in shareable `.config`; `.config.example` is the
template. The private `.env` contains only `OPENROUTER_API_KEY`; `.env.example`
is its blank template. Edit `.config` before launching:

```dotenv
LOCAL_AI_MODEL_NAME=tev1:4b-mlx-bf16
OLLAMA_BASE_URL=http://localhost:11434
AI_TIMEOUT_SECONDS=120
AI_LOG_DIR=logs
GAME_SPEED=0
```

`GAME_SPEED` accepts integers, clamped to -10 through 10. Restart the app after
changing it. Zero preserves the original pace. Human play moves every 125 ms at
0, 500 ms at -10, and 31.25 ms at 10; each five levels doubles or halves the
speed. Try `GAME_SPEED=-5` for a gentler pace (250 ms per human move).
AI play adds the slowdown above the original 125 ms baseline between requests
(for example, 375 ms extra at -10). At 0 and positive values, AI already runs as
fast as responses arrive, so positive values cannot accelerate model inference.
Every AI move still waits for its response. Invalid non-integer values produce
a clear startup error.

Supported installed choices are `kev:27b-nvfp4`, `clef-flash:9b-mxfp8`, and
`tev1:4b-mlx-bf16`. Start Ollama before AI play. Configuration is read from the
current working directory on launch; existing values in `.config` take priority over existing environment settings. An exported
`OPENROUTER_API_KEY` takes priority over the key in `.env`. Only the key is read
from `.env`, and only recognized non-secret settings are read from `.config`.

These are decision models: the client uses Ollama's `/v1/systemone` endpoint,
not chat generation. See the [model API documentation](https://ollama.com/library/clef-flash).
The three non-reversing directions are supplied as choices, and the state includes
`allowed_directions`. The opposite direction is excluded before asking the model. The highest returned probability wins;
ties use UP, DOWN, LEFT, RIGHT order. Forward or sideways moves into walls or the body remain available for evaluation.
Responses containing unexpected or missing choices stop the run as an AI error.
Opposite-direction keys follow standard Snake rules: ignored, continuing forward.
The requested key and actual direction are both logged. Human and AI share the
same movement rules. Food never spawns on the snake; filling the board wins.

AI play waits for one response per cell movement, while the window remains responsive.
Network failures, timeouts, and malformed responses stop the run without a fallback
move. Error details appear in the terminal and session log.

## Evaluation logs

Each AI game creates a unique `logs/ai-<UTC timestamp>-<id>.jsonl` file.
Each line is a JSON record with a UTC timestamp and event:

- `session_start`: model and initial board.
- `request`: step, endpoint, and exact JSON request, including state and question.
- `response`: raw response body (including probabilities and usage) and elapsed seconds.
- `transition`: requested arrow key, applied direction, resulting state and outcome.
- `game_over`: final state after collision or victory.
- `error`: transport or response-validation error.
- `session_end`: final state and exit/restart reason.

Records are appended and flushed after each event. A request already in flight when
leaving a game may append its response afterward; it will never move a new game.
Closing the application may interrupt that pending request. `.env` and logs are ignored by Git.

## Checks

```sh
uv run python -m unittest discover -s tests -v
```

## Visualize a log

```sh
uv run snake-ai-replay
```

Select a `.jsonl` file in the file picker. Alternatively, supply its path:

```sh
uv run snake-ai-replay logs/your-log.jsonl
```

The board window shows the selected **physical file row number**, event, score,
step, direction, and outcome. **Down** selects the next row; **Up** selects the
previous row. Navigation stops at the first and last rows. These keys work from
either window, including while the JSON text has focus. Buttons offer the same
controls. **Esc** closes the viewer; **Open log** selects another file.

The second window displays the complete selected row as indented JSON with
scrollbars. Its **Decoded response** tab separately formats the JSON encoded
inside a response row's `raw` string without changing the original row display.

Session starts use `initial_state`, requests use `payload.state`, and transitions
and final events use `state`. Rows without a state retain the latest preceding
state; the board identifies which row supplied it. Navigating backward restores
that row's state rather than keeping a later move. No moves are simulated and
no model requests are made. Logs are never modified.

Board dimensions and coordinates come directly from the log. Because logs do not
record original pixel dimensions, the viewer uses 30-pixel cells and a one-cell
margin to show fatal out-of-bounds positions in red. Files with malformed JSON,
blank lines, or invalid board states report the offending row rather than silently
skipping it. A file beginning without a state displays a clear message until a
state is encountered. The viewer reads a snapshot of the file when opened.

This utility uses Python's Tkinter GUI library (available in the project's current
Python installation). A Python build with Tk support is required.

## Switch between Ollama and OpenRouter

Select the provider in `.config`, then restart the app:

```dotenv
AI_PROVIDER=openrouter
OPENROUTER_MODEL_NAME=typesafe/jev-1.14
OPENROUTER_BASE_URL=https://openrouter.ai/api
```

Keep `OPENROUTER_API_KEY=your-key` separately in your private `.env`.

To return to local play, set `AI_PROVIDER=ollama`. If `AI_PROVIDER` is absent,
Ollama remains the default. `LOCAL_AI_MODEL_NAME` and `OLLAMA_BASE_URL` still
configure local inference. OpenRouter uses `OPENROUTER_MODEL_NAME` (default:
`typesafe/jev-1.14`) and the existing `OPENROUTER_API_KEY`.

Both providers use the same System One payload, non-reversing choices, highest
probability selection, timeout, and game rules. OpenRouter requests go to
`<OPENROUTER_BASE_URL>/v1/systemone` (default: `https://openrouter.ai/api/v1/systemone`) with Bearer authentication, as documented
in [OpenRouter's System One guide](https://openrouter.ai/docs/guides/community/typesafe-sdk).
Restart after editing either file. `.config` may be committed and shared; `.env`
remains ignored by Git. Never put API keys into `.config`.

This integration is for decision models, not ordinary chat models.

Session starts and request/response records identify the provider. Raw responses
retain probability and usage/cost information for evaluation; existing replay
works with both providers. Authorization headers are never logged. Missing keys,
invalid provider settings, HTTP errors, and malformed model answers report errors
without falling back to another provider or making automatic retry requests.
Cloud calls use your OpenRouter balance. Human play does not require an API key.

## Reproducible benchmarks

Benchmark mode runs without a game window and uses saved JSON scenarios. It shares
normal Snake movement and provider decisions, but never chooses random food.
Normal human/AI play is unchanged.

```sh
uv sync
uv run snake-ai-benchmark scenarios/circuit-25.json --model tev1:4b-mlx-bf16 --model clef-flash:9b-mxfp8 --repeats 3
uv run snake-ai-dashboard
```

Open `logs/benchmark-dashboard.html` in a browser. It is an offline snapshot with
scenario selection, model completion rates, completion move averages/ranges,
individual outcomes, cumulative food progress, and moves for each food item.
Re-run the dashboard command after collecting new logs. No model calls are made
when generating or viewing reports. Raw logs are linked from the report; inspect
their boards with `uv run snake-ai-replay <log path>`.

Use `scenarios/circuit-50.json` for a 50-food target. Multiple scenario paths can
be supplied to one benchmark command. These are starter scenarios, not calibrated
measures of model quality. Define additional layouts to broaden evaluation.

Models use the provider, endpoint, key and timeout configured in `.config`/`.env`.
Without `--model`, the configured model is used. To compare across providers, run
each provider configuration separately into the same log directory; reports group
results by provider and model. Cloud benchmarks make real paid requests; repeats
multiply the number of games. There are no retries or fallback moves. Ctrl+C ends
the current run with an `interrupted` outcome and stops the batch.

For Ollama, all scenarios and repeats for one model run together. The benchmark
then sends `POST /api/generate` with an empty prompt and `keep_alive: 0`, and waits
for an unload acknowledgement before starting another model. Cleanup also runs
after model errors and Ctrl+C. If unloading fails or is not confirmed, the batch
stops with an error rather than loading the next model. The unload request uses
the configured Ollama URL and a timeout of at most 30 seconds. OpenRouter runs
do not send unload requests. Forced process termination cannot perform cleanup.

### Scenario format and rules

Each JSON scenario has `name`, positive integer `version`, `width`, `height`,
`snake` (head-first coordinates), `direction`, `food` (ordered coordinates),
`food_target`, and `move_limit`. See the supplied scenarios for complete examples.
The starting snake must be contiguous and point in the specified direction.
Coordinates must be inside the board; the sequence must cover the target count,
and the board must accommodate starting length plus target growth.

- The initial state and food coordinates are identical for every run of a scenario.
- Only one food item is active. Eating it advances the sequence.
- Occupied food targets wait without skipping. There is no active food until the
  target cell is free after a move; it becomes available for the following move.
  The pending coordinate and limits are included in the model's state.
- Eating the target number ends immediately as `scenario_completed`, including
  when this happens on the last allowed move or fills the board.
- Otherwise, reaching the move limit ends as `move_limit_reached`. Wall/self
  collisions take priority over the move limit. Provider failures end separately
  as `model_error`; they do not count as physical moves.
- All physical moves, including moves while food is pending, count toward the
  limit. Per-food moves count from the previous food (or the initial state).
  A waiting move is a move that begins without active food.

Logs contain the full scenario, a SHA-256 rules fingerprint, model/provider,
endpoint, timeout, repeat index, every decision and transition, food milestones,
and final summary. They remain compatible with the existing replay viewer.
Changing any scenario field creates a separate dashboard comparison group, even
if its name/version was left unchanged. Unfinished logs are shown as incomplete;
unreadable logs are listed explicitly in the report.

Completion moves are reported only for completed runs. Average moves per food
uses reached items only and excludes trailing moves after the last food. Missing
items are “Not reached,” never zero. Reports include recorded decision duration;
USD cost is shown only if every response supplies numeric `usage.cost`.

Optional paths:

```sh
uv run snake-ai-benchmark scenarios/circuit-25.json --output logs/my-benchmarks
uv run snake-ai-dashboard logs/my-benchmarks --output logs/my-report.html
```
