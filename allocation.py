from __future__ import annotations

import math


def proportional_matrix(category_stock: dict[str, int], order_demand: dict[int, int]):
    """Return allocations preserving exact total/category/order margins.

    If stock exceeds demand, only total demand is allocated and category mix follows
    available stock proportions. If demand exceeds stock, all stock is allocated and
    order shortages remain proportional to requested quantities.
    """
    stock = {k: max(0, int(v)) for k, v in category_stock.items() if int(v) > 0}
    demand = {k: max(0, int(v)) for k, v in order_demand.items() if int(v) > 0}
    total_stock = sum(stock.values())
    total_demand = sum(demand.values())
    target = min(total_stock, total_demand)
    if target <= 0:
        return {}, {}, {}

    def margins(source: dict, total_source: int, target_sum: int):
        raw = {k: v * target_sum / total_source for k, v in source.items()}
        base = {k: int(math.floor(x)) for k, x in raw.items()}
        rem = target_sum - sum(base.values())
        for k in sorted(source, key=lambda kk: (raw[kk] - base[kk], source[kk]), reverse=True)[:rem]:
            base[k] += 1
        return base

    cat_quota = margins(stock, total_stock, target)
    order_quota = margins(demand, total_demand, target)

    matrix = {oid: {cat: 0 for cat in cat_quota} for oid in order_quota}
    fractions = []
    for oid, oq in order_quota.items():
        for cat, cq in cat_quota.items():
            raw = oq * cq / target
            base = int(math.floor(raw))
            matrix[oid][cat] = base
            fractions.append((raw - base, oid, cat))

    row_def = {oid: order_quota[oid] - sum(matrix[oid].values()) for oid in order_quota}
    col_def = {cat: cat_quota[cat] - sum(matrix[oid][cat] for oid in order_quota) for cat in cat_quota}

    for _, oid, cat in sorted(fractions, reverse=True):
        if row_def[oid] > 0 and col_def[cat] > 0:
            matrix[oid][cat] += 1
            row_def[oid] -= 1
            col_def[cat] -= 1

    # Deterministic fallback for any remaining integer deficits.
    for oid in order_quota:
        while row_def[oid] > 0:
            choices = [c for c in cat_quota if col_def[c] > 0]
            if not choices:
                break
            cat = max(choices, key=lambda c: col_def[c])
            matrix[oid][cat] += 1
            row_def[oid] -= 1
            col_def[cat] -= 1

    return matrix, cat_quota, order_quota
