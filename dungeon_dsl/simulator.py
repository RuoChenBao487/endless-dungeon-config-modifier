"""Monte Carlo simulation for normalized dungeon configuration."""

from __future__ import annotations

from collections import Counter
import random


def _weighted_choice(rng: random.Random, weighted: dict[str, float]) -> str | None:
    if not weighted:
        return None
    names = list(weighted)
    weights = [max(0.0, float(weighted[name])) for name in names]
    total = sum(weights)
    if total <= 0:
        return None
    return rng.choices(names, weights=weights, k=1)[0]


def simulate(config: dict, rooms: int = 100000, seed: int | None = None) -> dict:
    """Simulate region/normal-room flow and return aggregate statistics."""
    if rooms < 1:
        raise ValueError("rooms must be at least 1")
    regions = config.get("regions") or {}
    if not regions:
        raise ValueError("configuration has no regions")
    nested_rooms = config.get("nested_rooms") or {}
    rng = random.Random(seed)

    region_names = list(regions)
    current_region: str | None = None
    remaining = 0
    current_length = 0
    nested_seen: set[str] = set()
    gap_chance: float | None = None
    gap_step = 0.1
    force_normal_room = False

    simulated = 0
    normal_rooms = 0
    region_rooms = 0
    completed_regions = 0
    completed_lengths: list[int] = []
    nested_counts = Counter()
    enemy_counts = Counter()
    region_stats = {
        name: {"starts": 0, "completed": 0, "rooms": 0, "max_length": 0}
        for name in region_names
    }
    once_violations = 0

    while simulated < rooms:
        if current_region is None:
            if force_normal_room:
                normal_rooms += 1
                simulated += 1
                force_normal_room = False
                continue
            if gap_chance is not None and gap_chance > 0:
                if rng.random() < gap_chance:
                    normal_rooms += 1
                    simulated += 1
                    gap_chance = max(0.0, gap_chance - gap_step)
                    continue

            current_region = rng.choice(region_names)
            region = regions[current_region]
            minimum, maximum = region["length"]
            current_length = rng.randint(int(minimum), int(maximum))
            remaining = current_length
            nested_seen = set()
            gap_chance = None
            region_stats[current_region]["starts"] += 1
            continue

        region = regions[current_region]
        remaining -= 1
        current_length += 0
        region_rooms += 1
        simulated += 1
        region_stats[current_region]["rooms"] += 1

        selected_nested = None
        for nested_name in region.get("nested", []):
            nested = nested_rooms.get(nested_name, {})
            if nested.get("once_per_region", False) and nested_name in nested_seen:
                continue
            if rng.random() < float(nested.get("chance", 0.0)):
                selected_nested = nested_name
                break
        if selected_nested is not None:
            nested = nested_rooms[selected_nested]
            if nested.get("once_per_region", False):
                if selected_nested in nested_seen:
                    once_violations += 1
                nested_seen.add(selected_nested)
            remaining += int(nested.get("extend", 0))
            current_length += int(nested.get("extend", 0))
            nested_counts[selected_nested] += 1

        enemy = _weighted_choice(rng, region.get("enemy_pool", {}))
        if enemy:
            enemy_counts[enemy] += 1

        if remaining <= 0:
            completed_regions += 1
            completed_lengths.append(current_length)
            region_stats[current_region]["completed"] += 1
            region_stats[current_region]["max_length"] = max(
                region_stats[current_region]["max_length"], current_length)
            gap_chance = float(region.get("normal_gap", 0.9))
            gap_step = float(region.get("normal_gap_step", 0.1))
            force_normal_room = True
            current_region = None
            remaining = 0
            nested_seen = set()

    length_summary = {"min": 0, "max": 0, "mean": 0.0}
    if completed_lengths:
        length_summary = {
            "min": min(completed_lengths),
            "max": max(completed_lengths),
            "mean": round(sum(completed_lengths) / len(completed_lengths), 3),
        }

    nested_rates = {
        name: round(count / max(1, completed_regions), 4)
        for name, count in sorted(nested_counts.items())
    }
    enemy_total = sum(enemy_counts.values())
    enemy_distribution = {
        name: round(count / enemy_total, 4)
        for name, count in sorted(enemy_counts.items())
    } if enemy_total else {}

    return {
        "seed": seed,
        "requested_rooms": rooms,
        "simulated_rooms": simulated,
        "normal_rooms": normal_rooms,
        "region_rooms": region_rooms,
        "completed_regions": completed_regions,
        "region_length": length_summary,
        "nested_counts": dict(sorted(nested_counts.items())),
        "nested_occurrences_per_completed_region": nested_rates,
        "once_per_region_violations": once_violations,
        "enemy_samples": enemy_total,
        "enemy_distribution": enemy_distribution,
        "regions": region_stats,
    }
