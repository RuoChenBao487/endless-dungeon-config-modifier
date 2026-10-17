"""Source locations, diagnostics and human-readable error rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Location:
    line: int
    column: int
    length: int = 1


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    location: Location | None = None
    severity: str = "error"
    hint: str | None = None

    def format(self, source: str, filename: str = "<input>") -> str:
        prefix = f"{filename}"
        if self.location is not None:
            prefix += f":{self.location.line}:{self.location.column}"
        lines = [f"{prefix}: {self.severity}[{self.code}]: {self.message}"]
        if self.location is not None:
            source_lines = source.splitlines()
            index = self.location.line - 1
            if 0 <= index < len(source_lines):
                text = source_lines[index]
                lines.append(f"  {self.location.line:>4} | {text}")
                caret_len = max(1, self.location.length)
                lines.append(
                    f"       | {' ' * (self.location.column - 1)}"
                    + "^" * caret_len
                )
        if self.hint:
            lines.append(f"  help: {self.hint}")
        return "\n".join(lines)


@dataclass
class DiagnosticBag:
    items: list[Diagnostic] = field(default_factory=list)

    def add(self, code: str, message: str, location: Location | None = None,
            severity: str = "error", hint: str | None = None) -> None:
        self.items.append(Diagnostic(code, message, location, severity, hint))

    def error(self, code: str, message: str, location: Location | None = None,
              hint: str | None = None) -> None:
        self.add(code, message, location, "error", hint)

    def warning(self, code: str, message: str, location: Location | None = None,
                hint: str | None = None) -> None:
        self.add(code, message, location, "warning", hint)

    def extend(self, items: Iterable[Diagnostic]) -> None:
        self.items.extend(items)

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.items if item.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [item for item in self.items if item.severity == "warning"]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class DslSyntaxError(Exception):
    def __init__(self, message: str, location: Location,
                 hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.location = location
        self.hint = hint

    def diagnostic(self, code: str = "E001") -> Diagnostic:
        return Diagnostic(code, self.message, self.location, "error", self.hint)


def render_diagnostics(diagnostics: Iterable[Diagnostic], source: str,
                       filename: str = "<input>") -> str:
    return "\n\n".join(item.format(source, filename) for item in diagnostics)
