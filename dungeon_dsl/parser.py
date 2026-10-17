"""Recursive-descent parser for Dungeon Rule Language."""

from __future__ import annotations

from pathlib import Path

from .ast import (
    Catalog,
    CatalogEntry,
    EnemyPool,
    NestedRoom,
    Program,
    Region,
    RoomRule,
    Span,
    WeightedEnemy,
)
from .diagnostics import DslSyntaxError, Location
from .lexer import (
    COMMA,
    DOTDOT,
    EOF,
    IDENT,
    LBRACE,
    LBRACKET,
    NUMBER,
    RBRACE,
    RBRACKET,
    SEMICOLON,
    STRING,
    Token,
    tokenize,
)


class Parser:
    def __init__(self, tokens: list[Token], filename: str = "<input>"):
        self.tokens = tokens
        self.filename = filename
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def _advance(self) -> Token:
        token = self.current
        if token.kind != EOF:
            self.index += 1
        return token

    def _is_keyword(self, word: str) -> bool:
        return self.current.kind == IDENT and self.current.text == word

    def _match_keyword(self, word: str) -> Token | None:
        if self._is_keyword(word):
            return self._advance()
        return None

    def _expect_keyword(self, word: str) -> Token:
        token = self._match_keyword(word)
        if token is None:
            self._error(f"expected keyword {word!r}")
        return token

    def _expect_kind(self, kind: str, message: str) -> Token:
        if self.current.kind != kind:
            self._error(message)
        return self._advance()

    def _expect_ident(self, message: str = "expected identifier") -> Token:
        return self._expect_kind(IDENT, message)

    def _expect_number(self, message: str = "expected number") -> Token:
        return self._expect_kind(NUMBER, message)

    def _expect_int(self, message: str = "expected integer") -> int:
        token = self._expect_number(message)
        value = token.value
        if isinstance(value, float):
            if not value.is_integer():
                self._error("expected an integer", token)
            return int(value)
        return int(value)

    def _expect_string(self, message: str = "expected string") -> str:
        return str(self._expect_kind(STRING, message).value)

    def _expect_bool(self, message: str = "expected true or false") -> bool:
        if self._is_keyword("true"):
            self._advance()
            return True
        if self._is_keyword("false"):
            self._advance()
            return False
        self._error(message)
        raise AssertionError("unreachable")

    def _expect_symbol(self, kind: str, message: str) -> Token:
        return self._expect_kind(kind, message)

    def _consume_semicolon(self) -> None:
        if self.current.kind == SEMICOLON:
            self._advance()

    def _error(self, message: str, token: Token | None = None,
               hint: str | None = None) -> None:
        token = token or self.current
        raise DslSyntaxError(
            message,
            Location(token.line, token.column, max(1, token.end_column - token.column)),
            hint,
        )

    @staticmethod
    def _span(start: Token, end: Token) -> Span:
        return Span(start.line, start.column, end.end_line, end.end_column)

    def parse(self) -> Program:
        start = self._expect_keyword("version")
        version = self._expect_int("version must be an integer")
        self._consume_semicolon()

        catalog: Catalog | None = None
        regions: list[Region] = []
        nested: list[NestedRoom] = []
        room_rules: list[RoomRule] = []

        while self.current.kind != EOF:
            if self._is_keyword("catalog"):
                if catalog is not None:
                    self._error("duplicate catalog block")
                catalog = self._parse_catalog()
            elif self._is_keyword("region"):
                regions.append(self._parse_region())
            elif self._is_keyword("nested"):
                nested.append(self._parse_nested(parent=None))
            elif self._is_keyword("room_rule"):
                room_rules.append(self._parse_room_rule())
            else:
                self._error(
                    "expected declaration: catalog, region, nested or room_rule",
                    hint=f"found {self.current.text!r}",
                )

        end = self.current
        return Program(
            version=version,
            catalog=catalog,
            regions=regions,
            nested=nested,
            room_rules=room_rules,
            span=self._span(start, end),
        )

    def _parse_catalog(self) -> Catalog:
        start = self._expect_keyword("catalog")
        self._expect_symbol(LBRACE, "expected '{' after catalog")
        entries: list[CatalogEntry] = []
        while self.current.kind != RBRACE:
            if self.current.kind == EOF:
                self._error("unterminated catalog block")
            kind_token = self._expect_ident("expected catalog entry kind")
            kind = kind_token.text
            if kind not in {"enemy", "elite", "boss", "biome", "affix"}:
                self._error(
                    "unknown catalog entry kind",
                    kind_token,
                    "expected enemy, elite, boss, biome or affix",
                )
            name_token = self._expect_ident("expected symbol name")
            scene: str | None = None
            if self._is_keyword("scene"):
                self._advance()
                scene = self._expect_ident("expected scene name").text
            self._consume_semicolon()
            entries.append(CatalogEntry(
                kind, name_token.text, scene, self._span(kind_token, name_token),
            ))
        end = self._expect_symbol(RBRACE, "expected '}' after catalog")
        return Catalog(entries, self._span(start, end))

    def _parse_region(self) -> Region:
        start = self._expect_keyword("region")
        name_token = self._expect_ident("expected region name")
        self._expect_symbol(LBRACE, "expected '{' after region name")
        title = ""
        length_min, length_max = 3, 5
        normal_gap, normal_gap_step = 0.9, 0.1
        enemy_pool: EnemyPool | None = None
        nested: list[NestedRoom] = []
        seen: set[str] = set()

        while self.current.kind != RBRACE:
            if self.current.kind == EOF:
                self._error("unterminated region block")
            field_token = self._expect_ident("expected region field")
            field = field_token.text
            if field != "nested" and field in seen:
                self._error(f"duplicate region field {field!r}")
            if field != "nested":
                seen.add(field)
            if field == "title":
                title = self._expect_string("expected region title string")
            elif field == "length":
                length_min = self._expect_int("expected minimum room count")
                self._expect_symbol(DOTDOT, "expected '..' in room count range")
                length_max = self._expect_int("expected maximum room count")
            elif field == "normal_gap":
                normal_gap = float(self._expect_number("expected normal gap probability").value)
            elif field == "normal_gap_step":
                normal_gap_step = float(
                    self._expect_number("expected normal gap step").value)
            elif field == "enemy_pool":
                enemy_pool = self._parse_enemy_pool()
            elif field == "nested":
                nested.append(self._parse_nested(
                    parent=name_token.text, start_token=field_token))
            else:
                self._error(
                    f"unknown region field {field!r}",
                    hint="expected title, length, normal_gap, normal_gap_step, "
                         "enemy_pool or nested",
                )
            self._consume_semicolon()

        end = self._expect_symbol(RBRACE, "expected '}' after region")
        return Region(
            name=name_token.text,
            title=title,
            length_min=length_min,
            length_max=length_max,
            normal_gap=normal_gap,
            normal_gap_step=normal_gap_step,
            enemy_pool=enemy_pool,
            nested=nested,
            span=self._span(start, end),
        )

    def _parse_enemy_pool(self) -> EnemyPool:
        start = self._expect_symbol(LBRACE, "expected '{' after enemy_pool")
        entries: list[WeightedEnemy] = []
        while self.current.kind != RBRACE:
            if self.current.kind == EOF:
                self._error("unterminated enemy_pool block")
            name_token = self._expect_ident("expected enemy name")
            self._expect_keyword("weight")
            weight_token = self._expect_number("expected enemy weight")
            entries.append(WeightedEnemy(
                name_token.text,
                float(weight_token.value),
                self._span(name_token, weight_token),
            ))
            self._consume_semicolon()
        end = self._expect_symbol(RBRACE, "expected '}' after enemy_pool")
        return EnemyPool(entries, self._span(start, end))

    def _parse_nested(self, parent: str | None,
                      start_token: Token | None = None) -> NestedRoom:
        start = start_token or self._expect_keyword("nested")
        name_token = self._expect_ident("expected nested room name")
        self._expect_symbol(LBRACE, "expected '{' after nested room name")
        chance = 0.0
        extend = 0
        once_per_region = False
        allowed_room_rules: list[str] = []
        explicit_parent = parent
        seen: set[str] = set()

        while self.current.kind != RBRACE:
            if self.current.kind == EOF:
                self._error("unterminated nested room block")
            field = self._expect_ident("expected nested room field").text
            if field in seen:
                self._error(f"duplicate nested room field {field!r}")
            seen.add(field)
            if field == "parent":
                explicit_parent = self._expect_ident("expected parent name").text
            elif field == "chance":
                chance = float(self._expect_number("expected chance probability").value)
            elif field == "extend":
                extend = self._expect_int("expected extension room count")
            elif field == "once_per_region":
                once_per_region = self._expect_bool()
            elif field == "allowed_room_rules":
                allowed_room_rules = self._parse_ident_list()
            else:
                self._error(
                    f"unknown nested room field {field!r}",
                    hint="expected parent, chance, extend, once_per_region or "
                         "allowed_room_rules",
                )
            self._consume_semicolon()

        end = self._expect_symbol(RBRACE, "expected '}' after nested room")
        return NestedRoom(
            name=name_token.text,
            parent=explicit_parent,
            chance=chance,
            extend=extend,
            once_per_region=once_per_region,
            allowed_room_rules=allowed_room_rules,
            span=self._span(start, end),
        )

    def _parse_ident_list(self) -> list[str]:
        self._expect_symbol(LBRACKET, "expected '[' before identifier list")
        values: list[str] = []
        if self.current.kind == RBRACKET:
            self._advance()
            return values
        while True:
            values.append(self._expect_ident("expected identifier in list").text)
            if self.current.kind == COMMA:
                self._advance()
                continue
            break
        self._expect_symbol(RBRACKET, "expected ']' after identifier list")
        return values

    def _parse_room_rule(self) -> RoomRule:
        start = self._expect_keyword("room_rule")
        name_token = self._expect_ident("expected room rule name")
        self._expect_symbol(LBRACE, "expected '{' after room rule name")
        allow_nested = False
        seen: set[str] = set()
        while self.current.kind != RBRACE:
            if self.current.kind == EOF:
                self._error("unterminated room_rule block")
            field = self._expect_ident("expected room rule field").text
            if field in seen:
                self._error(f"duplicate room rule field {field!r}")
            seen.add(field)
            if field == "allow_nested":
                allow_nested = self._expect_bool()
            else:
                self._error(
                    f"unknown room rule field {field!r}",
                    hint="expected allow_nested",
                )
            self._consume_semicolon()
        end = self._expect_symbol(RBRACE, "expected '}' after room_rule")
        return RoomRule(name_token.text, allow_nested, self._span(start, end))


def parse_source(source: str, filename: str = "<input>") -> Program:
    return Parser(tokenize(source), filename).parse()


def parse_file(path: str | Path) -> tuple[Program, str]:
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    return parse_source(source, str(path)), source
