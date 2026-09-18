"""Repository Discovery Engine.

Produces a structured repository inventory without loading raw repository
contents indiscriminately into LLM context.
"""

from pathlib import Path
from typing import Any

from auto_pr.discovery.models import (
    FileCategory,
    DiscoveredFile,
    RepositoryInventory,
)
from auto_pr.discovery.rules import RuleDiscoverer
from auto_pr.discovery.tests import TestCommandDiscoverer
from auto_pr.discovery.symbols import PythonSymbolExtractor

# Standard directory and file exclusions
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "target",
    ".auto_pr_worktrees",
    ".gemini",
}

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".rb",
    ".php",
    ".sql",
}

CONFIG_EXTENSIONS = {
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
}

DOC_EXTENSIONS = {
    ".md",
    ".rst",
    ".txt",
}


class RepositoryDiscoveryEngine:
    """Deterministic repository scanner producing structured inventories."""

    def __init__(
        self,
        symbol_extractor: PythonSymbolExtractor | None = None,
        rule_discoverer: RuleDiscoverer | None = None,
        command_discoverer: TestCommandDiscoverer | None = None,
    ) -> None:
        self.symbol_extractor = symbol_extractor or PythonSymbolExtractor()
        self.rule_discoverer = rule_discoverer or RuleDiscoverer()
        self.command_discoverer = command_discoverer or TestCommandDiscoverer()

    def discover_repository(self, repo_path: Path | str) -> RepositoryInventory:
        """Scan repository and construct complete structured inventory."""
        root = Path(repo_path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Target repository path does not exist: {root}")

        source_files: list[DiscoveredFile] = []
        test_files: list[DiscoveredFile] = []
        config_files: list[DiscoveredFile] = []
        doc_files: list[DiscoveredFile] = []
        rule_files: list[DiscoveredFile] = []
        directory_tree: list[str] = []

        # Recursively walk repository respecting exclusions
        for path in sorted(root.rglob("*")):
            rel_parts = path.relative_to(root).parts
            # Check exclusions
            if any(excluded in rel_parts for excluded in DEFAULT_EXCLUDED_DIRS):
                continue

            rel_str = str(path.relative_to(root)).replace("\\", "/")

            if path.is_dir():
                if len(rel_parts) <= 3:
                    directory_tree.append(f"{rel_str}/")
                continue

            if not path.is_file():
                continue

            # Classify file
            category = self._categorize_file(path, rel_str)
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0

            disc_file = DiscoveredFile(
                relative_path=rel_str,
                absolute_path=str(path),
                category=category,
                size_bytes=size_bytes,
                extension=path.suffix.lower(),
            )

            if category == FileCategory.SOURCE:
                source_files.append(disc_file)
            elif category == FileCategory.TEST:
                test_files.append(disc_file)
            elif category == FileCategory.CONFIG:
                config_files.append(disc_file)
            elif category == FileCategory.DOCUMENTATION:
                doc_files.append(disc_file)
            elif category == FileCategory.RULE:
                rule_files.append(disc_file)

        # 2. Extract AST symbols from Python source files (up to max 100 source files)
        all_symbols = []
        for sf in source_files[:100]:
            if sf.extension == ".py":
                file_symbols = self.symbol_extractor.extract_symbols(
                    Path(sf.absolute_path), sf.relative_path
                )
                all_symbols.extend(file_symbols)

        # 3. Discover rules and instructions
        rules = self.rule_discoverer.discover_rules(root)

        # 4. Discover likely build/test/lint commands
        commands = self.command_discoverer.discover_commands(root)

        return RepositoryInventory(
            repo_root=str(root),
            directory_tree=directory_tree,
            source_files=source_files,
            test_files=test_files,
            config_files=config_files,
            doc_files=doc_files,
            rule_files=rule_files,
            detected_commands=commands,
            rules=rules,
            symbols=all_symbols,
            project_metadata={
                "total_source_files": len(source_files),
                "total_test_files": len(test_files),
                "total_config_files": len(config_files),
            },
        )

    def _categorize_file(self, path: Path, rel_path: str) -> FileCategory:
        """Classify a file into a category based on path and extension."""
        name_lower = path.name.lower()
        rel_lower = rel_path.lower()
        ext = path.suffix.lower()

        # Rules
        if name_lower in ("agents.md", "contributing.md", "contributing") or ".agents/rules" in rel_lower:
            return FileCategory.RULE

        # Tests
        if (
            "test" in rel_lower
            or name_lower.startswith("test_")
            or name_lower.endswith("_test.py")
            or ".spec." in name_lower
            or ".test." in name_lower
        ):
            return FileCategory.TEST

        # Documentation
        if name_lower.startswith("readme") or ext in DOC_EXTENSIONS or "docs/" in rel_lower:
            return FileCategory.DOCUMENTATION

        # Configuration
        if (
            name_lower
            in (
                "pyproject.toml",
                "setup.cfg",
                "setup.py",
                "tox.ini",
                "pytest.ini",
                "package.json",
                "tsconfig.json",
                "cargo.toml",
                "go.mod",
                "makefile",
                "dockerfile",
            )
            or ext in CONFIG_EXTENSIONS
        ):
            return FileCategory.CONFIG

        # Source code
        if ext in SOURCE_EXTENSIONS:
            return FileCategory.SOURCE

        return FileCategory.UNKNOWN
