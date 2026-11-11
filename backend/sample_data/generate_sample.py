"""Generate realistic synthetic sales data for InsightPulse AI.

About 18 months of orders across Karachi, Lahore, Islamabad and Multan, with:
- 5 product categories (20 products), repeat customers (Pareto-like),
- weekday and time-of-day patterns, Eid / 11.11 / wedding-season seasonality,
- gentle growth, a few missing values, duplicate rows, currency-formatted totals,
- one revenue spike anomaly and one outage-style dip.

Run:  python -m sample_data.generate_sample   (writes sample_data/sales_sample.csv)
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

CITIES = {"Karachi": 0.38, "Lahore": 0.32, "Islamabad": 0.18, "Multan": 0.12}

PRODUCTS: dict[str, list[tuple[str, float]]] = {
    "Electronics": [
        ("Wireless Earbuds", 4500),
        ("Smart Watch", 9800),
        ("Power Bank 20000mAh", 3600),
        ("Bluetooth Speaker", 6200),
    ],
    "Apparel": [
        ("Lawn Suit 3pc", 5200),
        ("Men's Kurta", 3400),
        ("Denim Jeans", 2900),
        ("Embroidered Shawl", 4100),
    ],
    "Home & Kitchen": [
        ("Non-stick Cookware Set", 8900),
        ("Electric Kettle", 3200),
        ("Bedsheet King", 3900),
        ("Air Fryer", 15500),
    ],
    "Beauty": [
        ("Herbal Shampoo", 950),
        ("Face Serum", 1850),
        ("Attar Perfume", 2400),
        ("Lipstick Set", 1600),
    ],
    "Groceries": [
        ("Basmati Rice 5kg", 2100),
        ("Desi Ghee 1kg", 2600),
        ("Green Tea 100 bags", 850),
        ("Dry Fruit Box", 3800),
    ],
}
# Relative popularity of each product (same order as PRODUCTS, flattened).
POPULARITY = np.array([9, 4, 6, 3, 10, 6, 7, 3, 2, 5, 4, 2, 9, 6, 5, 4, 8, 6, 7, 2], dtype=float)

FIRST = [
    "Ali",
    "Ahmed",
    "Fatima",
    "Ayesha",
    "Hassan",
    "Zainab",
    "Bilal",
    "Sana",
    "Usman",
    "Hira",
    "Omar",
    "Maryam",
    "Hamza",
    "Iqra",
    "Saad",
    "Noor",
    "Danish",
    "Mahnoor",
    "Faisal",
    "Amna",
    "Imran",
    "Rabia",
    "Kashif",
    "Sadia",
    "Tariq",
    "Mehwish",
]
LAST = [
    "Khan",
    "Malik",
    "Qureshi",
    "Sheikh",
    "Butt",
    "Chaudhry",
    "Raza",
    "Siddiqui",
    "Hussain",
    "Javed",
    "Akhtar",
    "Mirza",
    "Abbasi",
    "Baig",
    "Rana",
    "Ansari",
]

# Approximate festival dates inside the window (Eid dates shift ~11 days per year).
EVENTS: list[tuple[date, int, float]] = [
    (date(2025, 6, 7), 10, 0.55),  # Eid al-Adha 2025 (build-up before the date)
    (date(2025, 11, 11), 3, 0.9),  # 11.11 sale
    (date(2026, 3, 20), 14, 0.75),  # Eid al-Fitr 2026 (Ramadan shopping)
    (date(2026, 5, 27), 10, 0.55),  # Eid al-Adha 2026
]


def _seasonal_multiplier(d: date) -> float:
    """Combine yearly seasonality, festival build-ups and wedding season."""
    m = 1.0
    if d.month in (11, 12, 1):  # wedding season
        m *= 1.18
    if d.month in (6, 7):  # summer slowdown
        m *= 0.9
    for event_day, lead_days, boost in EVENTS:
        delta = (event_day - d).days
        if 0 <= delta <= lead_days:
            m *= 1 + boost * (1 - delta / (lead_days + 1))
    return m


def _weekday_multiplier(d: date) -> float:
    # Mon..Sun; weekends busiest, Friday a little softer.
    return [0.92, 0.9, 0.95, 1.0, 0.88, 1.25, 1.3][d.weekday()]


def _order_hour(rng: np.random.Generator, weekday: int) -> int:
    hours = np.arange(24)
    weights = np.full(24, 0.15)
    weights[9:13] = 0.9
    weights[13:17] = 1.0
    weights[19:23] = 1.6  # evening peak
    if weekday == 4:  # Friday prayer dip
        weights[12:15] *= 0.3
    return int(rng.choice(hours, p=weights / weights.sum()))


def generate(
    start: date = date(2025, 5, 1),
    months: int = 18,
    base_orders_per_day: float = 34.0,
    n_customers: int = 2200,
    seed: int = 42,
) -> pd.DataFrame:
    """Return a raw (messy) synthetic sales DataFrame shaped like a shop export."""
    rng = np.random.default_rng(seed)
    end = (pd.Timestamp(start) + pd.DateOffset(months=months) - pd.Timedelta(days=1)).date()
    n_days = (end - start).days + 1

    flat = [(cat, name, price) for cat, items in PRODUCTS.items() for name, price in items]
    pop = POPULARITY / POPULARITY.sum()

    # Customers: home city + a Pareto "loyalty" weight so some buy very often.
    cust_city = rng.choice(list(CITIES), size=n_customers, p=list(CITIES.values()))
    loyalty = rng.pareto(1.6, size=n_customers) + 0.05
    # Customers join over time: each has a first-active day.
    join_day = (rng.beta(1.2, 2.2, size=n_customers) * n_days * 0.95).astype(int)
    names = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(n_customers)]
    customers = pd.DataFrame(
        {
            "customer_id": [f"C{10000 + i}" for i in range(n_customers)],
            "name": names,
            "email": [f"{n.lower().replace(' ', '.')}{i}@example.pk" for i, n in enumerate(names)],
            "phone": [
                f"03{rng.integers(0, 5)}{rng.integers(0, 10)}-{rng.integers(1000000, 9999999)}"
                for _ in range(n_customers)
            ],
            "city": cust_city,
        }
    )

    rows: list[dict] = []
    order_no = 100000
    for day_idx in range(n_days):
        d = start + timedelta(days=day_idx)
        growth = 1 + 0.35 * day_idx / n_days
        lam = base_orders_per_day * growth * _seasonal_multiplier(d) * _weekday_multiplier(d)
        if d == date(2026, 2, 9):  # outage-style dip
            lam *= 0.25
        n_orders = rng.poisson(lam)
        active = np.flatnonzero(join_day <= day_idx)
        w = loyalty[active] / loyalty[active].sum()
        buyers = rng.choice(active, size=n_orders, p=w)
        for c in buyers:
            order_no += 1
            hour = _order_hour(rng, d.weekday())
            ts = pd.Timestamp(d) + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60)))
            n_lines = 1 if rng.random() < 0.78 else 2
            for _ in range(n_lines):
                p = rng.choice(len(flat), p=pop)
                cat, prod, price = flat[p]
                unit = round(price * rng.uniform(0.92, 1.08), -1)
                discount = float(rng.choice([0, 0, 0, 5, 10, 15]))
                if d.month == 11 and d.day == 11:
                    discount = max(discount, 20.0)
                # Demand responds to price (elasticity of units ~ -1.5) and discounts.
                extra_units = 0.65 * (unit / price) ** -4 * (1 + 0.04 * discount)
                qty = 1 + int(min(rng.poisson(extra_units), 9))
                total = round(unit * qty * (1 - discount / 100), 0)
                rows.append(
                    {
                        "Order ID": f"ORD-{order_no}",
                        "Order Date": ts,
                        "Customer ID": customers.at[c, "customer_id"],
                        "Customer Name": customers.at[c, "name"],
                        "Email": customers.at[c, "email"],
                        "Phone": customers.at[c, "phone"],
                        "City": customers.at[c, "city"],
                        "Category": cat,
                        "Product": prod,
                        "Qty": qty,
                        "Unit Price": unit,
                        "Discount %": discount,
                        "Total": total,
                    }
                )

    df = pd.DataFrame(rows)

    # Anomaly: a corporate bulk order day with a huge spike.
    spike_day = pd.Timestamp(2026, 4, 18)
    spike = df[df["Order Date"].dt.normalize() == spike_day].head(12).copy()
    spike["Qty"] = 25
    spike["Total"] = (spike["Unit Price"] * spike["Qty"] * 0.85).round(0)
    spike["Order ID"] = [f"ORD-B{i}" for i in range(len(spike))]
    df = pd.concat([df, spike], ignore_index=True)

    df = df.sort_values("Order Date", kind="stable").reset_index(drop=True)

    # Messiness: currency-formatted totals, missing values, duplicates.
    df["Order Date"] = df["Order Date"].dt.strftime("%Y-%m-%d %H:%M")
    df["Total"] = df["Total"].astype(object)
    fmt_idx = rng.choice(len(df), size=len(df) // 6, replace=False)
    df.loc[fmt_idx, "Total"] = [f"Rs {int(v):,}" for v in df.loc[fmt_idx, "Total"]]
    df.loc[rng.choice(len(df), size=25, replace=False), "Order Date"] = None
    df.loc[rng.choice(len(df), size=30, replace=False), "Total"] = None
    df.loc[rng.choice(len(df), size=60, replace=False), "City"] = None
    dupes = df.iloc[rng.choice(len(df), size=40, replace=False)]
    df = pd.concat([df, dupes], ignore_index=True)
    return df


def main() -> None:
    out = Path(__file__).with_name("sales_sample.csv")
    df = generate()
    df.to_csv(out, index=False)
    print(f"Wrote {len(df):,} rows to {out}")


if __name__ == "__main__":
    main()
