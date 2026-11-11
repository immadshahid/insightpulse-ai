"""Top / bottom products and revenue concentration."""

from __future__ import annotations

import math

import pandas as pd

from app.insights.base import ChartSpec, Insight, InsightContext, clamp01, has, jsonable


def top_products(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Rank products by revenue and measure how concentrated revenue is."""
    if not has(df, "product"):
        return None
    by_product = df.groupby("product")["revenue"].sum().sort_values(ascending=False)
    by_product = by_product[by_product > 0]
    if len(by_product) < 3:
        return None
    total = float(by_product.sum())
    shares = by_product / total
    top_n = max(1, math.ceil(len(by_product) * 0.2))
    top20_share = float(shares.iloc[:top_n].sum())
    top3_share = float(shares.iloc[:3].sum())
    leader = str(by_product.index[0])

    bottom = shares.iloc[-3:][::-1]
    headline = (
        f"{leader} brings in {shares.iloc[0] * 100:.0f}% of revenue; "
        f"the top 3 products bring {top3_share * 100:.0f}%"
    )
    why = (
        f"Your top {top_n} product{'s' if top_n > 1 else ''} ({20}% of the range) "
        f"make {top20_share * 100:.0f}% of sales. "
        f"Weakest: {', '.join(bottom.index.astype(str))}."
    )
    shown = by_product.iloc[:8]
    chart = ChartSpec(
        kind="bar_ranking",
        payload=jsonable(
            {
                "labels": [str(i) for i in shown.index],
                "values": shown.tolist(),
                "highlight": [0],
                "value_format": "money",
                "currency": ctx.currency,
            }
        ),
    )
    return Insight(
        id="top_products",
        kind="top_products",
        category="products",
        tag="Products",
        headline=headline,
        why_it_matters=why,
        score=clamp01(0.35 + max(0.0, top3_share - 0.3) * 1.2),
        data=jsonable(
            {
                "top": [
                    {"product": str(k), "revenue": float(v), "share": float(shares[k])}
                    for k, v in by_product.iloc[:5].items()
                ],
                "bottom": [
                    {"product": str(k), "revenue": float(by_product[k]), "share": float(v)}
                    for k, v in bottom.items()
                ],
                "product_count": int(len(by_product)),
                "top20pct_share": top20_share,
                "top3_share": top3_share,
                "currency": ctx.currency,
            }
        ),
        chart=chart,
    )
