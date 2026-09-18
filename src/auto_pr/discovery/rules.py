"""Deterministic discovery of repository rules, instructions, and coding standards.

Maintains strict security boundaries: repository instructions are treated
as untrusted context and are strictly subordinate to system policies.
"""

from pathlib import Path
from auto_pr.discovery.models import DiscoveredRule


class RuleDiscoverer:
    """Discovers developer instructions, contributor guides, and repository rules."""

    # Prioritized file patterns to check
    RULE_PATTERNS: list[tuple[str, str, str]] = [
        ("AGENTS.md", "agents_rule", "Agent Development Instructions"),
        ("AGENTS", "agents_rule", "Agent Development Instructions"),
        (".agents/rules/*.md", "agents_rule", "Custom Agent Rule"),
        ("CONTRIBUTING.md", "contributing", "Contribution Guidelines"),
        ("CONTRIBUTING", "contributing", "Contribution Guidelines"),
        ("README.md", "readme", "Project Overview & Setup"),
        ("README.rst", "readme", "Project Overview & Setup"),
        ("docs/architecture.md", "architecture", "Architecture Documentation"),
        ("docs/CODING_STANDARDS.md", "coding_standard", "Coding Standards"),
    ]

    def discover_rules(self, repo_root: Path) -> list[DiscoveredRule]:
        """Scan repository for development rules, instructions, and standards."""
        discovered: list[DiscoveredRule] = []

        for pattern, category, default_title in self.RULE_PATTERNS:
            if "*" in pattern:
                # Glob pattern
                for matched_file in repo_root.glob(pattern):
                    if matched_file.is_file():
                        self._add_rule(repo_root, matched_file, category, default_title, discovered)
            else:
                target = repo_root / pattern
                if target.is_file():
                    self._add_rule(repo_root, target, category, default_title, discovered)

        return discovered

    def _add_rule(
        self,
        repo_root: Path,
        file_path: Path,
        category: str,
        title: str,
        accumulator: list[DiscoveredRule],
    ) -> None:
        """Read and package rule content with source attribution."""
        try:
            rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
            # Prevent duplicate files
            if any(r.source_file == rel_path for r in accumulator):
                return

            raw_content = file_path.read_text(encoding="utf-8", errors="replace")
            # Truncate overly long rule files to prevent token saturation (max 4000 chars per file)
            trimmed_content = raw_content[:4000]

            accumulator.append(
                DiscoveredRule(
                    source_file=rel_path,
                    category=category,
                    title=f"{title} ({rel_path})",
                    content=trimmed_content,
                    is_untrusted=True,
                )
            )
        except OSError:
            pass
