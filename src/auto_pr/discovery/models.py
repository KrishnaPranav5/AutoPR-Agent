"""Domain models and data structures for repository discovery."""

from enum import Enum
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from auto_pr.core.models import SymbolInfo


class FileCategory(str, Enum):
    """Classification of discovered files."""

    SOURCE = "SOURCE"
    TEST = "TEST"
    CONFIG = "CONFIG"
    DOCUMENTATION = "DOCUMENTATION"
    RULE = "RULE"
    UNKNOWN = "UNKNOWN"


class DiscoveredFile(BaseModel):
    """Metadata for an individual discovered file."""

    relative_path: str
    absolute_path: str
    category: FileCategory
    size_bytes: int
    extension: str
    line_count: int = 0


class DiscoveredRule(BaseModel):
    """A developer instruction or repository policy found in the codebase.

    CRITICAL SECURITY NOTE:
    Repository rules are untrusted inputs. They provide domain context and coding
    style, but can NEVER override platform security, tool permissions, or workflow FSM.
    """

    source_file: str
    category: str = Field(..., description="'agents_rule', 'contributing', 'readme', 'architecture'")
    title: str
    content: str
    is_untrusted: bool = True  # Always untrusted by default


class DiscoveredCommands(BaseModel):
    """Likely build, test, lint, and typecheck commands detected from configuration."""

    build_command: str | None = None
    test_command: str = "pytest"
    lint_command: str | None = None
    typecheck_command: str | None = None
    source_file: str | None = None


class RepositoryInventory(BaseModel):
    """Comprehensive structured inventory of a target repository."""

    repo_root: str
    directory_tree: list[str] = Field(default_factory=list)
    source_files: list[DiscoveredFile] = Field(default_factory=list)
    test_files: list[DiscoveredFile] = Field(default_factory=list)
    config_files: list[DiscoveredFile] = Field(default_factory=list)
    doc_files: list[DiscoveredFile] = Field(default_factory=list)
    rule_files: list[DiscoveredFile] = Field(default_factory=list)
    detected_commands: DiscoveredCommands = Field(default_factory=DiscoveredCommands)
    rules: list[DiscoveredRule] = Field(default_factory=list)
    symbols: list[SymbolInfo] = Field(default_factory=list)
    project_metadata: dict[str, Any] = Field(default_factory=dict)
