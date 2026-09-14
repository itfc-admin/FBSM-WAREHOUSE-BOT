from __future__ import annotations

import math


def proportional_matrix(category_stock: dict[str, int], order_demand: dict[int, int]):
    stock = {k: max(0, int(v)) for k, v in category_stock.items() if int(v) > 0}
    demand = {k: max(0, int(v)) for k, v in order_demand.items() if int(v) > 0}

    total_stock = sum(stock.values())
    total_demand = sum(demand.values())
    target = min(total_stock, total_demand)

    if target <= 0:
        return {}, {}, {}

    def margins(source: dict, total_source: int, target_sum: int):
        raw = {
            k: v * target_sum / total_source
            for k, v in source.items()
        }

        base = {
            k: int(math.floor(x))
            for k, x in raw.items()
        }

        remainder = target_sum - sum(base.values())

        for k in sorted(
            source,
            key=lambda kk: (
                raw[kk] - base[kk],
                source[kk]
            ),
            reverse=True
        )[:remainder]:
            base[k] += 1

        return base

    cat_quota = margins(stock, total_stock, target)
    order_quota = margins(demand, total_demand, target)

    matrix = {
        order_id: {
            category: 0
            for category in cat_quota
        }
        for order_id in order_quota
    }

    fractions = []

    for order_id, order_qty in order_quota.items():
        for category, category_qty in cat_quota.items():

            raw = order_qty * category_qty / target
            base = int(math.floor(raw))

            matrix[order_id][category] = base
            fractions.append(
                (raw - base, order_id, category)
            )

    row_deficit = {
        order_id:
        order_quota[order_id]
        - sum(matrix[order_id].values())
        for order_id in order_quota
    }

    col_deficit = {
        category:
        cat_quota[category]
        - sum(
            matrix[order_id][category]
            for order_id in order_quota
        )
        for category in cat_quota
    }

    for _, order_id, category in sorted(fractions, reverse=True):

        if (
            row_deficit[order_id] > 0
            and col_deficit[category] > 0
        ):
            matrix[order_id][category] += 1
            row_deficit[order_id] -= 1
            col_deficit[category] -= 1

    for order_id in order_quota:

        while row_deficit[order_id] > 0:

            choices = [
                category
                for category in cat_quota
                if col_deficit[category] > 0
            ]

            if not choices:
                break

            category = max(
                choices,
                key=lambda c: col_deficit[c]
            )

            matrix[order_id][category] += 1
            row_deficit[order_id] -= 1
            col_deficit[category] -= 1

    return matrix, cat_quota, order_quota
