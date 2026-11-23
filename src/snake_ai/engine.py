"""Grid-based Snake rules, independent of the display and model."""
import random

DIRECTIONS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
OPPOSITE = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}


class Game:
    def __init__(self, width=24, height=18, seed=None):
        self.width, self.height = width, height
        self.rng = random.Random(seed)
        x, y = width // 2, height // 2
        self.snake = [(x, y), (x - 1, y), (x - 2, y)]
        self.direction = "RIGHT"
        self.score = self.steps = 0
        self.outcome = None
        self.food = self.spawn_food()

    def spawn_food(self):
        empty = [(x, y) for y in range(self.height) for x in range(self.width)
                 if (x, y) not in self.snake]
        return self.rng.choice(empty) if empty else None

    def state(self):
        return {"board": {"width": self.width, "height": self.height},
                "coordinates": "[x,y], origin top-left; x increases right, y increases down",
                "snake": [list(p) for p in self.snake], "snake_order": "head first",
                "direction": self.direction,
                "allowed_directions": [key for key in DIRECTIONS if key != OPPOSITE[self.direction]],
                "food": [list(self.food)] if self.food else [],
                "walls": {"left": -1, "right": self.width, "top": -1, "bottom": self.height},
                "score": self.score, "step": self.steps, "outcome": self.outcome}

    def step(self, requested):
        if self.outcome:
            raise ValueError("Game is already over")
        if requested not in DIRECTIONS:
            raise ValueError("Unknown direction")
        if requested != OPPOSITE[self.direction]:
            self.direction = requested
        dx, dy = DIRECTIONS[self.direction]
        head = (self.snake[0][0] + dx, self.snake[0][1] + dy)
        eating = head == self.food
        body = self.snake if eating else self.snake[:-1]
        self.steps += 1
        if not (0 <= head[0] < self.width and 0 <= head[1] < self.height):
            self.outcome = "wall_collision"
        elif head in body:
            self.outcome = "self_collision"
        self.snake.insert(0, head)
        if not eating:
            self.snake.pop()
        if eating:
            self.score += 1
            self.food = self.spawn_food()
            if self.food is None:
                self.outcome = "won"
        return self.direction
