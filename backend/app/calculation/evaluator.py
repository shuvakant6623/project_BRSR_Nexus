"""Safe, deterministic formula evaluator (spec §12).

NO eval(), no exec, no attribute access, no names beyond the resolver.
Grammar (recursive descent, all arithmetic in Decimal):

    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor)*
    factor := NUMBER | IDENT | '(' expr ')' | '-' factor

IDENT covers metric codes (which contain hyphens, e.g.
C-P6-GRID-RENEWABLE-MWH) and constant names (DIESEL_EF_KG_PER_LITRE).
Anything the resolver does not know raises CalculationError — missing inputs
never silently become zero.
"""
import re
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from typing import Callable

getcontext().prec = 28

QUANT = Decimal("0.00000001")

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<number>\d+(?:\.\d+)?)|(?P<ident>[A-Za-z][A-Za-z0-9_-]*)"
    r"|(?P<op>[+\-*/()]))"
)


class CalculationError(Exception):
    pass


def tokenize(expression: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expression):
        match = _TOKEN_RE.match(expression, pos)
        if match is None:
            if expression[pos:].strip() == "":
                break
            raise CalculationError(f"Formula contains invalid token at position {pos}")
        pos = match.end()
        if match.group("number") is not None:
            tokens.append(("number", match.group("number")))
        elif match.group("ident") is not None:
            tokens.append(("ident", match.group("ident")))
        else:
            tokens.append(("op", match.group("op")))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], resolve: Callable[[str], Decimal]):
        self.tokens = tokens
        self.pos = 0
        self.resolve = resolve

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise CalculationError("Formula ended unexpectedly")
        self.pos += 1
        return token

    def parse(self) -> Decimal:
        if not self.tokens:
            raise CalculationError("Formula is empty")
        result = self.expr()
        if self.peek() is not None:
            raise CalculationError(f"Unexpected token {self.peek()!r} in formula")
        return result

    def expr(self) -> Decimal:
        value = self.term()
        while True:
            token = self.peek()
            if token not in (("op", "+"), ("op", "-")):
                break
            self.next()
            rhs = self.term()
            value = value + rhs if token == ("op", "+") else value - rhs
        return value

    def term(self) -> Decimal:
        value = self.factor()
        while True:
            token = self.peek()
            if token not in (("op", "*"), ("op", "/")):
                break
            self.next()
            rhs = self.factor()
            if token == ("op", "*"):
                value = value * rhs
            else:
                if rhs == 0:
                    raise CalculationError("Division by zero in formula")
                value = value / rhs
        return value

    def factor(self) -> Decimal:
        kind, text = self.next()
        if kind == "number":
            return Decimal(text)
        if kind == "ident":
            return self.resolve(text)
        if kind == "op" and text == "(":
            value = self.expr()
            kind2, text2 = self.next()
            if (kind2, text2) != ("op", ")"):
                raise CalculationError("Unbalanced parenthesis in formula")
            return value
        if kind == "op" and text == "-":
            return -self.factor()
        if kind == "op" and text == "+":
            return self.factor()
        raise CalculationError(f"Unexpected token {text!r} in formula")


def evaluate(
    expression: str,
    resolve: Callable[[str], Decimal],
) -> Decimal:
    """Evaluate a formula expression with a variable resolver. Deterministic:
    same expression + same inputs + same resolver table = same result."""
    return _Parser(tokenize(expression), resolve).parse().quantize(QUANT, rounding=ROUND_HALF_EVEN)
