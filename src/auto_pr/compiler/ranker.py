"""Deterministic evidence ranking engine.

Ranks repository files, symbols, and rules using deterministic keyword,
symbol, and structural relationship signals without relying on LLMs.
"""

import re
from typing import Set

from auto_pr.core.models import WorkItemSpec, SymbolInfo
from auto_pr.discovery.models import RepositoryInventory, DiscoveredFile

# Common English and programming stop words to ignore during lexical matching
STOP_WORDS: Set[str] = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "can", "could", "should", "would", "will", "shall", "may",
    "might", "must", "with", "from", "by", "about", "as", "into", "like", "through",
    "after", "over", "between", "out", "against", "during", "without", "before",
    "under", "around", "among", "this", "that", "these", "those", "it", "its",
    "def", "class", "return", "import", "from", "self", "none", "true", "false",
}


def extract_keywords(text: str) -> set[str]:
    """Tokenize text into lowercase keywords, stripping punctuation and stop words."""
    words = re.findall(r"[A-Za-z0-9_]+", text.lower())
    # Also split camelCase or snake_case
    tokens: set[str] = set()
    for w in words:
        if len(w) >= 3 and w not in STOP_WORDS:
            tokens.add(w)
            # Split snake_case
            parts = w.split("_")
            if len(parts) > 1:
                tokens.update(p for p in parts if len(p) >= 3 and p not in STOP_WORDS)
    return tokens


class EvidenceRanker:
    """Ranks discovered repository assets against a WorkItemSpec."""

    def rank_inventory(
        self,
        spec: WorkItemSpec,
        inventory: RepositoryInventory,
    ) -> list[tuple[DiscoveredFile, float, list[SymbolInfo]]]:
        """Rank repository files and identify relevant symbols for each.

        Returns:
            List of (DiscoveredFile, score, relevant_symbols) sorted by score descending.
        """
        # 1. Build query term bag from problem statement, requirements, and acceptance criteria
        query_text = (
            f"{spec.problem_statement} "
            f"{' '.join(spec.functional_requirements)} "
            f"{' '.join(c.description for c in spec.acceptance_criteria)} "
            f"{' '.join(spec.technical_constraints)}"
        )
        query_terms = extract_keywords(query_text)

        # Index symbols by file_path
        symbols_by_file: dict[str, list[SymbolInfo]] = {}
        for sym in inventory.symbols:
            symbols_by_file.setdefault(sym.file_path, []).append(sym)

        scored_candidates: list[tuple[DiscoveredFile, float, list[SymbolInfo]]] = []

        # 2. Score source files
        for sf in inventory.source_files:
            score = self._score_file(sf, query_terms, symbols_by_file.get(sf.relative_path, []))
            if score > 0.0:
                matched_symbols = self._get_matching_symbols(
                    symbols_by_file.get(sf.relative_path, []), query_terms
                )
                scored_candidates.append((sf, score, matched_symbols))

        # 3. Boost files that have direct test relations
        for i, (sf, score, syms) in enumerate(scored_candidates):
            sf_stem = sf.relative_path.split("/")[-1].split(".")[0]
            # Check if any test file matches this name (e.g. test_auth.py <-> auth.py)
            has_matching_test = any(
                sf_stem in tf.relative_path.lower() for tf in inventory.test_files
            )
            if has_matching_test:
                scored_candidates[i] = (sf, score + 2.5, syms)

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        return scored_candidates

    def _score_file(
        self,
        file: DiscoveredFile,
        query_terms: set[str],
        symbols: list[SymbolInfo],
    ) -> float:
        """Calculate relevance score for a file."""
        score = 0.0
        file_path_terms = extract_keywords(file.relative_path)

        # Path matching (high signal, e.g. "auth.py" when query mentions "auth")
        path_overlap = file_path_terms.intersection(query_terms)
        score += len(path_overlap) * 5.0

        # Symbol matching (class and function names)
        for sym in symbols:
            sym_terms = extract_keywords(sym.name)
            sym_overlap = sym_terms.intersection(query_terms)
            if sym_overlap:
                # Class match gives high weight
                if sym.kind == "class":
                    score += len(sym_overlap) * 4.0
                elif sym.kind in ("function", "method"):
                    score += len(sym_overlap) * 3.0

            # Docstring match
            if sym.docstring:
                doc_terms = extract_keywords(sym.docstring)
                doc_overlap = doc_terms.intersection(query_terms)
                score += len(doc_overlap) * 0.5

        return score

    def _get_matching_symbols(
        self,
        symbols: list[SymbolInfo],
        query_terms: set[str],
    ) -> list[SymbolInfo]:
        """Return symbols that match query terms or belong to top matched classes."""
        matched: list[SymbolInfo] = []
        for sym in symbols:
            sym_terms = extract_keywords(sym.name)
            if sym_terms.intersection(query_terms):
                matched.append(sym)
        # If no specific symbol matched directly, include classes/functions from the file
        if not matched:
            matched = [s for s in symbols if s.kind in ("class", "function")][:5]
        return matched
