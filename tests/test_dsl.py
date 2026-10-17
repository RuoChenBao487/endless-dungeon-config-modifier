from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from dungeon_dsl.cli import main
from dungeon_dsl.compiler import compile_program
from dungeon_dsl.diagnostics import DslSyntaxError
from dungeon_dsl.parser import parse_source
from dungeon_dsl.simulator import simulate
from dungeon_dsl.validator import validate_program


VALID = """
version 1

catalog {
    biome tomb
    biome snow
    enemy skeleton
    enemy ghost
    enemy wind
    elite carrier scene tomb
    boss dragon scene tomb
}

room_rule combat { allow_nested true }
room_rule boss { allow_nested false }
room_rule event { allow_nested false }

region tomb {
    title "亡灵墓穴"
    length 3..5
    normal_gap 0.9
    normal_gap_step 0.1
    enemy_pool {
        skeleton weight 20
        ghost weight 10
    }
    nested church {
        chance 0.2
        extend 2
        once_per_region true
        allowed_room_rules [combat]
    }
}

region snow {
    title "暴雪山脉"
    length 3..5
    enemy_pool {
        wind weight 20
    }
}

nested temple {
    parent snow
    chance 0.25
    extend 3
    once_per_region true
    allowed_room_rules [combat]
}
"""


def parse_valid(source=VALID):
    return parse_source(source, "valid.dungeon")


def errors(source):
    return validate_program(parse_source(source, "invalid.dungeon")).errors


class ParserAndCompilerTests(unittest.TestCase):
    def test_region_allows_multiple_nested_blocks(self):
        program = parse_source(
            """
version 1
catalog { biome tomb }
room_rule combat { allow_nested true }
region tomb {
    length 3..5
    enemy_pool { skeleton weight 1 }
    nested church {
        chance 0.2
        allowed_room_rules [combat]
    }
    nested great_tomb {
        chance 0.2
        allowed_room_rules [combat]
    }
}
"""
        )

        self.assertEqual(
            [room.name for room in program.regions[0].nested],
            ["church", "great_tomb"],
        )

    def test_parses_expected_structure(self):
        program = parse_valid()
        self.assertEqual(program.version, 1)
        self.assertEqual(len(program.regions), 2)
        self.assertEqual(len(program.all_nested), 2)
        self.assertEqual([rule.name for rule in program.room_rules],
                         ["combat", "boss", "event"])

    def test_compile_normalizes_top_level_nested_parent(self):
        config = compile_program(parse_valid())
        self.assertIn("temple", config["regions"]["snow"]["nested"])
        self.assertEqual(config["nested_rooms"]["temple"]["parent"], "snow")
        self.assertEqual(config["catalog"]["elites"]["carrier"]["scene"], "tomb")

    def test_syntax_error_has_location(self):
        with self.assertRaises(DslSyntaxError) as context:
            parse_source("version 1\nregion tomb { length 3 }", "bad.dungeon")
        self.assertGreaterEqual(context.exception.location.line, 2)


class ValidatorTests(unittest.TestCase):
    def test_valid_program_has_no_errors(self):
        self.assertEqual(errors(VALID), [])

    def test_top_level_nested_counts_as_region_child(self):
        diagnostics = validate_program(parse_valid())
        warning_codes = [item.code for item in diagnostics.warnings]
        self.assertNotIn("W304", warning_codes)

    def test_unknown_enemy(self):
        source = VALID.replace("ghost weight 10", "zombi weight 10")
        codes = [item.code for item in errors(source)]
        self.assertIn("E201", codes)

    def test_duplicate_region(self):
        source = VALID + "\nregion tomb { length 3..5 }\n"
        self.assertIn("E200", [item.code for item in errors(source)])

    def test_invalid_region_length(self):
        source = VALID.replace("length 3..5", "length 6..3", 1)
        self.assertIn("E202", [item.code for item in errors(source)])

    def test_invalid_chance(self):
        source = VALID.replace("chance 0.2", "chance 1.5")
        self.assertIn("E214", [item.code for item in errors(source)])

    def test_unknown_room_rule(self):
        source = VALID.replace("allowed_room_rules [combat]", "allowed_room_rules [missing]", 1)
        self.assertIn("E217", [item.code for item in errors(source)])

    def test_room_rule_can_forbid_nested(self):
        source = VALID.replace("allowed_room_rules [combat]", "allowed_room_rules [boss]", 1)
        self.assertIn("E218", [item.code for item in errors(source)])

    def test_missing_nested_parent(self):
        source = VALID.replace("parent snow\n", "")
        self.assertIn("E211", [item.code for item in errors(source)])

    def test_duplicate_catalog_symbol(self):
        source = VALID.replace("enemy skeleton", "enemy skeleton\n    enemy skeleton")
        self.assertIn("E101", [item.code for item in errors(source)])


class SimulatorTests(unittest.TestCase):
    def test_simulation_is_deterministic(self):
        config = compile_program(parse_valid())
        first = simulate(config, rooms=20000, seed=123)
        second = simulate(config, rooms=20000, seed=123)
        self.assertEqual(first, second)
        self.assertEqual(first["once_per_region_violations"], 0)
        self.assertEqual(first["simulated_rooms"], 20000)

    def test_nested_room_is_sampled(self):
        config = compile_program(parse_valid())
        result = simulate(config, rooms=50000, seed=7)
        self.assertGreater(result["nested_counts"].get("church", 0), 0)
        self.assertGreater(result["nested_counts"].get("temple", 0), 0)

    def test_first_room_after_region_is_always_normal(self):
        config = {
            "regions": {
                "tomb": {
                    "length": [1, 1],
                    "normal_gap": 0.0,
                    "normal_gap_step": 0.1,
                    "enemy_pool": {"skeleton": 1.0},
                    "nested": [],
                }
            },
            "nested_rooms": {},
        }

        result = simulate(config, rooms=6, seed=1)

        self.assertEqual(result["region_rooms"], 3)
        self.assertEqual(result["normal_rooms"], 3)
        self.assertEqual(result["completed_regions"], 3)


class CliTests(unittest.TestCase):
    def test_example_passes_check(self):
        root = Path(__file__).resolve().parents[1]
        output = StringIO()
        errors_output = StringIO()
        with redirect_stdout(output), redirect_stderr(errors_output):
            code = main(["check", str(root / "examples" / "world.dungeon")])
        self.assertEqual(code, 0, errors_output.getvalue())
        self.assertIn("检查通过", output.getvalue())

    def test_compile_writes_json(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "world.json"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = main([
                    "compile",
                    str(root / "examples" / "world.dungeon"),
                    "-o",
                    str(target),
                ])
            self.assertEqual(code, 0)
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("tomb", data["regions"])


if __name__ == "__main__":
    unittest.main()
