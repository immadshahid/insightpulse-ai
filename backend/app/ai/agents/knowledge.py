"""The retrieval half of RAG: passages about one dataset, searched with TF-IDF.

The corpus is what the deterministic analytics already worked out (insights, forecasts,
data quality, the column mapping) plus fixed definitions of the app's metrics. TF-IDF
needs no extra service or key; to use embeddings, replace :meth:`KnowledgeBase.search`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.ai.privacy import Pseudonymizer, mask_text
from app.insights.base import Insight

MIN_SCORE = 0.03

GLOSSARY = [
    ("Definition: revenue", "Revenue is total money received from sales after discounts."),
    ("Definition: orders", "Orders counts separate orders; one order can hold many products."),
    ("Definition: average order value", "Average order value (AOV) is revenue divided by orders."),
    (
        "Definition: active customers",
        "Active customers are different customers who bought at least once in the period.",
    ),
    (
        "Method: forecasts",
        "Forecasts test Prophet, SARIMA and XGBoost on held-out recent history and keep the "
        "most accurate. The accuracy note is the typical percentage error on that holdout. "
        "The likely range is an interval around the expected total.",
    ),
    (
        "Method: customer segments",
        "Customers are grouped by how recently, how often and how much they buy into "
        "Champions, Loyal, Potential, At risk and Hibernating. Churn risk flags regular "
        "buyers who have stopped buying for much longer than usual.",
    ),
    (
        "Method: anomalies",
        "An anomaly is a day whose revenue is far outside the normal range for that weekday.",
    ),
    (
        "Limits of the data",
        "Sales files hold no costs, margins, marketing spend or stock levels unless those "
        "columns were uploaded, so profit and return on ads cannot be worked out otherwise.",
    ),
]


@dataclass(frozen=True)
class Passage:
    """One searchable piece of knowledge."""

    title: str
    text: str


class KnowledgeBase:
    """TF-IDF index over a dataset's passages."""

    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages
        self._vectorizer = TfidfVectorizer(
            stop_words="english", ngram_range=(1, 2), sublinear_tf=True
        )
        self._matrix = self._vectorizer.fit_transform(f"{p.title}. {p.text}" for p in passages)

    def search(self, query: str, k: int = 4) -> list[tuple[Passage, float]]:
        """Best passages for ``query``, most relevant first."""
        scores = cosine_similarity(self._vectorizer.transform([query]), self._matrix)[0]
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [(self.passages[i], float(s)) for i, s in ranked[:k] if s >= MIN_SCORE]


def build_passages(
    insights: list[Insight],
    profile: dict[str, Any],
    forecasts: list[dict[str, Any]],
    pseudo: Pseudonymizer,
    real_customers: list[str],
) -> list[Passage]:
    """Assemble the corpus, with personal data masked before anything is indexed."""

    def safe(text: str) -> str:
        return pseudo.mask_known(mask_text(text), real_customers)

    out = [Passage(title, text) for title, text in GLOSSARY]
    for ins in insights:
        body = " ".join(filter(None, [ins.headline, ins.why_it_matters, ins.narrative]))
        facts = json.dumps(ins.data, ensure_ascii=False, default=str)[:1500]
        out.append(Passage(f"Insight ({ins.category}): {ins.tag}", safe(f"{body} Data: {facts}")))
    mapping = {k: v for k, v in (profile.get("mapping") or {}).items() if isinstance(v, str)}
    if mapping:
        pairs = ", ".join(f"{k} = {v}" for k, v in mapping.items())
        out.append(Passage("Data: how columns are used", safe(f"Column mapping: {pairs}.")))
    quality = profile.get("quality") or {}
    if quality:
        issues = " ".join(i.get("message", "") for i in quality.get("issues", []))
        out.append(
            Passage(
                "Data: quality",
                safe(f"Quality score {quality.get('score')} ({quality.get('label')}). {issues}"),
            )
        )
    for f in forecasts:
        out.append(
            Passage(
                f"Forecast: {f.get('target_label', f.get('target'))}, {f.get('horizon_days')} days",
                f"Expected total {f.get('total')}, likely between {f.get('total_lower')} and "
                f"{f.get('total_upper')}. Change versus the previous period: "
                f"{f.get('change_pct')}%. Model: {f.get('model')}. "
                f"Accuracy: {f.get('accuracy_note')}.",
            )
        )
    return out
