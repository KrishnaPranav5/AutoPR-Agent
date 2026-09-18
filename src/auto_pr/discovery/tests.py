"""Deterministic test and build command discovery from repository configuration."""

import json
from pathlib import Path
from typing import Any

from auto_pr.discovery.models import DiscoveredCommands


class TestCommandDiscoverer:
    """Discovers test suites, frameworks, and execution commands without executing anything."""

    def discover_commands(self, repo_root: Path) -> DiscoveredCommands:
        """Inspect repository configuration files and infer test, lint, and build commands."""
        commands = DiscoveredCommands(test_command="pytest")

        # 1. Python pyproject.toml
        pyproject_path = repo_root / "pyproject.toml"
        if pyproject_path.is_file():
            content = pyproject_path.read_text(encoding="utf-8", errors="replace")
            commands.source_file = "pyproject.toml"

            if "[tool.pytest" in content or "pytest" in content:
                commands.test_command = "pytest"

            if "[tool.ruff" in content or "ruff" in content:
                commands.lint_command = "ruff check ."

            if "[tool.mypy" in content or "mypy" in content:
                commands.typecheck_command = "mypy ."

            if "[build-system]" in content:
                commands.build_command = "pip install -e ."
            return commands

        # 2. pytest.ini / tox.ini / setup.cfg
        for cfg_name in ("pytest.ini", "setup.cfg", "tox.ini"):
            cfg_path = repo_root / cfg_name
            if cfg_path.is_file():
                commands.source_file = cfg_name
                commands.test_command = "pytest"
                return commands

        # 3. Node.js package.json
        package_json_path = repo_root / "package.json"
        if package_json_path.is_file():
            try:
                pkg_data = json.loads(package_json_path.read_text(encoding="utf-8"))
                scripts = pkg_data.get("scripts", {})
                commands.source_file = "package.json"

                if "test" in scripts:
                    commands.test_command = "npm test"
                if "lint" in scripts:
                    commands.lint_command = "npm run lint"
                if "typecheck" in scripts or "check-types" in scripts:
                    commands.typecheck_command = "npm run typecheck"
                if "build" in scripts:
                    commands.build_command = "npm run build"
                return commands
            except Exception:
                pass

        # 4. Rust Cargo.toml
        cargo_path = repo_root / "Cargo.toml"
        if cargo_path.is_file():
            commands.source_file = "Cargo.toml"
            commands.test_command = "cargo test"
            commands.build_command = "cargo build"
            commands.lint_command = "cargo clippy"
            return commands

        # 5. Go go.mod
        go_mod_path = repo_root / "go.mod"
        if go_mod_path.is_file():
            commands.source_file = "go.mod"
            commands.test_command = "go test ./..."
            commands.build_command = "go build ./..."
            return commands

        # Default fallback
        return commands
