"""Reproducible order generation and test shuffling."""

from __future__ import annotations

import hashlib
import random


def derive_run_seed(base_seed: int, run_index: int) -> int:
    """Derive a deterministic integer seed for a specific run index."""
    hasher = hashlib.sha256()
    hasher.update(f"{base_seed}:{run_index}".encode())
    # Use lowest 31 bits as positive integer seed
    return int.from_bytes(hasher.digest()[:4], byteorder="big") & 0x7FFFFFFF


def generate_shuffled_order(node_ids: list[str], seed: int) -> list[str]:
    """Deterministically shuffle a list of test node IDs using a seed.

    Args:
        node_ids: List of test node IDs.
        seed: Integer seed for reproducible ordering.

    Returns:
        New list of node IDs shuffled according to the seed.
    """
    rng = random.Random(seed)
    shuffled = list(node_ids)
    rng.shuffle(shuffled)
    return shuffled


def generate_suite_orders(
    node_ids: list[str],
    base_seed: int,
    runs: int,
) -> list[tuple[int, list[str]]]:
    """Generate reproducible seeds and shuffled orders for each run.

    Args:
        node_ids: Collected test node IDs.
        base_seed: Master seed provided to FlakyHunter.
        runs: Number of runs to generate.

    Returns:
        List of tuples: (run_seed, shuffled_order).
    """
    orders: list[tuple[int, list[str]]] = []
    for i in range(runs):
        run_seed = derive_run_seed(base_seed, i)
        order = generate_shuffled_order(node_ids, run_seed)
        orders.append((run_seed, order))
    return orders
