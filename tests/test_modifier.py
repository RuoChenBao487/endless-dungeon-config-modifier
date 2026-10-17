from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from modifier import launcher
from modifier.config import ModifierConfig, defaults, load_config, write_config
from modifier.runtime import RuntimeState


TOOL_ROOT = Path(__file__).resolve().parents[1]
GAME_ROOT = TOOL_ROOT.parent / "16.0"


class ModifierConfigTests(unittest.TestCase):
    def test_defaults_are_neutral(self):
        config = defaults()
        self.assertEqual(config.enemy_health_multiplier, 1.0)
        self.assertEqual(config.extra_start_crystals, 0)

    def test_values_are_clamped_and_typed(self):
        config = ModifierConfig(
            enemy_health_multiplier=-4,
            extra_start_crystals=20000,
            extra_start_bombs=3.8,
        ).validated()
        self.assertEqual(config.enemy_health_multiplier, 0.1)
        self.assertEqual(config.extra_start_crystals, 9999)
        self.assertEqual(config.extra_start_bombs, 4)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            expected = defaults().changed(
                enemy_health_multiplier=2.5,
                extra_start_crystals=75,
            )
            write_config(path, expected)
            self.assertEqual(load_config(path), expected)

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_config(path), defaults())


class LauncherTests(unittest.TestCase):
    def test_session_copies_saves_and_never_points_at_game_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "16.0"
            (game / "dungeon").mkdir(parents=True)
            (game / "dungeon" / "settings.py").write_text(
                'VERSION = "16.0"\n', encoding="utf-8")
            (game / "main.py").write_text("", encoding="utf-8")
            (game / "save_data.json").write_text('{"keep": true}\n',
                                                  encoding="utf-8")
            (game / "run_save.json").write_text('{"room": 7}\n',
                                                 encoding="utf-8")
            sessions = root / "sessions"
            fake_process = mock.Mock()
            fake_process.poll.return_value = None

            with mock.patch.object(launcher, "SESSION_ROOT", sessions), \
                    mock.patch.object(launcher, "_windowless_python",
                                      return_value=Path(sys.executable)), \
                    mock.patch.object(launcher.subprocess, "Popen",
                                      return_value=fake_process):
                managed = launcher.start_game(
                    game,
                    defaults().changed(extra_start_crystals=25),
                    inherit_saves=True,
                    preserve_session=True,
                )

            self.assertTrue(managed.config_path.is_file())
            self.assertEqual(
                json.loads((managed.session_dir / "save_data.json").read_text(
                    encoding="utf-8")),
                {"keep": True},
            )
            self.assertEqual(
                json.loads((game / "save_data.json").read_text(encoding="utf-8")),
                {"keep": True},
            )
            managed.close()
            launcher.cleanup_session(managed.session_dir)


class RuntimeStateTests(unittest.TestCase):
    def test_changed_session_file_is_reloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            write_config(path, defaults())
            state = RuntimeState(path)
            updated = defaults().changed(player_attack_multiplier=4.0)
            write_config(path, updated)

            self.assertEqual(state.poll(), updated)
            self.assertEqual(state.current(), updated)


@unittest.skipUnless(GAME_ROOT.is_dir(), "16.0 game directory is unavailable")
class RuntimeIntegrationTests(unittest.TestCase):
    def _run_probe(self, config: ModifierConfig):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            session = root / "session"
            write_config(config_path, config)
            env = os.environ.copy()
            env.update({
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
                "PYGAME_HIDE_SUPPORT_PROMPT": "1",
                "PYTHONIOENCODING": "utf-8",
            })
            result = subprocess.run(
                [
                    sys.executable, "-B", "-m", "modifier.runtime",
                    "--game-dir", str(GAME_ROOT),
                    "--config", str(config_path),
                    "--session-dir", str(session),
                    "--dry-run", "--probe",
                ],
                cwd=TOOL_ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = result.stdout[result.stdout.find("{"):]
            return json.loads(payload)

    def test_runtime_scales_real_16_0_entities(self):
        baseline = self._run_probe(defaults())
        modified = self._run_probe(defaults().changed(
            enemy_health_multiplier=2.5,
            elite_health_multiplier=3.0,
            boss_health_multiplier=4.0,
            player_max_health_multiplier=2.0,
            player_attack_multiplier=3.0,
            player_speed_multiplier=1.5,
            incoming_damage_multiplier=0.5,
            extra_start_crystals=75,
            extra_start_bombs=2,
        ))

        base_probe = baseline["probe"]
        mod_probe = modified["probe"]
        self.assertEqual(
            mod_probe["player_max_health"],
            base_probe["player_max_health"] * 2,
        )
        self.assertEqual(
            mod_probe["enemy_max_health"],
            round(base_probe["enemy_max_health"] * 2.5),
        )
        self.assertEqual(
            mod_probe["elite_max_health"],
            round(base_probe["elite_max_health"] * 3.0),
        )
        self.assertEqual(
            mod_probe["boss_max_health"],
            round(base_probe["boss_max_health"] * 4.0),
        )
        self.assertAlmostEqual(
            mod_probe["player_attack"],
            base_probe["player_attack"] * 3.0,
            places=4,
        )
        self.assertAlmostEqual(
            mod_probe["player_speed"],
            base_probe["player_speed"] * 1.5,
            places=4,
        )
        self.assertAlmostEqual(
            mod_probe["player_damage_taken"],
            base_probe["player_damage_taken"] * 0.5,
            places=4,
        )
        self.assertEqual(
            mod_probe["start_crystals"],
            base_probe["start_crystals"] + 75,
        )
        self.assertEqual(
            mod_probe["start_bombs"],
            base_probe["start_bombs"] + 2,
        )
        self.assertNotEqual(
            modified["save_path"],
            str(GAME_ROOT / "save_data.json"),
        )


if __name__ == "__main__":
    unittest.main()
