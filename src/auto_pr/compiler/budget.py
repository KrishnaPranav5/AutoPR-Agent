"""Token budgeting and extract trimmer for the Context Compiler.

Ensures the ContextPack remains within configured token budgets and never
silently blows up model context limits.
"""

from pathlib import Path
from auto_pr.core.models import FileExtract, SymbolInfo
from auto_pr.discovery.models import DiscoveredFile


def estimate_tokens(text: str) -> int:
    """Heuristic token estimation (~4 characters per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class EvidenceBudgetManager:
    """Manages token allocation and extract trimming for the ContextPack."""

    def __init__(self, default_budget: int = 8000) -> None:
        self.default_budget = default_budget

    def build_file_extracts(
        self,
        ranked_files: list[tuple[DiscoveredFile, float, list[SymbolInfo]]],
        token_budget: int | None = None,
    ) -> tuple[list[FileExtract], int]:
        """Extract focused code spans from ranked files within token budget.

        Returns:
            tuple of (list_of_FileExtracts, total_tokens_used)
        """
        budget = token_budget or self.default_budget
        tokens_used = 0
        extracts: list[FileExtract] = []

        for disc_file, score, matched_symbols in ranked_files:
            file_path = Path(disc_file.absolute_path)
            if not file_path.is_file():
                continue

            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            total_lines = len(lines)
            if total_lines == 0:
                continue

            # Determine line window based on symbols or default window
            start_line, end_line, symbol_name = self._compute_line_window(
                total_lines, matched_symbols
            )
            # 1-indexed to 0-indexed slicing
            selected_lines = lines[start_line - 1 : end_line]
            content = "\n".join(selected_lines)

            cost = estimate_tokens(content)
            # If adding this extract exceeds budget, check if we can trim or stop
            if tokens_used + cost > budget:
                # Attempt smaller window (max 30 lines) if room exists
                remaining = budget - tokens_used
                if remaining > 100 and len(selected_lines) > 30:
                    trimmed_lines = selected_lines[:30]
                    content = "\n".join(trimmed_lines) + "\n... [TRIMMED TO REMAIN IN BUDGET]"
                    end_line = start_line + len(trimmed_lines) - 1
                    cost = estimate_tokens(content)
                    if tokens_used + cost <= budget:
                        extracts.append(
                            FileExtract(
                                file_path=disc_file.relative_path,
                                start_line=start_line,
                                end_line=end_line,
                                content=content,
                                relevance_score=score,
                                symbol_name=symbol_name,
                            )
                        )
                        tokens_used += cost
                # Stop adding further file extracts once budget limit is reached
                break

            extracts.append(
                FileExtract(
                    file_path=disc_file.relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                    relevance_score=score,
                    symbol_name=symbol_name,
                )
            )
            tokens_used += cost

        return extracts, tokens_used

    def _compute_line_window(
        self,
        total_lines: int,
        symbols: list[SymbolInfo],
    ) -> tuple[int, int, str | None]:
        """Compute the most relevant start and end line range for a file."""
        if not symbols:
            # If whole file is small (<= 120 lines), include everything
            if total_lines <= 120:
                return 1, total_lines, None
            # Otherwise return the top 100 lines
            return 1, 100, None

        # Pick the most prominent matched symbol (prefer class or first function)
        primary_sym = symbols[0]
        sym_start = primary_sym.line_start
        sym_end = primary_sym.line_end

        # Add 10 lines of context padding
        start_line = max(1, sym_start - 10)
        end_line = min(total_lines, sym_end + 10)

        # Cap individual window at 150 lines
        if end_line - start_line > 150:
            end_line = start_line + 150

        return start_line, end_line, primary_sym.name
