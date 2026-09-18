"""Unit tests for repository discovery, file scanning, and symbol extraction."""

from pathlib import Path
import pytest

from auto_pr.discovery.models import FileCategory
from auto_pr.discovery.inventory import RepositoryDiscoveryEngine
from auto_pr.discovery.symbols import PythonSymbolExtractor
from auto_pr.discovery.tests import TestCommandDiscoverer
from auto_pr.discovery.rules import RuleDiscoverer


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary mock repository with diverse files and directories."""
    repo = tmp_path / "sample_repo"
    repo.mkdir()

    # Source files
    src = repo / "src"
    src.mkdir()
    (src / "calculator.py").write_text(
        '"""Calculator module."""\n\n'
        "import math\n\n"
        "class Calculator:\n"
        '    """Arithmetic calculator."""\n'
        "    def add(self, a: int, b: int) -> int:\n"
        '        """Add two integers."""\n'
        "        return a + b\n\n"
        "    def subtract(self, a: int, b: int) -> int:\n"
        "        return a - b\n",
        encoding="utf-8",
    )
    (src / "utils.py").write_text(
        "def format_result(val: int) -> str:\n    return f'Result: {val}'\n",
        encoding="utf-8",
    )

    # Test files
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_calculator.py").write_text(
        "from src.calculator import Calculator\n\n"
        "def test_add():\n    assert Calculator().add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # Configuration files
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "sample-calculator"\nversion = "1.0.0"\n\n'
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n\n'
        '[tool.ruff]\nline-length = 88\n\n'
        '[tool.mypy]\nstrict = true\n',
        encoding="utf-8",
    )

    # Rules and documentation
    (repo / "README.md").write_text(
        "# Sample Calculator\n\nA simple calculator application.\n",
        encoding="utf-8",
    )
    (repo / "AGENTS.md").write_text(
        "# Agent Instructions\n\nAlways add tests for new arithmetic operations.\n",
        encoding="utf-8",
    )
    (repo / "CONTRIBUTING.md").write_text(
        "# Contributing\n\nFollow PEP8 formatting standards.\n",
        encoding="utf-8",
    )

    # Excluded directories (should be ignored by discovery)
    node_modules = repo / "node_modules"
    node_modules.mkdir()
    (node_modules / "dummy.js").write_text("console.log('ignored');", encoding="utf-8")

    venv_dir = repo / ".venv" / "Lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "site_pkg.py").write_text("# ignored site package", encoding="utf-8")

    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("# git config", encoding="utf-8")

    return repo


def test_repository_inventory_scanning(temp_repo: Path) -> None:
    """Verify repository inventory scanning classifies files properly."""
    engine = RepositoryDiscoveryEngine()
    inv = engine.discover_repository(temp_repo)

    assert inv.repo_root == str(temp_repo.resolve())
    assert len(inv.source_files) == 2  # calculator.py, utils.py
    assert len(inv.test_files) == 1    # test_calculator.py
    assert len(inv.config_files) == 1  # pyproject.toml
    assert len(inv.rule_files) == 2    # AGENTS.md, CONTRIBUTING.md
    assert len(inv.doc_files) >= 1     # README.md


def test_irrelevant_file_exclusion(temp_repo: Path) -> None:
    """Verify that node_modules, .venv, and .git are completely excluded."""
    engine = RepositoryDiscoveryEngine()
    inv = engine.discover_repository(temp_repo)

    all_relative_paths = [
        f.relative_path
        for f in (
            inv.source_files
            + inv.test_files
            + inv.config_files
            + inv.doc_files
            + inv.rule_files
        )
    ]

    for path in all_relative_paths:
        assert not path.startswith("node_modules")
        assert not path.startswith(".venv")
        assert not path.startswith(".git")


def test_python_symbol_extraction(temp_repo: Path) -> None:
    """Verify AST-based symbol extraction captures classes, methods, docstrings, and imports."""
    extractor = PythonSymbolExtractor()
    calc_path = temp_repo / "src" / "calculator.py"

    symbols = extractor.extract_symbols(calc_path, "src/calculator.py")
    symbol_names = [s.name for s in symbols]

    assert "calculator" in symbol_names  # module docstring
    assert "Calculator" in symbol_names  # class
    assert "Calculator.add" in symbol_names  # method
    assert "Calculator.subtract" in symbol_names  # method
    assert "math" in symbol_names  # import

    calc_sym = next(s for s in symbols if s.name == "Calculator")
    assert calc_sym.kind == "class"
    assert calc_sym.docstring == "Arithmetic calculator."

    add_sym = next(s for s in symbols if s.name == "Calculator.add")
    assert add_sym.kind == "method"
    assert "def add(self, a: int, b: int) -> int" in (add_sym.signature or "")


def test_syntax_error_graceful_handling(tmp_path: Path) -> None:
    """Verify that syntax errors in source files do not crash symbol extraction."""
    broken_file = tmp_path / "broken.py"
    broken_file.write_text("def unclosed_function(:\n    broken syntax", encoding="utf-8")

    extractor = PythonSymbolExtractor()
    symbols = extractor.extract_symbols(broken_file, "broken.py")
    assert symbols == []


def test_command_discovery(temp_repo: Path) -> None:
    """Verify test, lint, and typecheck commands are detected from pyproject.toml."""
    discoverer = TestCommandDiscoverer()
    cmds = discoverer.discover_commands(temp_repo)

    assert cmds.test_command == "pytest"
    assert cmds.lint_command == "ruff check ."
    assert cmds.typecheck_command == "mypy ."
    assert cmds.source_file == "pyproject.toml"


def test_rule_and_documentation_discovery(temp_repo: Path) -> None:
    """Verify AGENTS.md, CONTRIBUTING.md, and README.md are discovered with attribution."""
    discoverer = RuleDiscoverer()
    rules = discoverer.discover_rules(temp_repo)

    source_files = [r.source_file for r in rules]
    assert "AGENTS.md" in source_files
    assert "CONTRIBUTING.md" in source_files
    assert "README.md" in source_files

    # Verify all rules are flagged as untrusted
    for r in rules:
        assert r.is_untrusted is True
