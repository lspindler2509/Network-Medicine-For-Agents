"""Explicit trusted Python lambda arguments."""

from .objects import ObjectError


def parse_callback(value):
    """Compile an explicitly requested, trusted Python lambda (not a sandbox)."""
    import ast

    expression = value[len("@lambda:") :]
    try:
        tree = ast.parse(expression, mode="eval")
        if not isinstance(tree.body, ast.Lambda):
            raise ValueError("expected a lambda expression")
        return eval(compile(tree, "<netmed-callback>", "eval"), {})
    except (SyntaxError, ValueError) as error:
        raise ObjectError(f"Invalid @lambda callback: {error}") from error
