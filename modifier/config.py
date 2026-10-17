"""Validated, session-only modifier choices."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class OptionSpec:
    key: str
    title: str
    minimum: float
    maximum: float
    step: float
    kind: str
    group: str
    scope: str


OPTION_SPECS = (
    OptionSpec("enemy_health_multiplier", "普通敌人生命",
               0.1, 10.0, 0.1, "float", "combat", "新生成"),
    OptionSpec("elite_health_multiplier", "精英敌人生命",
               0.1, 10.0, 0.1, "float", "combat", "新生成"),
    OptionSpec("boss_health_multiplier", "首领生命",
               0.1, 10.0, 0.1, "float", "combat", "新生成"),
    OptionSpec("incoming_damage_multiplier", "玩家受到伤害",
               0.0, 5.0, 0.05, "float", "combat", "即时"),
    OptionSpec("player_attack_multiplier", "玩家攻击",
               0.1, 10.0, 0.1, "float", "combat", "即时"),
    OptionSpec("player_speed_multiplier", "玩家移速",
               0.25, 5.0, 0.05, "float", "combat", "即时"),
    OptionSpec("player_max_health_multiplier", "玩家生命上限",
               0.25, 10.0, 0.05, "float", "resources", "新一局"),
    OptionSpec("extra_start_crystals", "额外初始水晶",
               -9999, 9999, 1, "int", "resources", "新一局"),
    OptionSpec("extra_start_bombs", "额外初始炸弹",
               0, 99, 1, "int", "resources", "新一局"),
    OptionSpec("beacon_damage_multiplier", "寺庙水晶伤害",
               0.0, 10.0, 0.1, "float", "resources", "即时"),
    OptionSpec("beacon_cooldown_multiplier", "寺庙水晶冷却",
               0.1, 5.0, 0.05, "float", "resources", "即时"),
    OptionSpec("blizzard_push_multiplier", "风雪与风灵推力",
               0.0, 3.0, 0.05, "float", "resources", "即时"),
)

SPEC_BY_KEY = {spec.key: spec for spec in OPTION_SPECS}


@dataclass(frozen=True)
class ModifierConfig:
    enemy_health_multiplier: float = 1.0
    elite_health_multiplier: float = 1.0
    boss_health_multiplier: float = 1.0
    incoming_damage_multiplier: float = 1.0
    player_attack_multiplier: float = 1.0
    player_speed_multiplier: float = 1.0
    player_max_health_multiplier: float = 1.0
    extra_start_crystals: int = 0
    extra_start_bombs: int = 0
    beacon_damage_multiplier: float = 1.0
    beacon_cooldown_multiplier: float = 1.0
    blizzard_push_multiplier: float = 1.0

    def validated(self) -> "ModifierConfig":
        values: dict[str, Any] = {}
        for spec in OPTION_SPECS:
            raw = getattr(self, spec.key)
            try:
                number = float(raw)
            except (TypeError, ValueError):
                number = float(getattr(ModifierConfig(), spec.key))
            if not math.isfinite(number):
                number = float(getattr(ModifierConfig(), spec.key))
            number = min(spec.maximum, max(spec.minimum, number))
            if spec.kind == "int":
                values[spec.key] = int(round(number))
            else:
                values[spec.key] = round(number, 4)
        return ModifierConfig(**values)

    def changed(self, **values: Any) -> "ModifierConfig":
        return replace(self, **values).validated()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self.validated())


def defaults() -> ModifierConfig:
    return ModifierConfig().validated()


def from_mapping(data: Any) -> ModifierConfig:
    if not isinstance(data, dict):
        return defaults()
    values = {}
    default_config = ModifierConfig()
    for spec in OPTION_SPECS:
        values[spec.key] = data.get(spec.key, getattr(default_config, spec.key))
    try:
        return ModifierConfig(**values).validated()
    except (TypeError, ValueError):
        return defaults()


def load_config(path: str | Path) -> ModifierConfig:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return defaults()
    if isinstance(raw, dict) and "modifiers" in raw:
        raw = raw["modifiers"]
    return from_mapping(raw)


def write_config(path: str | Path, config: ModifierConfig) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "modifiers": config.validated().as_dict(),
    }
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def validate_config(config: ModifierConfig) -> Iterable[str]:
    """Return user-facing errors; validated configs normally return none."""
    errors: list[str] = []
    for spec in OPTION_SPECS:
        value = getattr(config, spec.key)
        if not spec.minimum <= float(value) <= spec.maximum:
            errors.append(
                f"{spec.title}必须在 {spec.minimum:g} 到 {spec.maximum:g} 之间"
            )
    return errors


def config_fields() -> tuple[str, ...]:
    return tuple(item.name for item in fields(ModifierConfig))
