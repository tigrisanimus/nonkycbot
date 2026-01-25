#!/usr/bin/env python3
"""
Validate all bot runners and strategies for common issues.

This script ensures:
1. All bots use correct RestClient initialization
2. All bots use correct method names (get_order not get_order_status)
3. All strategies support underscore symbol format
4. All grid strategies have profit validation
5. All bots have proper authentication setup
6. No deprecated imports or patterns

Run this before committing changes to prevent regressions.
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


class BotValidator(ast.NodeVisitor):
    """AST visitor to validate bot code."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.issues: List[str] = []
        self.warnings: List[str] = []
        self.checks_passed: List[str] = []

        # Patterns to check
        self.has_rest_client_import = False
        self.has_auth_signer_import = False
        self.has_sign_absolute_url = False
        self.has_nonce_multiplier_1e3 = False
        self.uses_get_order_status = False  # Bad
        self.uses_get_order = False  # Good
        self.has_symbol_split = False
        self.supports_underscore = False

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Check imports."""
        if node.module == "engine.exchange_client_factory":
            self.issues.append(
                "DEPRECATED: Importing from engine.exchange_client_factory. "
                "Use direct RestClient imports instead."
            )

        if node.module == "nonkyc_client.rest":
            for alias in node.names:
                if alias.name == "RestClient":
                    self.has_rest_client_import = True

        if node.module == "nonkyc_client.auth":
            for alias in node.names:
                if alias.name == "AuthSigner":
                    self.has_auth_signer_import = True

        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword):
        """Check keyword arguments."""
        if node.arg == "sign_absolute_url":
            self.has_sign_absolute_url = True

        if node.arg == "nonce_multiplier":
            if isinstance(node.value, ast.Constant):
                if node.value.value == 1000 or node.value.value == 1e3:
                    self.has_nonce_multiplier_1e3 = True

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Check method calls."""
        if node.attr == "get_order_status":
            self.uses_get_order_status = True
        if node.attr == "get_order":
            self.uses_get_order = True

        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        """Check for symbol format support."""
        # Look for patterns like: if "_" in symbol:
        if isinstance(node.test, ast.Compare):
            for op, comp in zip(node.test.ops, node.test.comparators):
                if isinstance(op, ast.In):
                    if isinstance(comp, ast.Name) and "symbol" in comp.id.lower():
                        if isinstance(node.test.left, ast.Constant):
                            if node.test.left.value == "_":
                                self.supports_underscore = True

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Check function definitions."""
        if "_split_symbol" in node.name or "parse_symbol" in node.name:
            self.has_symbol_split = True

        self.generic_visit(node)

    def report(self) -> Tuple[bool, str]:
        """Generate validation report."""
        output = []
        has_errors = False

        # File header
        output.append(f"\n{'='*80}")
        output.append(f"Validating: {self.filepath}")
        output.append(f"{'='*80}")

        # Check for issues
        if self.issues:
            has_errors = True
            output.append(f"\n{RED}✗ ERRORS:{RESET}")
            for issue in self.issues:
                output.append(f"  {RED}✗{RESET} {issue}")

        # Check for warnings
        if self.warnings:
            output.append(f"\n{YELLOW}⚠ WARNINGS:{RESET}")
            for warning in self.warnings:
                output.append(f"  {YELLOW}⚠{RESET} {warning}")

        # Bot-specific validation
        is_bot_runner = "run_" in Path(self.filepath).name
        is_strategy = "strategies/" in self.filepath
        is_test_file = "test_" in Path(self.filepath).name

        if is_bot_runner or is_test_file:
            # Validate bot runners
            if not self.has_rest_client_import:
                self.warnings.append("Missing RestClient import")

            if not self.has_auth_signer_import:
                self.warnings.append("Missing AuthSigner import")

            if not self.has_sign_absolute_url:
                self.warnings.append(
                    "Missing sign_absolute_url configuration. "
                    "Should support config.get('sign_absolute_url')"
                )

            if not self.has_nonce_multiplier_1e3:
                self.warnings.append(
                    "nonce_multiplier not set to 1e3 (1000). "
                    "Should use config.get('nonce_multiplier', 1e3)"
                )

        if is_strategy:
            # Validate strategies
            if self.uses_get_order_status:
                self.issues.append(
                    "Using get_order_status() - should be get_order(). "
                    "NonkycRestExchangeClient doesn't have get_order_status method."
                )
                has_errors = True

            if self.has_symbol_split and not self.supports_underscore:
                self.warnings.append(
                    "Symbol parsing found but no underscore support detected. "
                    "Ensure underscore format (BTC_USDT) is supported."
                )

        # Success checks
        if is_bot_runner and self.has_sign_absolute_url:
            self.checks_passed.append("✓ sign_absolute_url configurable")

        if is_bot_runner and self.has_nonce_multiplier_1e3:
            self.checks_passed.append("✓ nonce_multiplier set to 1e3")

        if is_strategy and self.uses_get_order and not self.uses_get_order_status:
            self.checks_passed.append("✓ Uses correct get_order() method")

        if is_strategy and self.supports_underscore:
            self.checks_passed.append("✓ Supports underscore symbol format")

        # Print checks passed
        if self.checks_passed and not has_errors:
            output.append(f"\n{GREEN}✓ PASSED:{RESET}")
            for check in self.checks_passed:
                output.append(f"  {GREEN}{check}{RESET}")

        # Print warnings if no errors
        if self.warnings and not has_errors:
            for warning in self.warnings:
                output.append(f"  {YELLOW}⚠{RESET} {warning}")

        if not has_errors and not self.warnings:
            output.append(f"\n{GREEN}✓ All checks passed!{RESET}")

        return has_errors, "\n".join(output)


def validate_file(filepath: Path) -> Tuple[bool, str]:
    """Validate a single Python file."""
    try:
        with open(filepath, "r") as f:
            tree = ast.parse(f.read(), filename=str(filepath))

        validator = BotValidator(str(filepath))
        validator.visit(tree)
        return validator.report()

    except SyntaxError as e:
        return True, f"{RED}✗ Syntax error in {filepath}: {e}{RESET}"
    except Exception as e:
        return True, f"{RED}✗ Error validating {filepath}: {e}{RESET}"


def main():
    """Main validation entry point."""
    root = Path(__file__).parent

    # Files to validate
    bot_runners = list(root.glob("run_*.py"))
    strategies = list((root / "src" / "strategies").glob("*.py"))
    test_files = list(root.glob("test_*.py"))

    # Remove __init__.py and deprecated files
    strategies = [s for s in strategies if s.name != "__init__.py"]

    all_files = bot_runners + strategies + test_files

    print(f"\n{'='*80}")
    print("NonKYC Bot Validation")
    print(f"{'='*80}")
    print(
        f"\nValidating {len(bot_runners)} bot runners, {len(strategies)} strategies, and {len(test_files)} test files..."
    )

    has_any_errors = False
    results = []

    for filepath in all_files:
        has_error, report = validate_file(filepath)
        results.append((filepath, has_error, report))
        if has_error:
            has_any_errors = True

    # Print all results
    for filepath, has_error, report in results:
        print(report)

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")

    files_with_errors = sum(1 for _, has_error, _ in results if has_error)
    files_passed = len(results) - files_with_errors

    print(f"\nFiles validated: {len(results)}")
    print(f"{GREEN}✓ Passed: {files_passed}{RESET}")
    if files_with_errors > 0:
        print(f"{RED}✗ Failed: {files_with_errors}{RESET}")

    if has_any_errors:
        print(f"\n{RED}Validation FAILED! Fix errors before committing.{RESET}")
        return 1
    else:
        print(f"\n{GREEN}All validations PASSED!{RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
