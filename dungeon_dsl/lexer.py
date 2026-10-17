"""A small, source-located lexer for DRL."""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import DslSyntaxError, Location


IDENT = "IDENT"
NUMBER = "NUMBER"
STRING = "STRING"
LBRACE = "LBRACE"
RBRACE = "RBRACE"
LBRACKET = "LBRACKET"
RBRACKET = "RBRACKET"
COMMA = "COMMA"
COLON = "COLON"
DOTDOT = "DOTDOT"
SEMICOLON = "SEMICOLON"
EOF = "EOF"


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    line: int
    column: int
    end_line: int
    end_column: int

    @property
    def location(self) -> Location:
        return Location(self.line, self.column, max(1, self.end_column - self.column))


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.index = 0
        self.line = 1
        self.column = 1
        self.tokens: list[Token] = []

    def _peek(self, offset: int = 0) -> str:
        index = self.index + offset
        if index >= len(self.source):
            return ""
        return self.source[index]

    def _advance(self) -> str:
        char = self._peek()
        self.index += 1
        if char == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return char

    def _skip_trivia(self) -> None:
        while True:
            while self._peek() and self._peek().isspace():
                self._advance()
            if self._peek() == "#":
                while self._peek() and self._peek() != "\n":
                    self._advance()
                continue
            if self._peek() == "/" and self._peek(1) == "/":
                while self._peek() and self._peek() != "\n":
                    self._advance()
                continue
            return

    def _emit(self, kind: str, text: str, value: object, start_line: int,
              start_column: int) -> None:
        self.tokens.append(Token(
            kind, text, value, start_line, start_column,
            self.line, self.column,
        ))

    def tokenize(self) -> list[Token]:
        while True:
            self._skip_trivia()
            if not self._peek():
                self.tokens.append(Token(
                    EOF, "", None, self.line, self.column,
                    self.line, self.column,
                ))
                return self.tokens

            start_line, start_column = self.line, self.column
            char = self._peek()

            if char.isalpha() or char == "_":
                text = ""
                while self._peek() and (
                    self._peek().isalnum() or self._peek() == "_"
                ):
                    text += self._advance()
                self._emit(IDENT, text, text, start_line, start_column)
                continue

            if char.isdigit() or (
                char == "-" and self._peek(1).isdigit()
            ):
                text = self._advance()
                while self._peek().isdigit():
                    text += self._advance()
                if self._peek() == "." and self._peek(1) != ".":
                    text += self._advance()
                    while self._peek().isdigit():
                        text += self._advance()
                value = float(text) if "." in text else int(text)
                self._emit(NUMBER, text, value, start_line, start_column)
                continue

            if char == '"':
                self._advance()
                value = ""
                while self._peek() and self._peek() != '"':
                    char = self._advance()
                    if char == "\\":
                        escaped = self._advance()
                        value += {
                            "n": "\n", "r": "\r", "t": "\t",
                            '"': '"', "\\": "\\",
                        }.get(escaped, escaped)
                    else:
                        value += char
                if self._peek() != '"':
                    raise DslSyntaxError(
                        "unterminated string literal",
                        Location(start_line, start_column),
                    )
                self._advance()
                self._emit(STRING, value, value, start_line, start_column)
                continue

            if char == "." and self._peek(1) == ".":
                self._advance()
                self._advance()
                self._emit(DOTDOT, "..", None, start_line, start_column)
                continue

            punctuation = {
                "{": LBRACE,
                "}": RBRACE,
                "[": LBRACKET,
                "]": RBRACKET,
                ",": COMMA,
                ":": COLON,
                ";": SEMICOLON,
            }
            if char in punctuation:
                self._advance()
                self._emit(punctuation[char], char, None,
                           start_line, start_column)
                continue

            raise DslSyntaxError(
                f"unexpected character {char!r}",
                Location(start_line, start_column),
            )


def tokenize(source: str) -> list[Token]:
    return Lexer(source).tokenize()
