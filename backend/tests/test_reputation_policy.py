from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.services.reputation_policy import (
    INVESTOR_POINTS_CAP_PER_DEPOSIT,
    calculate_project_investor_points,
)


def test_investor_points_are_linear_at_small_amounts() -> None:
    assert calculate_project_investor_points(1) == 1
    assert calculate_project_investor_points(100_000) == 1
    assert calculate_project_investor_points(550_000) == 5


def test_investor_points_cap_is_high_but_bounded() -> None:
    amount_at_cap = INVESTOR_POINTS_CAP_PER_DEPOSIT * 100_000
    assert calculate_project_investor_points(amount_at_cap) == INVESTOR_POINTS_CAP_PER_DEPOSIT
    assert calculate_project_investor_points(amount_at_cap * 3) == INVESTOR_POINTS_CAP_PER_DEPOSIT


def test_investor_points_require_positive_amount() -> None:
    with pytest.raises(ValueError):
        calculate_project_investor_points(0)
