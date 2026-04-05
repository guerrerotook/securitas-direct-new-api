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


def _python_files() -> list[Path]:
    """Return all .py files in the client package (excluding examples)."""
    return [p for p in CLIENT_PACKAGE.glob("*.py") if p.name != "__init__.py"]


class TestNoBareDict:
    """Bare ``dict`` without type parameters must not appear in annotations.

    Use ``dict[str, Any]`` or a more specific type instead.
    """

    # Pydantic validators legitimately use bare dict in signatures
    _VALIDATOR_DECORATORS = frozenset(
        {"field_validator", "model_validator", "validator"}
    )

    def test_no_bare_dict_in_annotations(self):
        """Every ``dict`` annotation must have type parameters."""
        violations: list[str] = []

        for path in _python_files():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # Skip Pydantic validator methods
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorators = [
                        getattr(d, "attr", getattr(d, "id", ""))
                        for d in node.decorator_list
                    ]
                    if self._VALIDATOR_DECORATORS & set(decorators):
                        continue

                # Check function annotations (params + return)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    annotations = [
                        (arg.annotation, arg.arg)
                        for arg in node.args.args
                        if arg.annotation
                    ]
                    if node.returns:
                        annotations.append((node.returns, "<return>"))

                    for ann, name in annotations:
                        if self._is_bare_dict(ann):
                            violations.append(
                                f"{path.name}:{node.lineno} "
                                f"({node.name}, param {name!r})"
                            )

                # Check variable annotations
                if isinstance(node, ast.AnnAssign) and node.annotation:
                    if self._is_bare_dict(node.annotation):
                        target = ast.dump(node.target) if node.target else "?"
                        violations.append(
                            f"{path.name}:{node.lineno} (variable {target})"
                        )

        assert not violations, (
            "Bare `dict` without type parameters found in annotations:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    @staticmethod
    def _is_bare_dict(node: ast.expr) -> bool:
        """Return True if the AST node is a bare ``dict`` (no subscript)."""
        # dict
        if isinstance(node, ast.Name) and node.id == "dict":
            return True
        # dict | None  (BinOp with | operator)
        if isinstance(node, ast.BinOp):
            return TestNoBareDict._is_bare_dict(
                node.left
            ) or TestNoBareDict._is_bare_dict(node.right)
        return False


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
    _BASELINE = 15

    # Pydantic validators legitimately use Any
    _VALIDATOR_DECORATORS = frozenset(
        {"field_validator", "model_validator", "validator"}
    )

    def test_standalone_any_does_not_increase(self):
        """Count of standalone ``Any`` annotations must not exceed baseline."""
        count = 0

        for path in _python_files():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                # Skip Pydantic validators
                decorators = [
                    getattr(d, "attr", getattr(d, "id", ""))
                    for d in node.decorator_list
                ]
                if self._VALIDATOR_DECORATORS & set(decorators):
                    continue

                # Check params
                for arg in node.args.args:
                    if arg.annotation and self._is_standalone_any(arg.annotation):
                        count += 1

                # Check return
                if node.returns and self._is_standalone_any(node.returns):
                    count += 1

        assert count <= self._BASELINE, (
            f"Standalone `Any` count ({count}) exceeds baseline "
            f"({self._BASELINE}). If you intentionally added `Any`, "
            f"update _BASELINE. Otherwise, use a more specific type."
        )

    @staticmethod
    def _is_standalone_any(node: ast.expr) -> bool:
        """Return True if the node is standalone ``Any`` (not inside a container)."""
        # Bare Any
        if isinstance(node, ast.Name) and node.id == "Any":
            return True
        # Any | None (BinOp)
        if isinstance(node, ast.BinOp):
            return TestAnyUsageBaseline._is_standalone_any(
                node.left
            ) or TestAnyUsageBaseline._is_standalone_any(node.right)
        return False
