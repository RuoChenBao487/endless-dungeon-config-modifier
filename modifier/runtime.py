"""Bootstrap that applies session-only patches before the game starts."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import threading
from types import ModuleType
from typing import Any

from .config import ModifierConfig, load_config


class RuntimeState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._config = load_config(self.path)
        self._mtime = self._file_mtime()

    def _file_mtime(self) -> int:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return -1

    def current(self) -> ModifierConfig:
        with self._lock:
            return self._config

    def poll(self) -> ModifierConfig | None:
        mtime = self._file_mtime()
        if mtime == self._mtime:
            return None
        with self._lock:
            self._config = load_config(self.path)
            self._mtime = mtime
            return self._config

    def start(self, on_change=None) -> None:
        def watch() -> None:
            while not self._stop.wait(0.25):
                changed = self.poll()
                if changed is not None and on_change is not None:
                    try:
                        on_change(changed)
                    except Exception:
                        pass

        threading.Thread(
            target=watch,
            name="modifier-config-watcher",
            daemon=True,
        ).start()

    def stop(self) -> None:
        self._stop.set()


def _scale_health(target: Any, factor: float) -> None:
    if abs(factor - 1.0) < 0.0001:
        return
    old_max = max(1.0, float(getattr(target, "max_health", 1.0)))
    old_health = float(getattr(target, "health", old_max))
    ratio = old_health / old_max
    if hasattr(target, "base_health"):
        target.base_health = max(1, int(round(float(target.base_health) * factor)))
    target.max_health = max(1, int(round(old_max * factor)))
    target.health = max(0.0, min(float(target.max_health),
                                 float(target.max_health) * ratio))


def _patch_constructor(
    cls: Any,
    state: RuntimeState,
    factor_name: str,
) -> None:
    original = cls.__init__
    if getattr(original, "_dungeon_modifier_patched", False):
        return

    def patched(self, *args, **kwargs):
        original(self, *args, **kwargs)
        _scale_health(self, float(getattr(state.current(), factor_name)))

    patched._dungeon_modifier_patched = True
    cls.__init__ = patched


def _patch_player(
    player_cls: Any,
    state: RuntimeState,
) -> None:
    original_init = player_cls.__init__
    if not getattr(original_init, "_dungeon_modifier_patched", False):
        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            factor = float(state.current().player_max_health_multiplier)
            if abs(factor - 1.0) >= 0.0001:
                self.max_health = max(1, int(round(self.max_health * factor)))
                self.health = self.max_health

        patched_init._dungeon_modifier_patched = True
        player_cls.__init__ = patched_init

    attack_property = player_cls.attack_damage
    if not getattr(attack_property.fget, "_dungeon_modifier_patched", False):
        original_attack = attack_property.fget

        def modified_attack(self):
            return original_attack(self) * float(
                state.current().player_attack_multiplier)

        modified_attack._dungeon_modifier_patched = True
        player_cls.attack_damage = property(modified_attack)

    speed_property = player_cls.speed
    if not getattr(speed_property.fget, "_dungeon_modifier_patched", False):
        original_speed = speed_property.fget

        def modified_speed(self):
            return original_speed(self) * float(
                state.current().player_speed_multiplier)

        modified_speed._dungeon_modifier_patched = True
        player_cls.speed = property(modified_speed)

    original_take_damage = player_cls.take_damage
    if not getattr(original_take_damage, "_dungeon_modifier_patched", False):
        def modified_take_damage(self, damage, *args, **kwargs):
            factor = float(state.current().incoming_damage_multiplier)
            return original_take_damage(self, float(damage) * factor, *args, **kwargs)

        modified_take_damage._dungeon_modifier_patched = True
        player_cls.take_damage = modified_take_damage

    original_true_damage = player_cls.take_true_damage
    if not getattr(original_true_damage, "_dungeon_modifier_patched", False):
        def modified_true_damage(self, damage, *args, **kwargs):
            factor = float(state.current().incoming_damage_multiplier)
            return original_true_damage(
                self, float(damage) * factor, *args, **kwargs)

        modified_true_damage._dungeon_modifier_patched = True
        player_cls.take_true_damage = modified_true_damage


def _patch_game_core(core_cls: Any, state: RuntimeState) -> None:
    original = core_cls.__init__
    if getattr(original, "_dungeon_modifier_patched", False):
        return

    def patched(self, *args, **kwargs):
        original(self, *args, **kwargs)
        config = state.current()
        self.player.crystals = max(
            0, int(self.player.crystals) + int(config.extra_start_crystals))
        self.player.bombs = max(
            0, int(self.player.bombs) + int(config.extra_start_bombs))

    patched._dungeon_modifier_patched = True
    core_cls.__init__ = patched


def _patch_push(region_cls: Any, state: RuntimeState,
                base_push: float) -> None:
    original = region_cls.push_player
    if getattr(original, "_dungeon_modifier_patched", False):
        return

    def patched(self, direction, strength=None):
        base = base_push if strength is None else strength
        factor = float(state.current().blizzard_push_multiplier)
        return original(self, direction, base * factor)

    patched._dungeon_modifier_patched = True
    region_cls.push_player = patched


def _import_game_module(name: str) -> ModuleType:
    return importlib.import_module(name)


def _sync_constants(
    config: ModifierConfig,
    settings: ModuleType,
    props: ModuleType,
    regions: ModuleType,
    base_crystal_cooldown: int,
    base_crystal_damage: float,
) -> None:
    cooldown = max(
        1, int(round(base_crystal_cooldown * config.beacon_cooldown_multiplier)))
    damage = base_crystal_damage * config.beacon_damage_multiplier
    settings.CRYSTAL_COOLDOWN = cooldown
    settings.CRYSTAL_DAMAGE_RATE = damage
    props.CRYSTAL_COOLDOWN = cooldown
    regions.CRYSTAL_COOLDOWN = cooldown
    regions.CRYSTAL_DAMAGE_RATE = damage


def apply_runtime(
    game_dir: str | Path,
    config_path: str | Path,
    session_dir: str | Path,
) -> RuntimeState:
    game_path = Path(game_dir).resolve()
    session_path = Path(session_dir).resolve()
    session_path.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(game_path))

    settings = _import_game_module("dungeon.settings")
    if settings.VERSION != "16.0":
        raise RuntimeError(
            f"运行时补丁适配 16.0，当前目录版本为 {settings.VERSION}")

    save_module = _import_game_module("dungeon.save")
    save_module.default_path = lambda: session_path / "save_data.json"

    player_module = _import_game_module("dungeon.entities.player")
    enemies_module = _import_game_module("dungeon.entities.enemies")
    props_module = _import_game_module("dungeon.entities.props")
    boss_base_module = _import_game_module("dungeon.bosses.base")
    game_module = _import_game_module("dungeon.game")
    core_module = _import_game_module("dungeon.game.core")
    regions_module = _import_game_module("dungeon.game.regions")

    state = RuntimeState(config_path)
    config = state.current()
    base_crystal_cooldown = int(settings.CRYSTAL_COOLDOWN)
    base_crystal_damage = float(settings.CRYSTAL_DAMAGE_RATE)
    base_push = float(settings.BLIZZARD_PUSH)
    _sync_constants(
        config, settings, props_module, regions_module,
        base_crystal_cooldown, base_crystal_damage,
    )

    _patch_constructor(enemies_module.Enemy, state, "enemy_health_multiplier")
    _patch_constructor(
        enemies_module.EliteEnemy, state, "elite_health_multiplier")
    _patch_constructor(
        boss_base_module.BaseBoss, state, "boss_health_multiplier")
    _patch_constructor(
        enemies_module.EmberMinion, state, "enemy_health_multiplier")
    _patch_player(player_module.Player, state)
    _patch_game_core(core_module.GameCoreMixin, state)
    _patch_push(regions_module.GameRegionMixin, state, base_push)

    state.start(lambda changed: _sync_constants(
        changed, settings, props_module, regions_module,
        base_crystal_cooldown, base_crystal_damage,
    ))
    return state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--probe", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        state = apply_runtime(args.game_dir, args.config, args.session_dir)
        import pygame
        from dungeon import app
        from dungeon import save as save_module
        from dungeon import settings

        pygame.display.set_caption("无尽地牢2D版 · 修改模式")
        if args.dry_run:
            config = state.current()
            summary = {
                "game_version": "16.0",
                "save_path": str(save_module.default_path()),
                "session_dir": str(Path(args.session_dir).resolve()),
                "modifiers": config.as_dict(),
                "patches": [
                    "Enemy", "EliteEnemy", "BaseBoss", "EmberMinion",
                    "Player", "GameCoreMixin", "GameRegionMixin",
                ],
                "effective_constants": {
                    "crystal_cooldown": int(settings.CRYSTAL_COOLDOWN),
                    "crystal_damage_rate": float(settings.CRYSTAL_DAMAGE_RATE),
                },
            }
            if args.probe:
                from dungeon.bosses import create_boss
                from dungeon.data.biomes import BIOME_NORMAL
                from dungeon.data.bosses import BOSS_FALLEN_KNIGHT
                from dungeon.data.modes import MODE_CLASSIC
                from dungeon.entities.enemies import EliteEnemy, Enemy
                from dungeon.entities.player import Player
                from dungeon.game import Game

                player = Player()
                enemy = Enemy(100, 100, 10, 0, BIOME_NORMAL)
                elite = EliteEnemy(100, 100, 10, BIOME_NORMAL, "vampire")
                boss = create_boss(
                    BOSS_FALLEN_KNIGHT, 400, 570, 10, BIOME_NORMAL)
                damage_before = float(player.health)
                player.take_damage(10, source="probe")
                game = Game(MODE_CLASSIC)
                summary["probe"] = {
                    "player_max_health": player.max_health,
                    "player_attack": player.attack_damage,
                    "player_speed": player.speed,
                    "player_damage_taken": round(
                        damage_before - float(player.health), 4),
                    "enemy_max_health": enemy.max_health,
                    "elite_max_health": elite.max_health,
                    "boss_max_health": boss.max_health,
                    "start_crystals": game.player.crystals,
                    "start_bombs": game.player.bombs,
                }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            state.stop()
            pygame.quit()
            return 0

        try:
            app.main()
        finally:
            state.stop()
            pygame.quit()
        return 0
    except Exception as error:
        print(f"修改模式启动失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
