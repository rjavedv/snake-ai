import json
import tempfile
import unittest
from unittest.mock import patch

from snake_ai.engine import Game
from snake_ai.ai import SessionLog, choose_move, decide, payload


class RulesTests(unittest.TestCase):
    def test_reverse_continues_forward(self):
        game = Game(seed=1)
        x, y = game.snake[0]
        game.step("LEFT")
        self.assertEqual(game.snake[0], (x + 1, y))

    def test_wall_move_is_fatal(self):
        game = Game()
        game.snake = [(23, 4), (22, 4), (21, 4)]
        game.step("RIGHT")
        self.assertEqual(game.outcome, "wall_collision")

    def test_food_growth(self):
        game = Game(seed=1)
        game.food = (13, 9)
        game.step("RIGHT")
        self.assertEqual((game.score, len(game.snake)), (1, 4))
        self.assertNotIn(game.food, game.snake)

    def test_tail_cell_can_be_entered(self):
        game = Game()
        game.snake = [(2, 2), (2, 3), (1, 3), (1, 2)]
        game.direction = "UP"
        game.food = (8, 8)
        game.step("LEFT")
        self.assertIsNone(game.outcome)

    def test_self_collision(self):
        game = Game()
        game.snake = [(2, 2), (2, 3), (1, 3), (1, 2), (1, 1)]
        game.direction = "UP"
        game.step("LEFT")
        self.assertEqual(game.outcome, "self_collision")

    def test_full_board_wins(self):
        game = Game(4, 1)
        game.snake = [(2, 0), (1, 0), (0, 0)]
        game.food = (3, 0)
        game.step("RIGHT")
        self.assertEqual(game.outcome, "won")


class ModelTests(unittest.TestCase):
    def test_highest_probability(self):
        response = {"answers": {"move": {"choice": "UP", "probabilities": {
            "UP": .1, "DOWN": .2, "RIGHT": .7}}}}
        self.assertEqual(choose_move(response, ["UP", "DOWN", "RIGHT"]), "RIGHT")

    def test_invalid_response_rejected(self):
        with self.assertRaises(ValueError):
            choose_move({"answers": {"move": {"probabilities": {"UP": 1}}}}, ["UP", "DOWN", "RIGHT"])

    def test_transport_and_logs(self):
        response = {"answers": {"move": {"probabilities": {
            "UP": .1, "DOWN": .2, "RIGHT": .7}}}}
        with tempfile.TemporaryDirectory() as directory:
            log = SessionLog(directory)
            with patch("snake_ai.ai.urlopen") as transport:
                transport.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
                self.assertEqual(decide("test", Game().state(), "http://localhost:11434", 3, log), "RIGHT")
                request = transport.call_args.args[0]
                self.assertTrue(request.full_url.endswith("/v1/systemone"))
                self.assertEqual(json.loads(request.data)["model"], "test")
            records = [json.loads(line) for line in log.path.read_text().splitlines()]
            self.assertEqual([r["event"] for r in records], ["request", "response"])
            self.assertEqual(json.loads(records[1]["raw"]), response)

    def test_reverse_excluded_for_every_heading(self):
        opposites = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
        for heading, reverse in opposites.items():
            game = Game()
            game.direction = heading
            state = game.state()
            criteria = payload("test", state)["questions"]["move"]["criteria"]
            self.assertEqual(len(criteria), 3)
            self.assertNotIn(reverse, criteria)
            self.assertEqual(set(criteria), set(state["allowed_directions"]))

    def test_bottom_edge_still_offers_fatal_forward_move(self):
        game = Game()
        game.direction = "DOWN"
        game.snake = [(9, 17), (9, 16), (9, 15), (9, 14)]
        criteria = payload("test", game.state())["questions"]["move"]["criteria"]
        self.assertEqual(set(criteria), {"LEFT", "RIGHT", "DOWN"})
        with self.assertRaises(ValueError):
            choose_move({"answers": {"move": {"probabilities": {
                "UP": .72, "DOWN": .09, "LEFT": .09, "RIGHT": .10}}}}, criteria)
        game.step("DOWN")
        self.assertEqual(game.outcome, "wall_collision")

    def test_network_error_is_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            log = SessionLog(directory)
            with patch("snake_ai.ai.urlopen", side_effect=TimeoutError("timed out")):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    decide("test", Game().state(), "http://localhost:11434", 3, log)
            self.assertEqual(json.loads(log.path.read_text().splitlines()[-1])["event"], "error")


if __name__ == "__main__":
    unittest.main()
