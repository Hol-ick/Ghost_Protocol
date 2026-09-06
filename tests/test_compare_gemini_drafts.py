from decimal import Decimal

import pytest

from tools.compare_gemini_drafts import CASES, cost_usd


def test_cost_includes_thinking_and_discounted_cached_input():
    usage = {'prompt_token_count': 10000, 'cached_content_token_count': 2000,
             'candidates_token_count': 100, 'thoughts_token_count': 50}
    assert cost_usd('gemini-2.5-flash', usage) == Decimal('0.002835')
    assert cost_usd('gemini-3.1-flash-lite', usage) == Decimal('0.002275')


def test_invalid_cached_usage_is_rejected():
    with pytest.raises(AssertionError):
        cost_usd('gemini-2.5-flash', {'prompt_token_count': 5, 'cached_content_token_count': 6})


def test_ten_explicit_distinct_personas():
    assert len(CASES) == len({tone for tone, _ in CASES}) == 10
