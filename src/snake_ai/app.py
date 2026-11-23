"""Responsive Pygame interface. In AI mode only completed decisions advance time."""
import os
import queue
import threading

import pygame

from .ai import AISettings, SessionLog, decide
from .engine import Game
from .config import load_configuration

CELL, TOP = 30, 130
BG, GRID, TEXT = (15, 23, 36), (25, 37, 52), (224, 234, 244)
GREEN, FOOD = (69, 214, 156), (255, 115, 115)
KEYS = {pygame.K_UP: "UP", pygame.K_DOWN: "DOWN", pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT"}


def speed_settings(value):
    """Return clamped speed, human tick interval, and extra AI pacing delay."""
    try:
        speed = max(-10, min(10, int(value)))
    except ValueError:
        raise SystemExit("GAME_SPEED must be an integer (for example -5, 0, or 5).") from None
    interval = 125 * 2 ** (-speed / 5)
    return speed, interval, max(0, interval - 125)


def main(*, load_config=True, initial_mode=None, exit_on_escape=False):
    if load_config:
        load_configuration()
    speed, move_interval, ai_delay = speed_settings(os.getenv("GAME_SPEED", "0"))
    try:
        settings = AISettings.from_env()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    model, url = settings.model, settings.base_url
    try:
        timeout = float(os.getenv("AI_TIMEOUT_SECONDS", "120"))
        if not 0 < timeout <= 3600:
            raise ValueError
    except ValueError:
        raise SystemExit("AI_TIMEOUT_SECONDS must be a number between 0 and 3600.")
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((24 * CELL, 18 * CELL + TOP))
    pygame.display.set_caption("Snake | Human + AI")
    font = pygame.font.SysFont("Arial", 21)
    small = pygame.font.SysFont("Arial", 16)
    clock = pygame.time.Clock()
    game, mode, log = Game(), None, None
    pending, error, session, last_tick = False, "", 0, 0
    buffered = game.direction
    results = queue.Queue()
    running = True
    if initial_mode in ("human", "ai"):
        pygame.event.post(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_h if initial_mode == "human" else pygame.K_a))

    def finish(reason):
        if log:
            log.write("session_end", reason=reason, state=game.state())

    def worker(token, state, session_log):
        try:
            results.put((token, decide(model, state, url, timeout, session_log,
                                      provider=settings.provider, api_key=settings.api_key), None))
        except Exception as exc:
            results.put((token, None, str(exc)))

    try:
        while running:
            desired = None
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if mode is None or exit_on_escape:
                            running = False
                        else:
                            finish("returned_to_menu")
                            mode, log, pending = None, None, False
                            session += 1
                    elif mode is None and event.key in (pygame.K_h, pygame.K_a):
                        mode = "Human" if event.key == pygame.K_h else "AI"
                        game, error, pending = Game(), "", False
                        buffered = game.direction
                        session += 1
                        last_tick = pygame.time.get_ticks()
                        if mode == "AI":
                            try:
                                settings.validate()
                                log = SessionLog(os.getenv("AI_LOG_DIR", "logs"))
                                log.write("session_start", model=model, provider=settings.provider, game_speed=speed, initial_state=game.state())
                            except Exception as exc:
                                error = str(exc)
                    elif mode and event.key == pygame.K_r and (game.outcome or error):
                        finish("restart")
                        mode, log, pending = None, None, False
                        session += 1
                    elif mode == "Human" and event.key in KEYS and desired is None:
                        desired = KEYS[event.key]
            if not running:
                break
            if mode == "Human" and not game.outcome:
                if desired:
                    # Buffer one turn until the next game tick.
                    buffered = desired
                if pygame.time.get_ticks() - last_tick >= move_interval:
                    game.step(buffered)
                    buffered = game.direction
                    last_tick = pygame.time.get_ticks()
            while not results.empty():
                token, move, failure = results.get_nowait()
                if token != session or mode != "AI":
                    continue
                pending = False
                if failure:
                    error = failure
                else:
                    applied = game.step(move)
                    last_tick = pygame.time.get_ticks()
                    log.write("transition", requested_key=move, applied_direction=applied, state=game.state())
                    if game.outcome:
                        log.write("game_over", state=game.state())
            if (mode == "AI" and not pending and not error and not game.outcome
                    and (game.steps == 0 or pygame.time.get_ticks() - last_tick >= ai_delay)):
                pending = True
                threading.Thread(target=worker, args=(session, game.state(), log), daemon=True).start()
            screen.fill(BG)
            def text(value, y, color=TEXT, tiny=False):
                screen.blit((small if tiny else font).render(value, True, color), (20, y))
            text("SNAKE  /  " + (mode.upper() if mode else "CHOOSE A MODE"), 16, GREEN)
            if mode is None:
                text("H  Human play     A  AI play     Esc  Quit", 54)
                text("AI model: " + settings.provider + " / " + model, 88, tiny=True)
            else:
                text(f"Score {game.score}    Moves {game.steps}    Esc "
                     + ("Quit" if exit_on_escape else "Menu"), 48)
                status = "Arrow keys to move" if mode == "Human" else "Waiting for " + model
                if game.outcome:
                    status = game.outcome.replace("_", " ").title() + "  |  R Choose mode"
                elif error:
                    status = "AI error  |  R Choose mode  |  See terminal / log"
                text(status, 78, FOOD if error or game.outcome else TEXT, tiny=True)
                if mode == "AI" and log:
                    text("Log: " + str(log.path), 103, tiny=True)
                if error and error != getattr(main, "last_error", None):
                    print("AI error:", error)
                    main.last_error = error
            for y in range(game.height):
                for x in range(game.width):
                    pygame.draw.rect(screen, GRID, (x * CELL, TOP + y * CELL, CELL, CELL), 1)
            for i, (x, y) in enumerate(game.snake):
                if 0 <= x < game.width and 0 <= y < game.height:
                    pygame.draw.rect(screen, GREEN if i else (144, 255, 201),
                                     (x * CELL + 2, TOP + y * CELL + 2, CELL - 4, CELL - 4), border_radius=6)
            if game.food:
                x, y = game.food
                pygame.draw.circle(screen, FOOD, (x * CELL + CELL // 2, TOP + y * CELL + CELL // 2), 9)
            pygame.display.flip()
            clock.tick(60)
    finally:
        finish("window_closed")
        pygame.quit()
