from deepeval.test_case import ToolCall
from backend.eval_service import (
    _compute_lcs,
    _normalize_param_value,
    _evaluate_tool_correctness,
    _evaluate_argument_correctness,
    _evaluate_answer_correctness,
    _evaluate_financial_hallucination,
)


def test_lcs_computation():
    """Verify LCS logic for tool sequence evaluation."""
    assert _compute_lcs(["a", "b", "c"], ["a", "b", "c"]) == 3
    assert _compute_lcs(["a", "b", "c"], ["b", "a", "c"]) == 2
    assert _compute_lcs(["a", "b"], ["x", "y"]) == 0
    assert _compute_lcs([], ["a"]) == 0


def test_normalize_param_value():
    """Verify parameter normalization handles strings, floats, ints, and item lists."""
    assert _normalize_param_value("  user123  ") == "user123"
    assert _normalize_param_value(30) == 30.0
    assert _normalize_param_value([{"name": "pen"}, {"name": "book"}]) == ["book", "pen"]
    assert _normalize_param_value(["pen", "book"]) == ["book", "pen"]


def test_tool_correctness_exact_sequence():
    """Verify tool correctness gives 1.0 on exact matching sequence."""
    expected = [
        ToolCall(name="get_user_purchase_history"),
        ToolCall(name="get_today_date"),
        ToolCall(name="calculate_right_refund"),
        ToolCall(name="issue_refund_ticket"),
    ]
    called = [
        {"name": "get_user_purchase_history", "input_parameters": {}},
        {"name": "get_today_date", "input_parameters": {}},
        {"name": "calculate_right_refund", "input_parameters": {}},
        {"name": "issue_refund_ticket", "input_parameters": {}},
    ]
    score, passed, reason = _evaluate_tool_correctness(expected, called)
    assert score == 1.0
    assert passed is True
    assert "Exact" in reason


def test_tool_correctness_out_of_order():
    """Verify out-of-order tool calling is penalized."""
    expected = [
        ToolCall(name="get_user_purchase_history"),
        ToolCall(name="get_today_date"),
        ToolCall(name="calculate_right_refund"),
        ToolCall(name="issue_refund_ticket"),
    ]
    # Inverted order of first two tools
    called = [
        {"name": "get_today_date", "input_parameters": {}},
        {"name": "get_user_purchase_history", "input_parameters": {}},
        {"name": "calculate_right_refund", "input_parameters": {}},
        {"name": "issue_refund_ticket", "input_parameters": {}},
    ]
    score, passed, reason = _evaluate_tool_correctness(expected, called)
    assert passed is False
    assert score < 0.8


def test_tool_correctness_unauthorized_ticket():
    """Calling issue_refund_ticket when unexpected must fail immediately."""
    expected = [ToolCall(name="get_user_purchase_history")]
    called = [
        {"name": "get_user_purchase_history", "input_parameters": {}},
        {"name": "issue_refund_ticket", "input_parameters": {"refund_amount": 100}},
    ]
    score, passed, reason = _evaluate_tool_correctness(expected, called)
    assert score == 0.0
    assert passed is False
    assert "unauthorized" in reason.lower()


def test_argument_correctness_matches():
    """Verify arguments match ground truth regardless of item list order."""
    expected = [
        ToolCall(name="calculate_right_refund", input_parameters={"user": "user123", "items": [{"name": "book"}, {"name": "pen"}]}),
        ToolCall(name="issue_refund_ticket", input_parameters={"user": "user123", "refund_amount": 30}),
    ]
    called = [
        {"name": "calculate_right_refund", "input_parameters": {"user": "user123", "items": [{"name": "pen"}, {"name": "book"}]}},
        {"name": "issue_refund_ticket", "input_parameters": {"user": "user123", "refund_amount": 30}},
    ]
    score, passed, reason = _evaluate_argument_correctness(expected, called)
    assert score == 1.0
    assert passed is True


def test_argument_correctness_mismatch():
    """Verify incorrect refund amount fails argument correctness."""
    expected = [
        ToolCall(name="issue_refund_ticket", input_parameters={"user": "user123", "refund_amount": 30}),
    ]
    called = [
        {"name": "issue_refund_ticket", "input_parameters": {"user": "user123", "refund_amount": 500}},
    ]
    score, passed, reason = _evaluate_argument_correctness(expected, called)
    # User matches (1/2), but refund_amount fails, resulting in 0.5 and fail status
    assert score == 0.5
    assert passed is False
    assert "mismatch" in reason.lower()


def test_answer_correctness_no_len20_backdoor():
    """Verify that a random sentence over 20 chars does NOT pass anymore!"""
    expected = "A refund ticket for $30 has been issued successfully for the book and pen."
    # Random text > 20 characters
    gibberish = "Here is some random explanation text that definitely exceeds twenty characters in length."
    score, passed, reason = _evaluate_answer_correctness(expected, gibberish, exec_error=None)
    assert passed is False, "Random 20+ char string must NOT pass honest evaluation"
    assert score < 0.8


def test_answer_correctness_polarity_conflict():
    """Verify that claiming a ticket was issued when request was ineligible fails."""
    expected = "No refund will be issued because the travel mug was purchased 31 days ago."
    actual = "A refund ticket has been issued for $15 for your travel mug."
    score, passed, reason = _evaluate_answer_correctness(expected, actual, exec_error=None)
    assert passed is False
    assert "polarity" in reason.lower()


def test_financial_hallucination_unauthorized_ticket():
    """Detects unauthorized ticket and tracks dollars over-refunded."""
    expected = [ToolCall(name="get_user_purchase_history", input_parameters={"user": "david_k"})]
    called = [
        {"name": "get_user_purchase_history", "input_parameters": {"user": "david_k"}},
        {"name": "issue_refund_ticket", "input_parameters": {"user": "david_k", "refund_amount": 80}},
    ]
    res = _evaluate_financial_hallucination(expected, called, "No refund will be issued.", "Here is your history.")
    assert res["detected"] is True
    assert res["unauthorized_ticket"] is True
    assert res["dollars_over_refunded"] == 80.0
    assert res["passed"] is False


def test_financial_hallucination_over_refund():
    """Detects over-refund and computes exact excess dollar amount."""
    expected = [
        ToolCall(name="issue_refund_ticket", input_parameters={"user": "user123", "refund_amount": 30}),
    ]
    called = [
        {"name": "issue_refund_ticket", "input_parameters": {"user": "user123", "refund_amount": 75}},
    ]
    res = _evaluate_financial_hallucination(expected, called, "Refund ticket for $30", "Refund ticket for $75")
    assert res["detected"] is True
    assert res["dollars_over_refunded"] == 45.0
    assert "Over-refund" in res["reason"]


def test_financial_hallucination_fabricated_claim():
    """Detects when agent claims in text that a refund was issued without calling tool."""
    expected = [ToolCall(name="get_user_purchase_history", input_parameters={"user": "user123"})]
    called = [{"name": "get_user_purchase_history", "input_parameters": {"user": "user123"}}]
    # Agent hallucinated in natural language that a ticket was issued
    actual = "A refund ticket has been issued successfully for $100."
    res = _evaluate_financial_hallucination(expected, called, "No refund was issued.", actual)
    assert res["detected"] is True
    assert "Fabricated claim" in res["reason"]
