"""AST-based symbol extraction for repository source files.

Extracts classes, functions, methods, docstrings, and imports safely
without executing any code.
"""

import ast
import logging
from pathlib import Path
from typing import Protocol

from auto_pr.core.models import SymbolInfo

logger = logging.getLogger(__name__)


class SymbolExtractor(Protocol):
    """Protocol for language-specific symbol extractors."""

    def extract_symbols(self, file_path: Path, relative_path: str) -> list[SymbolInfo]:
        ...


class PythonSymbolExtractor:
    """AST-based symbol extractor for Python source files."""

    def extract_symbols(self, file_path: Path, relative_path: str) -> list[SymbolInfo]:
        """Extract classes, functions, methods, and imports from a Python file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError, OSError) as err:
            logger.warning("Could not parse %s for symbols: %s", relative_path, err)
            return []

        symbols: list[SymbolInfo] = []

        # Module docstring
        module_doc = ast.get_docstring(tree)
        if module_doc:
            symbols.append(
                SymbolInfo(
                    name=file_path.stem,
                    kind="module",
                    file_path=relative_path,
                    line_start=1,
                    line_end=1,
                    docstring=module_doc[:200],
                )
            )

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node)
                bases = [self._format_node(b) for b in node.bases]
                sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="class",
                        file_path=relative_path,
                        line_start=node.lineno,
                        line_end=getattr(node, "end_lineno", node.lineno),
                        signature=sig,
                        docstring=doc[:200] if doc else None,
                    )
                )

                # Extract methods inside class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_doc = ast.get_docstring(item)
                        sig = self._format_func_sig(item)
                        symbols.append(
                            SymbolInfo(
                                name=f"{node.name}.{item.name}",
                                kind="method",
                                file_path=relative_path,
                                line_start=item.lineno,
                                line_end=getattr(item, "end_lineno", item.lineno),
                                signature=sig,
                                docstring=method_doc[:200] if method_doc else None,
                            )
                        )

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                sig = self._format_func_sig(node)
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="function",
                        file_path=relative_path,
                        line_start=node.lineno,
                        line_end=getattr(node, "end_lineno", node.lineno),
                        signature=sig,
                        docstring=doc[:200] if doc else None,
                    )
                )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    symbols.append(
                        SymbolInfo(
                            name=alias.name,
                            kind="import",
                            file_path=relative_path,
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                            signature=f"import {alias.name}",
                        )
                    )

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    symbols.append(
                        SymbolInfo(
                            name=f"{module}.{alias.name}" if module else alias.name,
                            kind="import",
                            file_path=relative_path,
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                            signature=f"from {module} import {alias.name}",
                        )
                    )

        return symbols

    def _format_func_sig(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Helper to format function signature with type annotations and return type."""
        async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        try:
            args_str = ast.unparse(node.args)
            ret_str = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            return f"{async_prefix}def {node.name}({args_str}){ret_str}"
        except Exception:
            args = [a.arg for a in node.args.args]
            return f"{async_prefix}def {node.name}({', '.join(args)})"

    def _format_node(self, node: ast.AST) -> str:
        """Helper to format simple AST expressions to string."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._format_node(node.value)}.{node.attr}"
        return "..."
