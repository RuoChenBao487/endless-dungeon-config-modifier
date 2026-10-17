"""AST nodes for Dungeon Rule Language."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class CatalogEntry:
    kind: str
    name: str
    scene: str | None
    span: Span


@dataclass(frozen=True)
class Catalog:
    entries: list[CatalogEntry]
    span: Span


@dataclass(frozen=True)
class WeightedEnemy:
    name: str
    weight: float
    span: Span


@dataclass(frozen=True)
class EnemyPool:
    entries: list[WeightedEnemy]
    span: Span


@dataclass(frozen=True)
class NestedRoom:
    name: str
    parent: str | None
    chance: float
    extend: int
    once_per_region: bool
    allowed_room_rules: list[str]
    span: Span


@dataclass(frozen=True)
class RoomRule:
    name: str
    allow_nested: bool
    span: Span


@dataclass(frozen=True)
class Region:
    name: str
    title: str
    length_min: int
    length_max: int
    normal_gap: float
    normal_gap_step: float
    enemy_pool: EnemyPool | None
    nested: list[NestedRoom]
    span: Span


@dataclass(frozen=True)
class Program:
    version: int
    catalog: Catalog | None
    regions: list[Region]
    nested: list[NestedRoom]
    room_rules: list[RoomRule]
    span: Span

    @property
    def all_nested(self) -> list[NestedRoom]:
        result = list(self.nested)
        for region in self.regions:
            result.extend(region.nested)
        return result
