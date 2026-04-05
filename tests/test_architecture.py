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
INTEGRATION_PACKAGE = Path("custom_components/securitas")

# Pydantic validators legitimately use bare dict/Any in signatures
_VALIDATOR_DECORATORS = frozenset({"field_validator", "model_validator", "validator"})


def _client_files() -> list[Path]:
    """Return all .py files in the client package (excluding __init__.py)."""
    return [p for p in CLIENT_PACKAGE.glob("*.py") if p.name != "__init__.py"]


def _integration_files() -> list[Path]:
    """Return top-level .py files in the integration package.

    Excludes the ``securitas_direct_new_api`` sub-package (covered by
    ``_client_files``) and includes ``__init__.py`` since it contains
    substantial setup logic.
    """
    return sorted(p for p in INTEGRATION_PACKAGE.glob("*.py") if p.is_file())


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


def _find_bare_dict_violations(files: list[Path]) -> list[str]:
    """Scan *files* and return a list of bare-dict annotation violations."""
    violations: list[str] = []

    for path in files:
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
                            f"{path.name}:{node.lineno} ({node.name}, param {name!r})"
                        )

            # Check variable annotations
            if isinstance(node, ast.AnnAssign) and node.annotation:
                if _has_bare_dict(node.annotation):
                    target = ast.dump(node.target) if node.target else "?"
                    violations.append(f"{path.name}:{node.lineno} (variable {target})")

    return violations


def _find_blanket_type_ignore(files: list[Path]) -> list[str]:
    """Scan *files* and return blanket ``# type: ignore`` violations."""
    pattern = re.compile(r"#\s*type:\s*ignore(?!\[)")
    violations: list[str] = []

    for path in files:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                violations.append(f"{path.name}:{i}: {line.strip()}")

    return violations


def _count_standalone_any(files: list[Path]) -> int:
    """Count standalone ``Any`` annotations in *files*."""
    count = 0

    for path in files:
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

    return count


# ── Client package tests ────────────────────────────────────────────────────


class TestClientNoBareDict:
    """Bare ``dict`` without type parameters must not appear in client annotations."""

    def test_no_bare_dict_in_annotations(self):
        """Every ``dict`` annotation must have type parameters."""
        violations = _find_bare_dict_violations(_client_files())
        assert not violations, (
            "Bare `dict` without type parameters found in client annotations:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestClientNoBlanketTypeIgnore:
    """``# type: ignore`` comments must specify error codes (client package)."""

    def test_no_blanket_type_ignore(self):
        """Every ``# type: ignore`` must have a bracketed error code."""
        violations = _find_blanket_type_ignore(_client_files())
        assert not violations, (
            "Blanket `# type: ignore` without error codes found in client:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestClientAnyUsageBaseline:
    """Track standalone ``Any`` usage in the client package.

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
        count = _count_standalone_any(_client_files())
        assert count <= self._BASELINE, (
            f"Standalone `Any` count ({count}) exceeds client baseline "
            f"({self._BASELINE}). If you intentionally added `Any`, "
            f"update _BASELINE. Otherwise, use a more specific type."
        )


# ── Integration package tests ───────────────────────────────────────────────


class TestIntegrationNoBareDict:
    """Bare ``dict`` without type parameters must not appear in integration annotations."""

    def test_no_bare_dict_in_annotations(self):
        """Every ``dict`` annotation must have type parameters."""
        violations = _find_bare_dict_violations(_integration_files())
        assert not violations, (
            "Bare `dict` without type parameters found in integration annotations:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestIntegrationNoBlanketTypeIgnore:
    """``# type: ignore`` comments must specify error codes (integration)."""

    def test_no_blanket_type_ignore(self):
        """Every ``# type: ignore`` must have a bracketed error code."""
        violations = _find_blanket_type_ignore(_integration_files())
        assert not violations, (
            "Blanket `# type: ignore` without error codes found in integration:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestIntegrationAnyUsageBaseline:
    """Track standalone ``Any`` usage in the integration package.

    Integration files use more ``Any`` than the client package due to
    Home Assistant framework callbacks and generic dict configs.
    """

    # Current baseline — update this number only when deliberately
    # adding or removing standalone Any annotations.
    _BASELINE = 9

    def test_standalone_any_does_not_increase(self):
        """Count of standalone ``Any`` annotations must not exceed baseline."""
        count = _count_standalone_any(_integration_files())
        assert count <= self._BASELINE, (
            f"Standalone `Any` count ({count}) exceeds integration baseline "
            f"({self._BASELINE}). If you intentionally added `Any`, "
            f"update _BASELINE. Otherwise, use a more specific type."
        )
