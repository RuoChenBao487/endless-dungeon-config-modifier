"""Semantic validation for Dungeon Rule Language."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches

from .ast import Catalog, NestedRoom, Program, Region, RoomRule, Span
from .diagnostics import DiagnosticBag, Location


SUPPORTED_VERSION = 1
MAX_NESTED_EXTENSION = 5


def _location(span: Span) -> Location:
    return Location(span.line, span.column,
                    max(1, span.end_column - span.column))


def _suggest(value: str, choices: set[str]) -> str | None:
    matches = get_close_matches(value, sorted(choices), n=1, cutoff=0.6)
    return f"did you mean {matches[0]!r}?" if matches else None


@dataclass
class CatalogIndex:
    biomes: set[str]
    enemies: set[str]
    elites: set[str]
    bosses: set[str]
    affixes: set[str]

    @classmethod
    def empty(cls) -> "CatalogIndex":
        return cls(set(), set(), set(), set(), set())


def build_catalog_index(program: Program,
                        diagnostics: DiagnosticBag) -> CatalogIndex:
    index = CatalogIndex.empty()
    if program.catalog is None:
        diagnostics.error(
            "E100", "missing catalog block",
            _location(program.span),
            "declare biome, enemy, elite and other symbols in a catalog block",
        )
        return index

    buckets = {
        "biome": index.biomes,
        "enemy": index.enemies,
        "elite": index.elites,
        "boss": index.bosses,
        "affix": index.affixes,
    }
    scenes: list[tuple[str, str, Span]] = []
    for entry in program.catalog.entries:
        bucket = buckets[entry.kind]
        if entry.name in bucket:
            diagnostics.error(
                "E101", f"duplicate {entry.kind} symbol {entry.name!r}",
                _location(entry.span),
            )
            continue
        bucket.add(entry.name)
        if entry.scene is not None:
            if entry.kind not in {"elite", "boss"}:
                diagnostics.error(
                    "E102", f"{entry.kind} symbols cannot declare a scene",
                    _location(entry.span),
                )
            else:
                scenes.append((entry.kind, entry.scene, entry.span))

    for kind, scene, span in scenes:
        if scene not in index.biomes:
            diagnostics.error(
                "E103", f"unknown scene {scene!r} for {kind}",
                _location(span), _suggest(scene, index.biomes),
            )
    return index


def _validate_region(region: Region, region_names: set[str],
                     room_rules: dict[str, RoomRule],
                     catalog: CatalogIndex,
                     has_nested: bool,
                     diagnostics: DiagnosticBag) -> None:
    if region.length_min < 1:
        diagnostics.error(
            "E202", "region minimum length must be at least 1",
            _location(region.span),
        )
    if region.length_min > region.length_max:
        diagnostics.error(
            "E202", "region minimum length cannot exceed maximum length",
            _location(region.span),
        )
    if not 0 <= region.normal_gap <= 1:
        diagnostics.error(
            "E203", "normal_gap must be between 0 and 1",
            _location(region.span),
        )
    if not 0 <= region.normal_gap_step <= 1:
        diagnostics.error(
            "E203", "normal_gap_step must be between 0 and 1",
            _location(region.span),
        )

    pool = region.enemy_pool
    if pool is None:
        diagnostics.error(
            "E204", f"region {region.name!r} has no enemy_pool",
            _location(region.span),
        )
    elif not pool.entries:
        diagnostics.error(
            "E204", f"region {region.name!r} has an empty enemy_pool",
            _location(pool.span),
        )
    else:
        seen: set[str] = set()
        valid_enemy_names = catalog.enemies | catalog.elites
        for entry in pool.entries:
            if entry.name in seen:
                diagnostics.error(
                    "E205", f"duplicate enemy {entry.name!r} in enemy_pool",
                    _location(entry.span),
                )
            seen.add(entry.name)
            if entry.weight <= 0:
                diagnostics.error(
                    "E206", f"enemy weight for {entry.name!r} must be positive",
                    _location(entry.span),
                )
            if entry.name not in valid_enemy_names:
                diagnostics.error(
                    "E201", f"unknown enemy {entry.name!r}",
                    _location(entry.span),
                    _suggest(entry.name, valid_enemy_names),
                )

    if has_nested and not any(rule.allow_nested for rule in room_rules.values()):
        diagnostics.warning(
            "W303", "nested rooms exist but no room rule allows nested rooms",
            _location(region.span),
            "add a room_rule with allow_nested true",
        )

    if not has_nested:
        diagnostics.warning(
            "W304", f"region {region.name!r} declares no nested rooms",
            _location(region.span),
        )


def _validate_nested(room: NestedRoom, region_names: set[str],
                     room_rules: dict[str, RoomRule],
                     diagnostics: DiagnosticBag) -> None:
    if room.parent is None:
        diagnostics.error(
            "E211", f"nested room {room.name!r} has no parent region",
            _location(room.span),
        )
    elif room.parent not in region_names:
        diagnostics.error(
            "E212", f"unknown parent region {room.parent!r} for {room.name!r}",
            _location(room.span), _suggest(room.parent, region_names),
        )
    elif room.parent == room.name:
        diagnostics.error(
            "E213", f"nested room {room.name!r} cannot be its own parent",
            _location(room.span),
        )

    if not 0 < room.chance <= 1:
        diagnostics.error(
            "E214", f"chance for {room.name!r} must be in (0, 1]",
            _location(room.span),
        )
    if room.extend < 0:
        diagnostics.error(
            "E215", f"extend for {room.name!r} cannot be negative",
            _location(room.span),
        )
    elif room.extend > MAX_NESTED_EXTENSION:
        diagnostics.warning(
            "W301", f"extend for {room.name!r} is unusually large",
            _location(room.span),
            f"consider keeping nested extensions at or below {MAX_NESTED_EXTENSION}",
        )
    if not room.once_per_region:
        diagnostics.warning(
            "W302", f"nested room {room.name!r} may appear more than once per region",
            _location(room.span),
        )
    if not room.allowed_room_rules:
        diagnostics.error(
            "E216", f"nested room {room.name!r} has no allowed_room_rules",
            _location(room.span),
            "use [combat] for a standard combat room",
        )
        return

    seen: set[str] = set()
    for rule_name in room.allowed_room_rules:
        if rule_name in seen:
            diagnostics.error(
                "E219", f"duplicate allowed room rule {rule_name!r}",
                _location(room.span),
            )
        seen.add(rule_name)
        rule = room_rules.get(rule_name)
        if rule is None:
            diagnostics.error(
                "E217", f"unknown room rule {rule_name!r}",
                _location(room.span), _suggest(rule_name, set(room_rules)),
            )
        elif not rule.allow_nested:
            diagnostics.error(
                "E218", f"room rule {rule_name!r} does not allow nested rooms",
                _location(room.span),
            )


def validate_program(program: Program) -> DiagnosticBag:
    diagnostics = DiagnosticBag()
    if program.version != SUPPORTED_VERSION:
        diagnostics.error(
            "E110", f"unsupported DSL version {program.version}",
            _location(program.span),
            f"this tool supports version {SUPPORTED_VERSION}",
        )

    catalog = build_catalog_index(program, diagnostics)

    region_names: set[str] = set()
    for region in program.regions:
        if region.name in region_names:
            diagnostics.error(
                "E200", f"duplicate region {region.name!r}",
                _location(region.span),
            )
        region_names.add(region.name)

    room_rules: dict[str, RoomRule] = {}
    for rule in program.room_rules:
        if rule.name in room_rules:
            diagnostics.error(
                "E220", f"duplicate room rule {rule.name!r}",
                _location(rule.span),
            )
            continue
        room_rules[rule.name] = rule

    nested_names: set[str] = set()
    all_nested = program.all_nested
    for room in all_nested:
        if room.name in nested_names:
            diagnostics.error(
                "E210", f"duplicate nested room {room.name!r}",
                _location(room.span),
            )
        nested_names.add(room.name)

    if not program.regions:
        diagnostics.error(
            "E221", "program declares no regions",
            _location(program.span),
        )

    nested_parents = {
        room.parent for room in all_nested if room.parent is not None
    }
    for region in program.regions:
        _validate_region(
            region,
            region_names,
            room_rules,
            catalog,
            region.name in nested_parents,
            diagnostics,
        )
    for room in all_nested:
        _validate_nested(room, region_names, room_rules, diagnostics)

    return diagnostics
