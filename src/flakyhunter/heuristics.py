"""Heuristic cause classification combining static AST inspection and failure messages."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from flakyhunter.models import CauseCategory, CauseClassification, PolluterInvestigation


class TestASTInspector(ast.NodeVisitor):
    """Inspects test function AST for indicators of time, randomness, network, and shared state."""

    def __init__(self) -> None:
        self.evidence: dict[str, list[str]] = {
            "time": [],
            "randomness": [],
            "network": [],
            "shared state": [],
        }

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name.lower()
            if name in ("time", "datetime"):
                self.evidence["time"].append(f"Imports module '{alias.name}'")
            elif name in ("random", "secrets"):
                self.evidence["randomness"].append(f"Imports module '{alias.name}'")
            elif name in ("requests", "httpx", "urllib", "socket", "aiohttp"):
                self.evidence["network"].append(f"Imports network library '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = (node.module or "").lower()
        if module in ("time", "datetime"):
            self.evidence["time"].append(f"Imports from '{node.module}'")
        elif module in ("random", "secrets"):
            self.evidence["randomness"].append(f"Imports from '{node.module}'")
        elif module in ("requests", "httpx", "urllib", "socket", "aiohttp"):
            self.evidence["network"].append(f"Imports from network library '{node.module}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        func_lower = func_name.lower()

        # Time indicators
        if func_lower in ("sleep", "monotonic", "perf_counter", "now", "utcnow", "wait_for"):
            self.evidence["time"].append(f"Calls time-related function '{func_name}'")

        # Randomness indicators
        if func_lower in (
            "random",
            "randint",
            "choice",
            "shuffle",
            "sample",
            "randrange",
            "uniform",
        ):
            self.evidence["randomness"].append(f"Calls stochastic function '{func_name}'")

        # Network indicators
        if func_lower in ("get", "post", "put", "delete", "urlopen", "connect", "sendall", "recv"):
            self.evidence["network"].append(f"Calls network-related function '{func_name}'")

        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.evidence["shared state"].append(f"Modifies global variables: {', '.join(node.names)}")
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.evidence["shared state"].append(
            f"Modifies nonlocal variables: {', '.join(node.names)}"
        )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr_lower = node.attr.lower()
        if "environ" in attr_lower:
            self.evidence["shared state"].append(
                "Accesses or modifies environment variables (os.environ)"
            )
        elif "session" in attr_lower or "store" in attr_lower or "cache" in attr_lower:
            self.evidence["shared state"].append(f"Accesses shared mutable attribute '{node.attr}'")
        elif "timeout" in attr_lower or "deadline" in attr_lower:
            self.evidence["time"].append(f"References timeout attribute '{node.attr}'")
        self.generic_visit(node)


def inspect_source_code(
    file_path: Path | str, test_func_name: str | None = None
) -> dict[str, list[str]]:
    """Parse a test file and return evidence found in AST."""
    path = Path(file_path)
    if not path.is_file():
        return {"time": [], "randomness": [], "network": [], "shared state": []}

    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
    except Exception:
        return {"time": [], "randomness": [], "network": [], "shared state": []}

    target_node: ast.AST = tree
    if test_func_name:
        for item in ast.walk(tree):
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == test_func_name
            ):
                target_node = item
                break

    inspector = TestASTInspector()
    inspector.visit(target_node)
    return inspector.evidence


def match_failure_message(error_message: str | None) -> dict[str, list[str]]:
    """Inspect error message and stack trace for diagnostic patterns."""
    evidence: dict[str, list[str]] = {
        "time": [],
        "randomness": [],
        "network": [],
        "shared state": [],
    }
    if not error_message:
        return evidence

    msg = error_message.lower()

    if any(k in msg for k in ("timeout", "timed out", "timeouterror", "deadline")):
        evidence["time"].append(
            f"Failure message indicates timeout/deadline issue: '{error_message[:100]}'"
        )

    if any(
        k in msg for k in ("connectionerror", "connecterror", "connectionrefused", "http", "socket")
    ):
        evidence["network"].append(
            f"Failure message indicates network/socket issue: '{error_message[:100]}'"
        )

    if any(
        k in msg for k in ("keyerror", "already exists", "integrityerror", "mutated", "conflict")
    ):
        evidence["shared state"].append(
            f"Failure message indicates state mutation/conflict: '{error_message[:100]}'"
        )

    if re.search(r"assert .* == .*", msg) and any(k in msg for k in ("random", "seed", "prob")):
        evidence["randomness"].append("Assertion failure in probabilistic/random output context")

    return evidence


def classify_cause(
    node_id: str,
    error_message: str | None = None,
    polluter_investigation: PolluterInvestigation | None = None,
    source_root: Path | str | None = None,
) -> CauseClassification:
    """Classify the likely root cause of a flaky test using AST inspection, error matching, and polluter findings.

    Precedence order for ties:
        shared state > time > randomness > network > unknown

    Args:
        node_id: Pytest node identifier (e.g. tests/test_cart.py::test_cart_total).
        error_message: Recorded failure message or traceback text.
        polluter_investigation: Optional completed polluter investigation.
        source_root: Optional root directory to resolve relative test file paths.

    Returns:
        CauseClassification with category, confidence, and supporting evidence.
    """
    evidence: dict[str, list[str]] = {
        "time": [],
        "randomness": [],
        "network": [],
        "shared state": [],
    }

    # 1. Check polluter investigation
    if (
        polluter_investigation
        and polluter_investigation.verified
        and polluter_investigation.minimized_polluter_set
    ):
        polluter_names = ", ".join(polluter_investigation.minimized_polluter_set)
        evidence["shared state"].append(
            f"Verified polluter test set identified via ddmin: [{polluter_names}]"
        )
        return CauseClassification(
            category="shared state",
            confidence=0.95,
            evidence=evidence["shared state"],
        )

    # 2. Parse source AST
    parts = node_id.split("::")
    file_part = parts[0]
    func_name = parts[-1].split("[")[0] if len(parts) > 1 else None

    file_path = Path(file_part)
    if not file_path.is_file() and source_root:
        file_path = Path(source_root) / file_part

    if file_path.is_file():
        ast_ev = inspect_source_code(file_path, test_func_name=func_name)
        for cat, items in ast_ev.items():
            evidence[cat].extend(items)

    # 3. Match failure message patterns
    msg_ev = match_failure_message(error_message)
    for cat, items in msg_ev.items():
        evidence[cat].extend(items)

    # 4. Deterministic scoring and precedence
    scores: dict[CauseCategory, int] = {
        "shared state": len(evidence["shared state"]),
        "time": len(evidence["time"]),
        "randomness": len(evidence["randomness"]),
        "network": len(evidence["network"]),
    }

    precedence: list[CauseCategory] = ["shared state", "time", "randomness", "network"]

    best_cat: CauseCategory = "unknown"
    max_score = 0

    for cat in precedence:
        score = scores.get(cat, 0)
        if score > max_score:
            max_score = score
            best_cat = cat

    if max_score == 0:
        return CauseClassification(
            category="unknown",
            confidence=0.0,
            evidence=["No static AST or runtime error patterns matched."],
        )

    cat_evidence = evidence[best_cat]
    confidence = min(0.90, round(0.40 + 0.15 * len(cat_evidence), 2))

    return CauseClassification(
        category=best_cat,
        confidence=confidence,
        evidence=cat_evidence,
    )
