"""Context Compiler Engine.

Compiles WorkItemSpec and RepositoryInventory into a ranked, budgeted,
and security-bounded ContextPack for the Implementation Agent.
"""

from auto_pr.core.models import WorkItemSpec, ContextPack, SymbolInfo
from auto_pr.discovery.models import RepositoryInventory
from auto_pr.compiler.ranker import EvidenceRanker
from auto_pr.compiler.budget import EvidenceBudgetManager, estimate_tokens


class ContextCompiler:
    """Compiles discovered repository context and work item spec into a ContextPack."""

    def __init__(
        self,
        ranker: EvidenceRanker | None = None,
        budget_manager: EvidenceBudgetManager | None = None,
        default_token_budget: int = 8000,
    ) -> None:
        self.ranker = ranker or EvidenceRanker()
        self.budget_manager = budget_manager or EvidenceBudgetManager(default_token_budget)
        self.default_token_budget = default_token_budget

    def compile(
        self,
        spec: WorkItemSpec,
        inventory: RepositoryInventory,
        token_budget: int | None = None,
    ) -> ContextPack:
        """Compile a structured, evidence-ranked, and budgeted ContextPack.

        Strictly enforces:
        1. Ranking by relevance to WorkItemSpec.
        2. Strict token ceiling (no silent context overflow).
        3. Security: repository contents tagged as untrusted context with source attribution.
        4. Independent of any LLM provider.
        """
        budget = token_budget or self.default_token_budget

        # 1. Rank repository files against spec
        ranked_files = self.ranker.rank_inventory(spec, inventory)

        # 2. Extract code windows within token budget
        # Allocate 70% of budget to file extracts, 30% to rules and symbols
        code_budget = int(budget * 0.70)
        file_extracts, code_tokens = self.budget_manager.build_file_extracts(
            ranked_files, token_budget=code_budget
        )

        # 3. Collect relevant symbols from the included extracts
        relevant_symbols: list[SymbolInfo] = []
        extract_paths = {fe.file_path for fe in file_extracts}
        for _, _, syms in ranked_files:
            for s in syms:
                if s.file_path in extract_paths and s not in relevant_symbols:
                    relevant_symbols.append(s)

        # 4. Formulate coding standards from repository rules with security boundaries
        coding_standards: list[str] = []
        rule_tokens = 0
        rule_budget = budget - code_tokens

        for rule in inventory.rules:
            # Defensive tagging: mark as untrusted repository context
            formatted_rule = (
                f"[SOURCE: {rule.source_file}] (Untrusted Context)\n"
                f"{rule.content.strip()}"
            )
            cost = estimate_tokens(formatted_rule)
            if rule_tokens + cost <= rule_budget:
                coding_standards.append(formatted_rule)
                rule_tokens += cost

        # 5. Gather test files (relative paths)
        test_file_paths = [tf.relative_path for tf in inventory.test_files]

        # 6. Map detected commands
        cmds = inventory.detected_commands
        detected_cmds_map: dict[str, str | None] = {
            "build": cmds.build_command,
            "test": cmds.test_command,
            "lint": cmds.lint_command,
            "typecheck": cmds.typecheck_command,
        }

        # 7. Compile evidence sources and ranking information
        evidence_sources = list(extract_paths)
        for rule in inventory.rules:
            if rule.source_file not in evidence_sources:
                evidence_sources.append(rule.source_file)

        ranking_details: dict[str, float] = {
            df.relative_path: round(score, 2) for df, score, _ in ranked_files
        }

        total_tokens_used = code_tokens + rule_tokens

        return ContextPack(
            target_files=file_extracts,
            relevant_symbols=relevant_symbols,
            test_files=test_file_paths,
            build_command=cmds.build_command,
            test_command=cmds.test_command,
            lint_command=cmds.lint_command,
            typecheck_command=cmds.typecheck_command,
            detected_commands=detected_cmds_map,
            coding_standards=coding_standards,
            evidence_sources=evidence_sources,
            ranking_details=ranking_details,
            evidence_tokens_used=total_tokens_used,
            token_budget=budget,
        )
