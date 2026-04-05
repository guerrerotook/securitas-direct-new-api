"""Architecture enforcement tests for the securitas_direct_new_api package.

AST-level tests ensuring type safety conventions are maintained:
- No bare ``dict`` without type parameters in annotations
- No blanket ``# type: ignore`` without specific error codes
- Standalone ``Any`` usage tracked to prevent regression

Borrowed from the verisure-italy pattern.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

CLIENT_PACKAGE = Path("custom_components/securitas/securitas_direct_new_api")

# Pydantic validators legitimately use bare dict/Any in signatures
_VALIDATOR_DECORATORS = frozenset({"field_validator", "model_validator", "validator"})


def _python_files() -> list[Path]:
    """Return all .py files in the client package (excluding examples)."""
    return [p for p in CLIENT_PACKAGE.glob("*.py") if p.name != "__init__.py"]


def _decorator_name(node: ast.expr) -> str:
    """Extract the decorator name from an AST node.

    Handles both simple decorators (``@foo``) and call decorators
    (``@foo(...)`` / ``@module.foo(...)``).
    """
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_validator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function is decorated with a Pydantic validator."""
    return bool(
        _VALIDATOR_DECORATORS & {_decorator_name(d) for d in node.decorator_list}
    )


def _has_bare_dict(node: ast.expr) -> bool:
    """Return True if the AST node contains a bare ``dict`` anywhere.

    Checks the node itself and recurses into container types like
    ``list[dict]``, ``dict[str, dict]``, ``tuple[dict, ...]``, and
    union types (``dict | None``).
    """
    # Bare dict
    if isinstance(node, ast.Name) and node.id == "dict":
        return True
    # dict | None (BinOp with | operator)
    if isinstance(node, ast.BinOp):
        return _has_bare_dict(node.left) or _has_bare_dict(node.right)
    # Container types: list[dict], dict[str, dict], tuple[dict, ...], etc.
    if isinstance(node, ast.Subscript):
        # Check the slice (type parameters)
        slc = node.slice
        if isinstance(slc, ast.Tuple):
            return any(_has_bare_dict(elt) for elt in slc.elts)
        return _has_bare_dict(slc)
    return False


def _is_standalone_any(node: ast.expr) -> bool:
    """Return True if the node is standalone ``Any`` (not inside a container)."""
    # Bare Any
    if isinstance(node, ast.Name) and node.id == "Any":
        return True
    # Any | None (BinOp)
    if isinstance(node, ast.BinOp):
        return _is_standalone_any(node.left) or _is_standalone_any(node.right)
    return False


class TestNoBareDict:
    """Bare ``dict`` without type parameters must not appear in annotations.

    Use ``dict[str, Any]`` or a more specific type instead.
    """

    def test_no_bare_dict_in_annotations(self):
        """Every ``dict`` annotation must have type parameters."""
        violations: list[str] = []

        for path in _python_files():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # Skip Pydantic validator methods
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _is_validator(node):
                        continue

                    # Check function annotations (params + return)
                    annotations = [
                        (arg.annotation, arg.arg)
                        for arg in node.args.args
                        if arg.annotation
                    ]
                    if node.returns:
                        annotations.append((node.returns, "<return>"))

                    for ann, name in annotations:
                        if _has_bare_dict(ann):
                            violations.append(
                                f"{path.name}:{node.lineno} "
                                f"({node.name}, param {name!r})"
                            )

                # Check variable annotations
                if isinstance(node, ast.AnnAssign) and node.annotation:
                    if _has_bare_dict(node.annotation):
                        target = ast.dump(node.target) if node.target else "?"
                        violations.append(
                            f"{path.name}:{node.lineno} (variable {target})"
                        )

        assert not violations, (
            "Bare `dict` without type parameters found in annotations:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestNoBlanketTypeIgnore:
    """``# type: ignore`` comments must specify error codes.

    Use ``# type: ignore[specific-error]`` instead of blanket suppression.
    """

    _BLANKET_PATTERN = re.compile(r"#\s*type:\s*ignore(?!\[)")

    def test_no_blanket_type_ignore(self):
        """Every ``# type: ignore`` must have a bracketed error code."""
        violations: list[str] = []

        for path in _python_files():
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if self._BLANKET_PATTERN.search(line):
                    violations.append(f"{path.name}:{i}: {line.strip()}")

        assert not violations, (
            "Blanket `# type: ignore` without error codes found:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestAnyUsageBaseline:
    """Track standalone ``Any`` usage to prevent regression.

    ``dict[str, Any]`` and ``list[Any]`` are acceptable — JSON data
    requires ``Any`` as a type parameter. Standalone ``Any`` (as a
    parameter type, return type, or variable annotation) should be
    minimised.

    This test tracks the current count and fails if it increases,
    preventing new standalone ``Any`` from creeping in.
    """

    # Current baseline — update this number only when deliberately
    # adding or removing standalone Any annotations.
    _BASELINE = 9

    def test_standalone_any_does_not_increase(self):
        """Count of standalone ``Any`` annotations must not exceed baseline."""
        count = 0

        for path in _python_files():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _is_validator(node):
                        continue

                    # Check params
                    for arg in node.args.args:
                        if arg.annotation and _is_standalone_any(arg.annotation):
                            count += 1

                    # Check return
                    if node.returns and _is_standalone_any(node.returns):
                        count += 1

                # Check variable and class attribute annotations
                elif isinstance(node, ast.AnnAssign):
                    if node.annotation and _is_standalone_any(node.annotation):
                        count += 1

        assert count <= self._BASELINE, (
            f"Standalone `Any` count ({count}) exceeds baseline "
            f"({self._BASELINE}). If you intentionally added `Any`, "
            f"update _BASELINE. Otherwise, use a more specific type."
        )
