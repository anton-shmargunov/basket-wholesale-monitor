"""Queries for the home page, basket explorer, and wholesale aggregation.

StockQty_W is a snapshot for one week. Callers pass a single week and may sum
stock across baskets. A wholesale sale does not carry a basket: it counts for
a basket when its SKU is in that basket in the selected week. Each stored
wholesale row is one sold tire.
"""

from bskuw import db

WHOLESALE_GROUPS = ("SKU", "size", "brand", "name", "basket")

_WEEK_ORDER = """
ORDER BY
    TRY_CAST(split_part(year_week, '-', 1) AS INTEGER) DESC,
    TRY_CAST(split_part(year_week, '-', 2) AS INTEGER) DESC,
    year_week DESC
"""


def status():
    tracking_rows = db.fetch_one("SELECT count(*) FROM tracking")[0]
    sku_rows = db.fetch_one("SELECT count(*) FROM sku_dim")[0]
    wholesale_rows = db.fetch_one("SELECT count(*) FROM wholesale")[0]
    source_row = db.fetch_one("SELECT source FROM sku_dim LIMIT 1")
    weeks = db.fetch_dicts(
        """
        SELECT
            year_week AS "Week",
            count(*) AS "Rows",
            count(DISTINCT basket) AS "Baskets",
            count(DISTINCT sku) AS "SKUs"
        FROM tracking
        GROUP BY year_week
        {order}
        """.format(order=_WEEK_ORDER)
    )
    return {
        "tracking_rows": tracking_rows,
        "sku_rows": sku_rows,
        "sku_source": source_row[0] if source_row else None,
        "wholesale_rows": wholesale_rows,
        "weeks": weeks,
    }


def quant_report():
    """The stored quant file and its latest sales-order date, if already captured."""
    db.ensure_quant_report()
    row = db.fetch_one("SELECT source_file, last_sale_date FROM quant_report")
    if row is None:
        return {"known": False, "source_file": None, "last_sale_date": None}
    return {"known": True, "source_file": row[0], "last_sale_date": row[1]}


def quant_source_path():
    """Path of the quant file that produced the loaded wholesale rows."""
    row = db.fetch_one(
        """
        SELECT source_file
        FROM wholesale
        WHERE source_file IS NOT NULL AND source_file <> ''
        LIMIT 1
        """
    )
    if row and row[0]:
        return row[0]
    return None


def list_weeks():
    rows = db.fetchall(
        """
        SELECT year_week
        FROM (SELECT DISTINCT year_week FROM tracking) weeks
        {order}
        """.format(order=_WEEK_ORDER)
    )[1]
    return [row[0] for row in rows]


def list_baskets(year_week):
    rows = db.fetchall(
        """
        SELECT DISTINCT basket
        FROM tracking
        WHERE year_week = ?
        ORDER BY TRY_CAST(basket AS INTEGER), basket
        """,
        [year_week],
    )[1]
    return [row[0] for row in rows]


def list_product_bs(year_week):
    rows = db.fetchall(
        """
        SELECT DISTINCT product_bs
        FROM tracking
        WHERE year_week = ?
          AND product_bs IS NOT NULL
          AND product_bs <> ''
        ORDER BY product_bs
        """,
        [year_week],
    )[1]
    return [row[0] for row in rows]


def basket_summary(
    year_week,
    baskets,
    product_bs,
    sku,
    size,
    brand,
    name,
    start=None,
    end=None,
    wholesale_min=None,
    wholesale_max=None,
    include_outside=False,
    outside_only=False,
):
    if outside_only:
        return _outside_only_summary(
            year_week, baskets, product_bs, sku, size, brand, name, start, end, wholesale_min, wholesale_max
        )
    where, filter_params = _tracking_filters(year_week, baskets, product_bs, sku, size, brand, name)
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    bound_sql, bound_params = _count_bounds(wholesale_min, wholesale_max, "coalesce(ws.sold, 0)")
    outside_sql, outside_params = _outside_union(
        include_outside,
        product_bs,
        year_week,
        baskets,
        sku,
        size,
        brand,
        name,
        wholesale_min,
        wholesale_max,
        """
        SELECT
            outside_skus.sku,
            outside_skus.size,
            outside_skus.brand,
            outside_skus.name,
            outside_skus.dim_sku,
            CAST(0 AS DOUBLE) AS stock_qty_w,
            outside_skus.sold,
            1 AS sku_row
        FROM ({outside_select}) outside_skus
        """,
    )
    params = list(date_params) + list(filter_params) + list(bound_params) + list(outside_params)
    return db.fetch_dicts(
        """
        WITH sold AS (
            SELECT sku, count(*) AS sold
            FROM wholesale
            WHERE {date_where}
            GROUP BY sku
        ),
        rows AS (
            SELECT
                t.sku,
                d.size,
                d.brand,
                d.name,
                d.sku AS dim_sku,
                t.stock_qty_w,
                coalesce(ws.sold, 0) AS sold,
                row_number() OVER (PARTITION BY t.sku ORDER BY t.basket) AS sku_row
            FROM tracking t
            LEFT JOIN sku_dim d ON t.sku = d.sku
            LEFT JOIN sold ws ON t.sku = ws.sku
            WHERE {where} AND {bounds}
            {outside_sql}
        )
        SELECT
            count(*) AS rows,
            count(DISTINCT sku) AS sku_count,
            count(DISTINCT size) FILTER (WHERE size IS NOT NULL AND size <> '') AS size_count,
            count(DISTINCT brand) FILTER (WHERE brand IS NOT NULL AND brand <> '') AS brand_count,
            count(DISTINCT name) FILTER (WHERE name IS NOT NULL AND name <> '') AS name_count,
            coalesce(sum(stock_qty_w), 0) AS stock_qty_w,
            coalesce(sum(sold) FILTER (WHERE sku_row = 1), 0) AS wholesale,
            count(*) FILTER (WHERE dim_sku IS NULL) AS unmatched_rows
        FROM rows
        """.format(
            date_where=date_sql or "TRUE",
            where=where,
            bounds=bound_sql,
            outside_sql=outside_sql,
        ),
        params,
    )[0]


def basket_rows(
    year_week,
    baskets,
    product_bs,
    sku,
    size,
    brand,
    name,
    limit=None,
    start=None,
    end=None,
    wholesale_min=None,
    wholesale_max=None,
    include_outside=False,
    outside_only=False,
):
    if outside_only:
        return _outside_only_rows(
            year_week,
            baskets,
            product_bs,
            sku,
            size,
            brand,
            name,
            start,
            end,
            wholesale_min,
            wholesale_max,
            limit,
        )
    where, filter_params = _tracking_filters(year_week, baskets, product_bs, sku, size, brand, name)
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    bound_sql, bound_params = _count_bounds(wholesale_min, wholesale_max, "coalesce(ws.sold, 0)")
    outside_sql, outside_params = _outside_union(
        include_outside,
        product_bs,
        year_week,
        baskets,
        sku,
        size,
        brand,
        name,
        wholesale_min,
        wholesale_max,
        """
        SELECT
            '(no basket)' AS "Basket",
            outside_skus.sku AS "SKU",
            outside_skus.size AS "Size",
            outside_skus.brand AS "Brand",
            outside_skus.name AS "Name",
            outside_skus.model AS "Model",
            outside_skus.tread AS "Tread",
            outside_skus.condition AS "Condition",
            NULL AS "Product BS",
            CAST(0 AS DOUBLE) AS "Stock",
            outside_skus.sold AS "Wholesale"
        FROM ({outside_select}) outside_skus
        """,
    )
    limit_sql = ""
    params = list(date_params) + list(filter_params) + list(bound_params) + list(outside_params)
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(int(limit))
    return db.fetch_dicts(
        """
        WITH sold AS (
            SELECT sku, count(*) AS sold
            FROM wholesale
            WHERE {date_where}
            GROUP BY sku
        )
        SELECT *
        FROM (
            SELECT
                t.basket AS "Basket",
                t.sku AS "SKU",
                d.size AS "Size",
                d.brand AS "Brand",
                d.name AS "Name",
                d.model AS "Model",
                d.tread AS "Tread",
                d.condition AS "Condition",
                t.product_bs AS "Product BS",
                t.stock_qty_w AS "Stock",
                coalesce(ws.sold, 0) AS "Wholesale"
            FROM tracking t
            LEFT JOIN sku_dim d ON t.sku = d.sku
            LEFT JOIN sold ws ON t.sku = ws.sku
            WHERE {where} AND {bounds}
            {outside_sql}
        ) combined
        ORDER BY
            CASE WHEN "Basket" = '(no basket)' THEN 1 ELSE 0 END,
            TRY_CAST("Basket" AS INTEGER),
            "Basket",
            "Size",
            "SKU"
        {limit_sql}
        """.format(
            date_where=date_sql or "TRUE",
            where=where,
            bounds=bound_sql,
            outside_sql=outside_sql,
            limit_sql=limit_sql,
        ),
        params,
    )


def basket_grouped(
    year_week,
    baskets,
    product_bs,
    sku,
    size,
    brand,
    name,
    group_by,
    start=None,
    end=None,
    wholesale_min=None,
    wholesale_max=None,
    include_outside=False,
    outside_only=False,
):
    """Stock and wholesale for one grouping.

    Wholesale min and max keep SKUs whose own wholesale count is inside the
    range, and both totals use only those SKUs. Grouping by size, brand, name,
    or SKU counts each tire once. Grouping by basket counts a tire in every
    selected basket that contains its SKU. Stock is summed across the tracking
    rows that remain.
    """
    if group_by not in WHOLESALE_GROUPS:
        raise ValueError("Unknown grouping: {group}".format(group=group_by))
    head, params = _filtered_members_sql(
        year_week,
        baskets,
        product_bs,
        sku,
        size,
        brand,
        name,
        start,
        end,
        wholesale_min,
        wholesale_max,
        include_outside,
        outside_only,
    )
    if group_by == "basket":
        body = """
        SELECT
            basket AS "Basket",
            count(DISTINCT sku) AS "SKUs",
            coalesce(sum(stock), 0) AS "Stock",
            coalesce(sum(sold), 0) AS "Wholesale"
        FROM filtered
        GROUP BY basket
        ORDER BY
            CASE WHEN basket = '(no basket)' THEN 1 ELSE 0 END,
            "Stock" DESC,
            "Wholesale" DESC,
            TRY_CAST(basket AS INTEGER),
            basket
        """
    else:
        column = {"SKU": "sku", "size": "size", "brand": "brand", "name": "name"}[group_by]
        label = {"SKU": "SKU", "size": "Size", "brand": "Brand", "name": "Name"}[group_by]
        body = """
        SELECT
            {column} AS "{label}",
            count(*) AS "SKUs",
            coalesce(sum(stock), 0) AS "Stock",
            coalesce(sum(sold), 0) AS "Wholesale"
        FROM (
            SELECT
                sku,
                any_value(size) AS size,
                any_value(brand) AS brand,
                any_value(name) AS name,
                sum(stock) AS stock,
                max(sold) AS sold
            FROM filtered
            GROUP BY sku
        ) sku_level
        GROUP BY {column}
        ORDER BY "Stock" DESC, "Wholesale" DESC, "{label}"
        """.format(column=column, label=label)
    return db.fetch_dicts(head + body, params)


def wholesale_unparsed_dates():
    return db.fetch_one("SELECT count(*) FROM wholesale WHERE sale_date IS NULL")[0]


def wholesale_count(year_week, baskets, sku, size, brand, name, start, end):
    """Count sold wholesale tires once, even when a SKU sits in several baskets."""
    where, params = _wholesale_where(year_week, baskets, sku, size, brand, name, start, end)
    return db.fetch_one(
        """
        SELECT count(*)
        FROM wholesale w
        LEFT JOIN sku_dim d ON w.sku = d.sku
        WHERE {where}
        """.format(where=where),
        params,
    )[0]


def wholesale_summary(year_week, baskets, sku, size, brand, name, group_by, start, end):
    """Count sold wholesale tires.

    Grouping by basket counts a tire in every selected basket that contains its
    SKU. Grouping by SKU, size, brand, or name counts each tire once.
    start and end are inclusive. None means that side is unlimited.
    """
    if group_by not in WHOLESALE_GROUPS:
        raise ValueError("Unknown grouping: {group}".format(group=group_by))

    if group_by == "basket":
        sku_where, sku_params = _sku_membership_filters(year_week, baskets, sku, size, brand, name)
        date_sql, date_params = _sale_date_sql(start, end)
        return db.fetch_dicts(
            """
            WITH members AS (
                SELECT DISTINCT t.sku, t.basket
                FROM tracking t
                LEFT JOIN sku_dim d ON t.sku = d.sku
                WHERE {sku_where}
            )
            SELECT
                m.basket AS "Basket",
                count(*) AS "Sold"
            FROM wholesale w
            INNER JOIN members m ON w.sku = m.sku
            WHERE {date_where}
            GROUP BY m.basket
            ORDER BY "Sold" DESC, m.basket
            """.format(
                sku_where=sku_where,
                date_where=date_sql or "TRUE",
            ),
            list(sku_params) + list(date_params),
        )

    expressions = {
        "SKU": 'coalesce(w.sku, \'(no SKU)\') AS "SKU"',
        "size": 'coalesce(nullif(d.size, \'\'), \'(no size)\') AS "Size"',
        "brand": 'coalesce(nullif(d.brand, \'\'), \'(no brand)\') AS "Brand"',
        "name": 'coalesce(nullif(d.name, \'\'), \'(no name)\') AS "Name"',
    }
    where, params = _wholesale_where(year_week, baskets, sku, size, brand, name, start, end)
    return db.fetch_dicts(
        """
        SELECT
            {expression},
            count(*) AS "Sold"
        FROM wholesale w
        LEFT JOIN sku_dim d ON w.sku = d.sku
        WHERE {where}
        GROUP BY 1
        ORDER BY "Sold" DESC
        """.format(expression=expressions[group_by], where=where),
        params,
    )


def _filtered_members_sql(
    year_week,
    baskets,
    product_bs,
    sku,
    size,
    brand,
    name,
    start,
    end,
    wholesale_min,
    wholesale_max,
    include_outside=False,
    outside_only=False,
):
    if outside_only:
        return _outside_only_members_sql(
            year_week, baskets, product_bs, sku, size, brand, name, start, end, wholesale_min, wholesale_max
        )
    where, filter_params = _tracking_filters(year_week, baskets, product_bs, sku, size, brand, name)
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    bound_sql, bound_params = _count_bounds(wholesale_min, wholesale_max, "coalesce(s.sold, 0)")
    outside_sql, outside_params = _outside_union(
        include_outside,
        product_bs,
        year_week,
        baskets,
        sku,
        size,
        brand,
        name,
        wholesale_min,
        wholesale_max,
        """
        SELECT
            '(no basket)' AS basket,
            outside_skus.sku,
            coalesce(nullif(outside_skus.size, ''), '(no size)') AS size,
            coalesce(nullif(outside_skus.brand, ''), '(no brand)') AS brand,
            coalesce(nullif(outside_skus.name, ''), '(no name)') AS name,
            CAST(0 AS DOUBLE) AS stock,
            outside_skus.sold
        FROM ({outside_select}) outside_skus
        """,
    )
    sql = """
        WITH member AS (
            SELECT
                t.basket,
                t.sku,
                coalesce(nullif(d.size, ''), '(no size)') AS size,
                coalesce(nullif(d.brand, ''), '(no brand)') AS brand,
                coalesce(nullif(d.name, ''), '(no name)') AS name,
                sum(t.stock_qty_w) AS stock
            FROM tracking t
            LEFT JOIN sku_dim d ON t.sku = d.sku
            WHERE {where}
            GROUP BY
                t.basket,
                t.sku,
                coalesce(nullif(d.size, ''), '(no size)'),
                coalesce(nullif(d.brand, ''), '(no brand)'),
                coalesce(nullif(d.name, ''), '(no name)')
        ),
        sold AS (
            SELECT sku, count(*) AS sold
            FROM wholesale
            WHERE {date_where}
            GROUP BY sku
        ),
        filtered AS (
            SELECT
                m.basket,
                m.sku,
                m.size,
                m.brand,
                m.name,
                m.stock,
                coalesce(s.sold, 0) AS sold
            FROM member m
            LEFT JOIN sold s ON m.sku = s.sku
            WHERE {bounds}
            {outside_sql}
        )
    """.format(
        where=where,
        date_where=date_sql or "TRUE",
        bounds=bound_sql,
        outside_sql=outside_sql,
    )
    return sql, list(filter_params) + list(date_params) + list(bound_params) + list(outside_params)


def _empty_basket_summary():
    return {
        "rows": 0,
        "sku_count": 0,
        "size_count": 0,
        "brand_count": 0,
        "name_count": 0,
        "stock_qty_w": 0,
        "wholesale": 0,
        "unmatched_rows": 0,
    }


def _outside_only_summary(
    year_week, baskets, product_bs, sku, size, brand, name, start, end, wholesale_min, wholesale_max
):
    if product_bs:
        return _empty_basket_summary()
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    outside_select, outside_params = _outside_skus_sql(
        year_week, baskets, sku, size, brand, name, wholesale_min, wholesale_max
    )
    return db.fetch_dicts(
        """
        WITH sold AS (
            SELECT sku, count(*) AS sold
            FROM wholesale
            WHERE {date_where}
            GROUP BY sku
        ),
        rows AS (
            SELECT
                outside_skus.sku,
                outside_skus.size,
                outside_skus.brand,
                outside_skus.name,
                outside_skus.dim_sku,
                CAST(0 AS DOUBLE) AS stock_qty_w,
                outside_skus.sold,
                1 AS sku_row
            FROM ({outside_select}) outside_skus
        )
        SELECT
            count(*) AS rows,
            count(DISTINCT sku) AS sku_count,
            count(DISTINCT size) FILTER (WHERE size IS NOT NULL AND size <> '') AS size_count,
            count(DISTINCT brand) FILTER (WHERE brand IS NOT NULL AND brand <> '') AS brand_count,
            count(DISTINCT name) FILTER (WHERE name IS NOT NULL AND name <> '') AS name_count,
            coalesce(sum(stock_qty_w), 0) AS stock_qty_w,
            coalesce(sum(sold), 0) AS wholesale,
            count(*) FILTER (WHERE dim_sku IS NULL) AS unmatched_rows
        FROM rows
        """.format(date_where=date_sql or "TRUE", outside_select=outside_select),
        list(date_params) + list(outside_params),
    )[0]


def _outside_only_rows(
    year_week, baskets, product_bs, sku, size, brand, name, start, end, wholesale_min, wholesale_max, limit
):
    if product_bs:
        return []
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    outside_select, outside_params = _outside_skus_sql(
        year_week, baskets, sku, size, brand, name, wholesale_min, wholesale_max
    )
    limit_sql = ""
    params = list(date_params) + list(outside_params)
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(int(limit))
    return db.fetch_dicts(
        """
        WITH sold AS (
            SELECT sku, count(*) AS sold
            FROM wholesale
            WHERE {date_where}
            GROUP BY sku
        )
        SELECT
            '(no basket)' AS "Basket",
            outside_skus.sku AS "SKU",
            outside_skus.size AS "Size",
            outside_skus.brand AS "Brand",
            outside_skus.name AS "Name",
            outside_skus.model AS "Model",
            outside_skus.tread AS "Tread",
            outside_skus.condition AS "Condition",
            NULL AS "Product BS",
            CAST(0 AS DOUBLE) AS "Stock",
            outside_skus.sold AS "Wholesale"
        FROM ({outside_select}) outside_skus
        ORDER BY "Size", "SKU"
        {limit_sql}
        """.format(
            date_where=date_sql or "TRUE",
            outside_select=outside_select,
            limit_sql=limit_sql,
        ),
        params,
    )


def _outside_only_members_sql(
    year_week, baskets, product_bs, sku, size, brand, name, start, end, wholesale_min, wholesale_max
):
    if product_bs:
        return (
            """
            WITH filtered AS (
                SELECT
                    CAST(NULL AS VARCHAR) AS basket,
                    CAST(NULL AS VARCHAR) AS sku,
                    CAST(NULL AS VARCHAR) AS size,
                    CAST(NULL AS VARCHAR) AS brand,
                    CAST(NULL AS VARCHAR) AS name,
                    CAST(0 AS DOUBLE) AS stock,
                    CAST(0 AS BIGINT) AS sold
                WHERE FALSE
            )
            """,
            [],
        )
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    outside_select, outside_params = _outside_skus_sql(
        year_week, baskets, sku, size, brand, name, wholesale_min, wholesale_max
    )
    sql = """
        WITH sold AS (
            SELECT sku, count(*) AS sold
            FROM wholesale
            WHERE {date_where}
            GROUP BY sku
        ),
        filtered AS (
            SELECT
                '(no basket)' AS basket,
                outside_skus.sku,
                coalesce(nullif(outside_skus.size, ''), '(no size)') AS size,
                coalesce(nullif(outside_skus.brand, ''), '(no brand)') AS brand,
                coalesce(nullif(outside_skus.name, ''), '(no name)') AS name,
                CAST(0 AS DOUBLE) AS stock,
                outside_skus.sold
            FROM ({outside_select}) outside_skus
        )
    """.format(date_where=date_sql or "TRUE", outside_select=outside_select)
    return sql, list(date_params) + list(outside_params)


def _outside_union(
    include_outside,
    product_bs,
    year_week,
    baskets,
    sku,
    size,
    brand,
    name,
    wholesale_min,
    wholesale_max,
    wrapper,
):
    """Rows for wholesale SKUs that are absent from the selected tracking baskets.

    A product BS filter leaves these SKUs out: they have no product BS.
    """
    if not include_outside or product_bs:
        return "", []
    outside_select, params = _outside_skus_sql(
        year_week, baskets, sku, size, brand, name, wholesale_min, wholesale_max
    )
    return "UNION ALL " + wrapper.format(outside_select=outside_select), params


def _outside_skus_sql(year_week, baskets, sku, size, brand, name, wholesale_min, wholesale_max):
    membership, membership_params = _tracking_membership(year_week, baskets)
    text_sql, text_params = _contains_sql(
        (("w.sku", sku), ("d.size", size), ("d.brand", brand), ("d.name", name))
    )
    bound_sql, bound_params = _count_bounds(wholesale_min, wholesale_max, "w.sold")
    clauses = [
        "NOT EXISTS (SELECT 1 FROM tracking t WHERE t.sku = w.sku AND {membership})".format(
            membership=membership
        )
    ]
    if text_sql:
        clauses.append(text_sql)
    if bound_sql != "TRUE":
        clauses.append(bound_sql)
    sql = """
        SELECT
            w.sku,
            d.size,
            d.brand,
            d.name,
            d.model,
            d.tread,
            d.condition,
            d.sku AS dim_sku,
            w.sold
        FROM sold w
        LEFT JOIN sku_dim d ON w.sku = d.sku
        WHERE {where}
    """.format(where=" AND ".join(clauses))
    return sql, list(membership_params) + list(text_params) + list(bound_params)


def _tracking_membership(year_week, baskets):
    params = [year_week]
    if not baskets:
        return "t.year_week = ?", params
    basket_sql = _in_clause("t.basket", baskets, params)
    return "t.year_week = ? AND {baskets}".format(baskets=basket_sql), params


def _tracking_filters(year_week, baskets, product_bs, sku, size, brand, name):
    clauses = ["t.year_week = ?"]
    params = [year_week]
    clauses.append(_in_clause("t.basket", baskets, params))
    if product_bs:
        clauses.append(_in_clause("t.product_bs", product_bs, params))
    text_sql, text_params = _contains_sql(
        (("t.sku", sku), ("d.size", size), ("d.brand", brand), ("d.name", name))
    )
    if text_sql:
        clauses.append(text_sql)
        params.extend(text_params)
    return " AND ".join(clauses), params


def _contains_sql(pairs):
    clauses = []
    params = []
    for column, value in pairs:
        if value and str(value).strip():
            clauses.append("contains(lower(coalesce({column}, '')), ?)".format(column=column))
            params.append(str(value).strip().lower())
    return " AND ".join(clauses), params


def _count_bounds(minimum, maximum, column):
    clauses = []
    params = []
    if minimum is not None:
        clauses.append("{column} >= ?".format(column=column))
        params.append(int(minimum))
    if maximum is not None:
        clauses.append("{column} <= ?".format(column=column))
        params.append(int(maximum))
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def _wholesale_where(year_week, baskets, sku, size, brand, name, start, end):
    clauses = []
    params = []
    date_sql, date_params = _sale_date_sql(start, end)
    if date_sql:
        clauses.append(date_sql)
        params.extend(date_params)
    if baskets:
        clauses.append(
            """w.sku IN (
                SELECT DISTINCT t.sku
                FROM tracking t
                WHERE t.year_week = ?
                  AND {baskets}
            )""".format(baskets=_in_clause("t.basket", baskets, params))
        )
        params.insert(len(date_params), year_week)
    text_sql, text_params = _contains_sql(
        (("w.sku", sku), ("d.size", size), ("d.brand", brand), ("d.name", name))
    )
    if text_sql:
        clauses.append(text_sql)
        params.extend(text_params)
    return " AND ".join(clauses) if clauses else "TRUE", params


def _sale_date_sql(start, end, column="w.sale_date"):
    clauses = []
    params = []
    if start is not None:
        clauses.append("{column} >= ?".format(column=column))
        params.append(start)
    if end is not None:
        clauses.append("{column} <= ?".format(column=column))
        params.append(end)
    return " AND ".join(clauses), params


def _sku_membership_filters(year_week, baskets, sku, size, brand, name):
    clauses = ["t.year_week = ?"]
    params = [year_week]
    if baskets:
        clauses.append(_in_clause("t.basket", baskets, params))
    text_sql, text_params = _contains_sql(
        (("t.sku", sku), ("d.size", size), ("d.brand", brand), ("d.name", name))
    )
    if text_sql:
        clauses.append(text_sql)
        params.extend(text_params)
    return " AND ".join(clauses), params


def _in_clause(column, values, params):
    if not values:
        raise ValueError("Select at least one basket.")
    params.extend(values)
    return "{column} IN ({placeholders})".format(
        column=column,
        placeholders=", ".join(["?"] * len(values)),
    )
