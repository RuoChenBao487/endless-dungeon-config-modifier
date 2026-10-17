"""Compile a validated DRL program into a normalized JSON configuration."""

from __future__ import annotations

import json

from .ast import Program


def compile_program(program: Program) -> dict:
    """Return the normalized configuration represented by *program*.

    The caller is expected to run ``validate_program`` first. The compiler
    deliberately does not silently repair malformed programs.
    """
    elites: dict[str, dict] = {}
    bosses: dict[str, dict] = {}
    catalog = {
        "biomes": [],
        "enemies": [],
        "elites": elites,
        "bosses": bosses,
        "affixes": [],
    }
    if program.catalog is not None:
        for entry in program.catalog.entries:
            if entry.kind == "biome":
                catalog["biomes"].append(entry.name)
            elif entry.kind == "enemy":
                catalog["enemies"].append(entry.name)
            elif entry.kind == "elite":
                elites[entry.name] = {"scene": entry.scene}
            elif entry.kind == "boss":
                bosses[entry.name] = {"scene": entry.scene}
            elif entry.kind == "affix":
                catalog["affixes"].append(entry.name)
        for key in ("biomes", "enemies", "affixes"):
            catalog[key] = sorted(set(catalog[key]))

    room_rules = {
        rule.name: {"allow_nested": rule.allow_nested}
        for rule in program.room_rules
    }

    nested_rooms: dict[str, dict] = {}
    for room in program.all_nested:
        nested_rooms[room.name] = {
            "parent": room.parent,
            "chance": room.chance,
            "extend": room.extend,
            "once_per_region": room.once_per_region,
            "allowed_room_rules": list(room.allowed_room_rules),
        }

    regions: dict[str, dict] = {}
    nested_by_parent: dict[str, list[str]] = {}
    for room in program.all_nested:
        if room.parent:
            nested_by_parent.setdefault(room.parent, []).append(room.name)
    for region in program.regions:
        pool = {}
        if region.enemy_pool is not None:
            pool = {
                entry.name: entry.weight
                for entry in region.enemy_pool.entries
            }
        regions[region.name] = {
            "title": region.title or region.name,
            "length": [region.length_min, region.length_max],
            "normal_gap": region.normal_gap,
            "normal_gap_step": region.normal_gap_step,
            "enemy_pool": pool,
            "nested": nested_by_parent.get(region.name, []),
        }

    return {
        "version": program.version,
        "catalog": catalog,
        "room_rules": room_rules,
        "regions": regions,
        "nested_rooms": nested_rooms,
    }


def dumps_program(program: Program) -> str:
    return json.dumps(
        compile_program(program),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
