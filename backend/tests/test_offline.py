"""Ask AI with no LLM: rule-based reading of questions, numbers from the same executor."""

from __future__ import annotations

import pandas as pd
import pytest

from app.ai.offline import answer_offline


def ask(df, q):
    return answer_offline(df, q, "PKR")


def test_top_products_last_month(clean_df) -> None:
    a = ask(clean_df, "Which products sold the most last month?")
    end = clean_df["date"].max().normalize()
    last = end.to_period("M") - (0 if end.is_month_end else 1)
    month = clean_df[clean_df["date"].dt.to_period("M") == last]
    assert a.source == "offline" and a.answerable and a.chart is not None
    assert a.plan["group_by"] == "product" and a.plan["period"]["type"] == "month"
    expected = month.groupby("product")["revenue"].sum().sort_values(ascending=False)
    assert a.result.rows[0].label == expected.index[0]
    assert a.result.rows[0].value == pytest.approx(expected.iloc[0], rel=1e-6)
    assert len(a.result.rows) == 5


@pytest.mark.parametrize(
    ("question", "metric", "group"),
    [
        ("Which city brings in the most revenue?", "revenue", "region"),
        ("What is my busiest weekday?", "orders", "weekday"),
        ("How many customers did I have last week?", "customers", None),
        ("Show monthly revenue", "revenue", "month"),
        ("What is my average order value?", "avg_order_value", None),
        ("Top 3 customers by sales", "revenue", "customer"),
    ],
)
def test_common_questions(clean_df, question, metric, group) -> None:
    a = ask(clean_df, question)
    assert a.answerable and a.plan["metric"] == metric and a.plan["group_by"] == group


def test_change_question_compares(clean_df) -> None:
    a = ask(clean_df, "How did revenue change over the last 30 days?")
    assert a.plan["compare"] == "previous_period" and a.plan["period"]["n_days"] == 30


def test_top_n_and_worst(clean_df) -> None:
    assert len(ask(clean_df, "top 3 products").result.rows) == 3
    assert ask(clean_df, "worst selling products").plan["sort"] == "asc"


def test_named_city_is_filtered(clean_df) -> None:
    city = str(clean_df["region"].dropna().iloc[0])
    a = ask(clean_df, f"revenue in {city} last month")
    assert a.plan["filter"][0]["field"] == "region"


def test_says_when_data_is_missing(clean_df) -> None:
    a = ask(clean_df, "What is my profit margin?")
    assert not a.answerable and "profit" in a.answer and a.chart is None


def test_unreadable_question_gets_help(clean_df) -> None:
    a = ask(clean_df, "hello there")
    assert not a.answerable and a.follow_ups


def test_month_without_data_is_explained(clean_df) -> None:
    df: pd.DataFrame = clean_df[clean_df["date"] < clean_df["date"].max().replace(day=1)]
    a = ask(df, "revenue this month")
    assert a.source == "offline"


def test_follow_ups_do_not_repeat_the_question(clean_df) -> None:
    q = "Which products sold the most last month?"
    assert q not in ask(clean_df, q).follow_ups


def test_profit_column_is_used_when_the_file_has_one(clean_df) -> None:
    df = clean_df.assign(profit=clean_df["revenue"] * 0.25)
    a = ask(df, "What is my profit?")
    assert a.answerable and a.plan["metric"] == "profit"
    assert a.result.total == pytest.approx(df["profit"].sum(), rel=1e-6)
    assert "25.0% margin" in ask(df, "What is my profit margin?").answer
    assert ask(df, "profit by product").plan["group_by"] == "product"


def test_ask_about_an_insight_explains_that_insight(ctx, clean_df) -> None:
    from app.insights.engine import generate_insights

    insights = generate_insights(clean_df, ctx, limit=10)
    target = next(i for i in insights if i.chart is not None)
    a = answer_offline(clean_df, f"Tell me more about this: {target.headline}", "PKR", insights)
    assert target.why_it_matters in a.answer and a.chart == target.chart and a.answerable


def test_a_named_year_or_month_limits_the_answer(clean_df) -> None:
    year = int(clean_df["date"].dt.year.max())
    a = ask(clean_df, f"Revenue in {year}")
    expected = clean_df.loc[clean_df["date"].dt.year == year, "revenue"].sum()
    assert a.result.total == pytest.approx(expected, rel=1e-6)
    month = clean_df["date"].max().strftime("%B %Y").lower()
    assert ask(clean_df, f"revenue for {month}").plan["period"]["type"] == "month"
