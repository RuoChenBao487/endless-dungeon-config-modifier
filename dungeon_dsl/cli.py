"""Command-line interface for Dungeon Rule Language."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .compiler import compile_program
from .diagnostics import DslSyntaxError, render_diagnostics
from .parser import parse_file
from .simulator import simulate
from .validator import validate_program


def _load(path: str):
    program, source = parse_file(path)
    diagnostics = validate_program(program)
    return program, source, diagnostics


def _print_diagnostics(diagnostics, source: str, filename: str) -> None:
    if diagnostics.items:
        print(render_diagnostics(diagnostics.items, source, filename),
              file=sys.stderr, flush=True)


def _cmd_check(args) -> int:
    try:
        _program, source, diagnostics = _load(args.file)
    except DslSyntaxError as error:
        print(render_diagnostics([error.diagnostic()], Path(args.file).read_text(
            encoding="utf-8"), args.file), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(
            [
                {
                    "code": item.code,
                    "severity": item.severity,
                    "message": item.message,
                    "line": item.location.line if item.location else None,
                    "column": item.location.column if item.location else None,
                    "hint": item.hint,
                }
                for item in diagnostics.items
            ],
            ensure_ascii=False,
            indent=2,
        ))
    else:
        _print_diagnostics(diagnostics, source, args.file)
        if diagnostics.has_errors:
            print(f"检查失败：{len(diagnostics.errors)} 个错误，"
                  f"{len(diagnostics.warnings)} 个警告")
        else:
            print(f"检查通过：0 个错误，{len(diagnostics.warnings)} 个警告")
    return 1 if diagnostics.has_errors else 0


def _cmd_compile(args) -> int:
    try:
        program, source, diagnostics = _load(args.file)
    except DslSyntaxError as error:
        print(render_diagnostics([error.diagnostic()], Path(args.file).read_text(
            encoding="utf-8"), args.file), file=sys.stderr)
        return 2
    if diagnostics.has_errors:
        _print_diagnostics(diagnostics, source, args.file)
        return 1
    _print_diagnostics(diagnostics, source, args.file)
    output = json.dumps(
        compile_program(program), ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
        print(f"已生成：{target}")
    else:
        print(output, end="")
    return 0


def _cmd_simulate(args) -> int:
    try:
        program, source, diagnostics = _load(args.file)
    except DslSyntaxError as error:
        print(render_diagnostics([error.diagnostic()], Path(args.file).read_text(
            encoding="utf-8"), args.file), file=sys.stderr)
        return 2
    if diagnostics.has_errors:
        _print_diagnostics(diagnostics, source, args.file)
        return 1
    config = compile_program(program)
    result = simulate(config, rooms=args.rooms, seed=args.seed)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"模拟结果：{args.output}")
    elif args.json:
        print(text, end="")
    else:
        print(f"房间样本: {result['simulated_rooms']}")
        print(f"普通房: {result['normal_rooms']}")
        print(f"生态房: {result['region_rooms']}")
        print(f"完成区域: {result['completed_regions']}")
        length = result["region_length"]
        print(f"区域长度: min={length['min']} mean={length['mean']} "
              f"max={length['max']}")
        print("嵌套房出现次数:")
        for name, count in result["nested_counts"].items():
            print(f"  {name}: {count}")
        print(f"唯一性违规: {result['once_per_region_violations']}")
    return 0


def _cmd_explain(args) -> int:
    try:
        program, source, diagnostics = _load(args.file)
    except DslSyntaxError as error:
        print(render_diagnostics([error.diagnostic()], Path(args.file).read_text(
            encoding="utf-8"), args.file), file=sys.stderr)
        return 2
    if diagnostics.has_errors:
        _print_diagnostics(diagnostics, source, args.file)
        return 1
    config = compile_program(program)
    region = config["regions"].get(args.region)
    if region is None:
        print(f"未知区域：{args.region}", file=sys.stderr)
        return 1
    print(json.dumps(region, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dungeon-dsl",
        description="Parse, validate, compile and simulate Dungeon Rule Language.",
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="parse and validate a DSL file")
    check.add_argument("file")
    check.add_argument("--json", action="store_true", help="print diagnostics as JSON")
    check.set_defaults(func=_cmd_check)

    compile_cmd = subparsers.add_parser("compile", help="compile to JSON")
    compile_cmd.add_argument("file")
    compile_cmd.add_argument("-o", "--output")
    compile_cmd.set_defaults(func=_cmd_compile)

    sim = subparsers.add_parser("simulate", help="run Monte Carlo simulation")
    sim.add_argument("file")
    sim.add_argument("--rooms", type=int, default=100000)
    sim.add_argument("--seed", type=int, default=42)
    sim.add_argument("--json", action="store_true")
    sim.add_argument("-o", "--output")
    sim.set_defaults(func=_cmd_simulate)

    explain = subparsers.add_parser("explain", help="show one compiled region")
    explain.add_argument("file")
    explain.add_argument("region")
    explain.set_defaults(func=_cmd_explain)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
