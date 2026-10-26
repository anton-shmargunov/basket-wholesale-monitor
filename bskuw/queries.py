"""Queries for the home page, basket explorer, and wholesale aggregation.

StockQty_W is a snapshot for one week. Callers pass a single week and may sum
stock across baskets. A wholesale sale does not carry a basket: it counts for
a basket when its SKU is in that basket in the selected week. Each stored
wholesale row is one sold tire. Majority decides that tire's grade. The sale
counts for that grade even when the tracking snapshot has stock only for
another grade of the same SKU.
"""

from bskuw import db

GRADE_OPTIONS = ("", "A", "B")
GRADE_HELP = (
    "Empty includes every grade. "
    "A counts Majority No Repair and Minor Repair. "
    "B counts Major Repair and Close to Sidewall. "
    "One SKU can have both grades. "
    "A grade still counts when that grade has no stock."
)

WHOLESALE_GROUPS = (
    "SKU",
    "Size",
    "Section",
    "Aspect",
    "Rim",
    "Section-Aspect-Rim",
    "Brand",
    "Name",
    "Basket",
)

_WEEK_ORDER = """
ORDER BY
    TRY_CAST(split_part(year_week, '-', 1) AS INTEGER) DESC,
    TRY_CAST(split_part(year_week, '-', 2) AS INTEGER) DESC,
    year_week DESC
"""


def _filled(column, label):
    """Blank text becomes a visible group such as (no section)."""
    return "coalesce(nullif(trim({column}), ''), '(no {label})')".format(column=column, label=label)


def _group_key(group_by, sku, size, section, aspect, rim, brand, name):
    """Return the grouping expression and its column label."""
    section_text = _filled(section, "section")
    aspect_text = _filled(aspect, "aspect")
    rim_text = _filled(rim, "rim")
    keys = {
        "SKU": (_filled(sku, "SKU"), "SKU"),
        "Size": (_filled(size, "size"), "Size"),
        "Section": (section_text, "Section"),
        "Aspect": (aspect_text, "Aspect"),
        "Rim": (rim_text, "Rim"),
        "Section-Aspect-Rim": (
            "{section} || '-' || {aspect} || '-' || {rim}".format(
                section=section_text, aspect=aspect_text, rim=rim_text
            ),
            "Section-Aspect-Rim",
        ),
        "Brand": (_filled(brand, "brand"), "Brand"),
        "Name": (_filled(name, "name"), "Name"),
    }
    return keys[group_by]


def _dimension_columns(section, aspect, rim, label):
    """Section, Aspect, and Rim columns for groups where each value is unique.

    Grouping by only one of them leaves the other two out, because one Section
    contains many Aspects and Rims.
    """
    if label in ("Section", "Aspect", "Rim"):
        return ""
    columns = [
        'mode({column}) AS "Section"'.format(column=section),
        'mode({column}) AS "Aspect"'.format(column=aspect),
        'mode({column}) AS "Rim"'.format(column=rim),
    ]
    return ",\n            ".join(columns) + ","


def _clean_grade(grade):
    if grade is None:
        return None
    text = str(grade).strip().upper()
    if text in ("A", "B"):
        return text
    return None


def _sale_grade_expr(column):
    """Map a quant Majority value to tracking grade A or B."""
    return (
        "CASE"
        " WHEN trim(coalesce({column}, '')) IN ('No Repair', 'Minor Repair') THEN 'A'"
        " WHEN trim(coalesce({column}, '')) IN ('Major Repair', 'Close to Sidewall') THEN 'B'"
        " ELSE NULL END"
    ).format(column=column)


def _sale_grade_clause(grade, column):
    value = _clean_grade(grade)
    if not value:
        return "TRUE"
    return "{expr} = '{value}'".format(expr=_sale_grade_expr(column), value=value)


def _tracking_grade_clause(grade, column="t.grade"):
    value = _clean_grade(grade)
    if not value:
        return "TRUE"
    return "trim(coalesce({column}, '')) = '{value}'".format(column=column, value=value)


def _sold_sql(date_where, grade, majority_column="majority"):
    return """
            SELECT
                sku,
                {expr} AS sale_grade,
                count(*) AS sold
            FROM wholesale
            WHERE {date_where} AND {grade_where}
            GROUP BY 1, 2
    """.format(
        expr=_sale_grade_expr(majority_column),
        date_where=date_where or "TRUE",
        grade_where=_sale_grade_clause(grade, majority_column),
    )


def _stored_grade_clause(grade, column):
    """Keep one stored grade. Empty grade keeps every stored grade."""
    value = _clean_grade(grade)
    if not value:
        return "TRUE"
    return "{column} = '{value}'".format(column=column, value=value)


def _graded_ctes(member_where, date_where, grade):
    """Stock rows by tracking grade, plus sales of a grade that has no stock.

    present is every tracking grade in the selected baskets. sold is wholesale
    by Majority. extra is a stock-0 row for a Majority grade the basket does
    not already list for that SKU.
    """
    return """
        sold AS (
            {sold_sql}
        ),
        present AS (
            SELECT
                t.basket,
                t.sku,
                coalesce(nullif(trim(t.grade), ''), '') AS grade,
                any_value(t.product_bs) AS product_bs,
                any_value(d.size) AS size,
                any_value(d.section) AS section,
                any_value(d.aspect) AS aspect,
                any_value(d.rim) AS rim,
                any_value(d.brand) AS brand,
                any_value(d.name) AS name,
                any_value(d.model) AS model,
                any_value(d.tread) AS tread,
                any_value(d.condition) AS condition,
                any_value(d.sku) AS dim_sku,
                sum(t.stock_qty_w) AS stock
            FROM tracking t
            LEFT JOIN sku_dim d ON t.sku = d.sku
            WHERE {member_where}
            GROUP BY t.basket, t.sku, coalesce(nullif(trim(t.grade), ''), '')
        ),
        extra AS (
            SELECT
                p.basket,
                p.sku,
                coalesce(s.sale_grade, '') AS grade,
                any_value(p.product_bs) AS product_bs,
                any_value(p.size) AS size,
                any_value(p.section) AS section,
                any_value(p.aspect) AS aspect,
                any_value(p.rim) AS rim,
                any_value(p.brand) AS brand,
                any_value(p.name) AS name,
                any_value(p.model) AS model,
                any_value(p.tread) AS tread,
                any_value(p.condition) AS condition,
                any_value(p.dim_sku) AS dim_sku,
                CAST(0 AS DOUBLE) AS stock,
                any_value(s.sold) AS sold
            FROM present p
            JOIN sold s ON s.sku = p.sku
            WHERE NOT EXISTS (
                SELECT 1
                FROM present g
                WHERE g.basket = p.basket
                  AND g.sku = p.sku
                  AND g.grade = coalesce(s.sale_grade, '')
            )
            GROUP BY p.basket, p.sku, coalesce(s.sale_grade, '')
        ),
        graded AS (
            SELECT
                p.basket,
                p.sku,
                p.grade,
                p.product_bs,
                p.size,
                p.section,
                p.aspect,
                p.rim,
                p.brand,
                p.name,
                p.model,
                p.tread,
                p.condition,
                p.dim_sku,
                p.stock,
                coalesce(s.sold, 0) AS sold
            FROM present p
            LEFT JOIN sold s
                ON s.sku = p.sku
               AND coalesce(s.sale_grade, '') = p.grade
            WHERE {stored_grade}
            UNION ALL
            SELECT
                e.basket,
                e.sku,
                e.grade,
                e.product_bs,
                e.size,
                e.section,
                e.aspect,
                e.rim,
                e.brand,
                e.name,
                e.model,
                e.tread,
                e.condition,
                e.dim_sku,
                e.stock,
                e.sold
            FROM extra e
            WHERE {extra_grade}
        )
    """.format(
        sold_sql=_sold_sql(date_where, grade),
        member_where=member_where,
        stored_grade=_stored_grade_clause(grade, "p.grade"),
        extra_grade=_stored_grade_clause(grade, "e.grade"),
    )


def grade_data_loaded():
    """How many tracking rows have a grade, and how many sales have a Majority."""
    tracking = db.fetch_one(
        "SELECT count(*) FROM tracking WHERE nullif(trim(grade), '') IS NOT NULL"
    )[0]
    sales = db.fetch_one(
        "SELECT count(*) FROM wholesale WHERE nullif(trim(majority), '') IS NOT NULL"
    )[0]
    return {"tracking": tracking, "wholesale": sales}


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


def list_treads():
    """Tread values kept from the quant report.

    The number before the slash orders 4/32 before 4.5/32.
    """
    rows = db.fetchall(
        """
        SELECT DISTINCT trim(tread) AS tread
        FROM sku_dim
        WHERE nullif(trim(tread), '') IS NOT NULL
        ORDER BY TRY_CAST(split_part(trim(tread), '/', 1) AS DOUBLE), tread
        """
    )[1]
    return [row[0] for row in rows]


def basket_summary(
    year_week,
    baskets,
    product_bs,
    sku,
    size,
    section,
    aspect,
    rim,
    brand,
    name,
    start=None,
    end=None,
    wholesale_min=None,
    wholesale_max=None,
    include_outside=False,
    outside_only=False,
    grade=None,
    treads=None,
):
    if outside_only:
        return _outside_only_summary(
            year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, start, end, wholesale_min, wholesale_max, grade, treads
        )
    where, filter_params = _tracking_filters(
        year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, grade=None, treads=treads
    )
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    bound_sql, bound_params = _count_bounds(wholesale_min, wholesale_max, "sold")
    outside_sql, outside_params = _outside_union(
        include_outside,
        product_bs,
        year_week,
        baskets,
        sku,
        size,
        section,
        aspect,
        rim,
        brand,
        name,
        wholesale_min,
        wholesale_max,
        treads=treads,
        wrapper="""
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
        WITH {graded_ctes},
        rows AS (
            SELECT
                sku,
                size,
                brand,
                name,
                dim_sku,
                stock AS stock_qty_w,
                sold,
                row_number() OVER (
                    PARTITION BY sku, grade
                    ORDER BY basket
                ) AS sku_row
            FROM graded
            WHERE {bounds}
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
            graded_ctes=_graded_ctes(where, date_sql, grade),
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
    section,
    aspect,
    rim,
    brand,
    name,
    limit=None,
    start=None,
    end=None,
    wholesale_min=None,
    wholesale_max=None,
    include_outside=False,
    outside_only=False,
    grade=None,
    treads=None,
):
    if outside_only:
        return _outside_only_rows(
            year_week,
            baskets,
            product_bs,
            sku,
            size,
            section,
            aspect,
            rim,
            brand,
            name,
            start,
            end,
            wholesale_min,
            wholesale_max,
            limit,
            grade,
            treads,
        )
    where, filter_params = _tracking_filters(
        year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, grade=None, treads=treads
    )
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    bound_sql, bound_params = _count_bounds(wholesale_min, wholesale_max, "sold")
    outside_sql, outside_params = _outside_union(
        include_outside,
        product_bs,
        year_week,
        baskets,
        sku,
        size,
        section,
        aspect,
        rim,
        brand,
        name,
        wholesale_min,
        wholesale_max,
        treads=treads,
        wrapper="""
        SELECT
            '(no basket)' AS "Basket",
            outside_skus.sku AS "SKU",
            outside_skus.sale_grade AS "Grade",
            outside_skus.size AS "Size",
            outside_skus.section AS "Section",
            outside_skus.aspect AS "Aspect",
            outside_skus.rim AS "Rim",
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
        WITH {graded_ctes}
        SELECT *
        FROM (
            SELECT
                basket AS "Basket",
                sku AS "SKU",
                nullif(grade, '') AS "Grade",
                size AS "Size",
                section AS "Section",
                aspect AS "Aspect",
                rim AS "Rim",
                brand AS "Brand",
                name AS "Name",
                model AS "Model",
                tread AS "Tread",
                condition AS "Condition",
                product_bs AS "Product BS",
                stock AS "Stock",
                sold AS "Wholesale"
            FROM graded
            WHERE {bounds}
            {outside_sql}
        ) combined
        ORDER BY
            CASE WHEN "Basket" = '(no basket)' THEN 1 ELSE 0 END,
            TRY_CAST("Basket" AS INTEGER),
            "Basket",
            "Size",
            "SKU",
            "Grade"
        {limit_sql}
        """.format(
            graded_ctes=_graded_ctes(where, date_sql, grade),
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
    section,
    aspect,
    rim,
    brand,
    name,
    group_by,
    start=None,
    end=None,
    wholesale_min=None,
    wholesale_max=None,
    include_outside=False,
    outside_only=False,
    grade=None,
    treads=None,
):
    """Stock and wholesale for one grouping.

    Wholesale min and max keep SKUs whose own wholesale count is inside the
    range, and both totals use only those SKUs. Grouping by size, section, aspect,
    rim, the section-aspect-rim combination, brand, name, or SKU counts each tire once.
    Grouping by basket counts a tire in every
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
        section,
        aspect,
        rim,
        brand,
        name,
        start,
        end,
        wholesale_min,
        wholesale_max,
        include_outside,
        outside_only,
        grade,
        treads,
    )
    if group_by == "Basket":
        body = """
        SELECT
            basket AS "Basket",
            mode(section) AS "Section",
            mode(aspect) AS "Aspect",
            mode(rim) AS "Rim",
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
        column, label = _group_key(
            group_by,
            sku="sku",
            size="size",
            section="section",
            aspect="aspect",
            rim="rim",
            brand="brand",
            name="name",
        )
        body = """
        SELECT
            {column} AS "{label}",
            {dimensions}
            count(*) AS "SKUs",
            coalesce(sum(stock), 0) AS "Stock",
            coalesce(sum(sold), 0) AS "Wholesale"
        FROM (
            SELECT
                sku,
                any_value(size) AS size,
                any_value(section) AS section,
                any_value(aspect) AS aspect,
                any_value(rim) AS rim,
                any_value(brand) AS brand,
                any_value(name) AS name,
                sum(stock) AS stock,
                sum(sold) AS sold
            FROM (
                SELECT
                    sku,
                    grade,
                    any_value(size) AS size,
                    any_value(section) AS section,
                    any_value(aspect) AS aspect,
                    any_value(rim) AS rim,
                    any_value(brand) AS brand,
                    any_value(name) AS name,
                    sum(stock) AS stock,
                    max(sold) AS sold
                FROM filtered
                GROUP BY sku, grade
            ) per_grade
            GROUP BY sku
        ) sku_level
        GROUP BY {column}
        ORDER BY "Stock" DESC, "Wholesale" DESC, "{label}"
        """.format(
            column=column,
            label=label,
            dimensions=_dimension_columns("section", "aspect", "rim", label),
        )
    return db.fetch_dicts(head + body, params)


def wholesale_unparsed_dates():
    return db.fetch_one("SELECT count(*) FROM wholesale WHERE sale_date IS NULL")[0]


def wholesale_count(year_week, baskets, sku, size, section, aspect, rim, brand, name, start, end, grade=None, treads=None):
    """Count sold wholesale tires once, even when a SKU sits in several baskets."""
    where, params = _wholesale_where(year_week, baskets, sku, size, section, aspect, rim, brand, name, start, end, grade, treads)
    return db.fetch_one(
        """
        SELECT count(*)
        FROM wholesale w
        LEFT JOIN sku_dim d ON w.sku = d.sku
        WHERE {where}
        """.format(where=where),
        params,
    )[0]


def wholesale_summary(year_week, baskets, sku, size, section, aspect, rim, brand, name, group_by, start, end, grade=None, treads=None):
    """Count sold wholesale tires.

    Grouping by basket counts a tire in every selected basket that contains its
    SKU. Every other grouping counts each tire once.
    start and end are inclusive. None means that side is unlimited.
    """
    if group_by not in WHOLESALE_GROUPS:
        raise ValueError("Unknown grouping: {group}".format(group=group_by))

    if group_by == "Basket":
        sku_where, sku_params = _sku_membership_filters(year_week, baskets, sku, size, section, aspect, rim, brand, name, grade, treads)
        date_sql, date_params = _sale_date_sql(start, end)
        return db.fetch_dicts(
            """
            WITH members AS (
                SELECT DISTINCT t.sku, t.basket, d.section, d.aspect, d.rim
                FROM tracking t
                LEFT JOIN sku_dim d ON t.sku = d.sku
                WHERE {sku_where}
            )
            SELECT
                m.basket AS "Basket",
                mode(m.section) AS "Section",
                mode(m.aspect) AS "Aspect",
                mode(m.rim) AS "Rim",
                count(*) AS "Sold"
            FROM wholesale w
            INNER JOIN members m ON w.sku = m.sku
            WHERE {date_where} AND {sale_grade}
            GROUP BY m.basket
            ORDER BY "Sold" DESC, m.basket
            """.format(
                sku_where=sku_where,
                date_where=date_sql or "TRUE",
                sale_grade=_sale_grade_clause(grade, "w.majority"),
            ),
            list(sku_params) + list(date_params),
        )

    column, label = _group_key(
        group_by,
        sku="w.sku",
        size="d.size",
        section="d.section",
        aspect="d.aspect",
        rim="d.rim",
        brand="d.brand",
        name="d.name",
    )
    where, params = _wholesale_where(year_week, baskets, sku, size, section, aspect, rim, brand, name, start, end, grade, treads)
    return db.fetch_dicts(
        """
        SELECT
            {column} AS "{label}",
            {dimensions}
            count(*) AS "Sold"
        FROM wholesale w
        LEFT JOIN sku_dim d ON w.sku = d.sku
        WHERE {where}
        GROUP BY 1
        ORDER BY "Sold" DESC
        """.format(
            column=column,
            label=label,
            dimensions=_dimension_columns("d.section", "d.aspect", "d.rim", label),
            where=where,
        ),
        params,
    )


def _filtered_members_sql(
    year_week,
    baskets,
    product_bs,
    sku,
    size,
    section,
    aspect,
    rim,
    brand,
    name,
    start,
    end,
    wholesale_min,
    wholesale_max,
    include_outside=False,
    outside_only=False,
    grade=None,
    treads=None,
):
    if outside_only:
        return _outside_only_members_sql(
            year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, start, end, wholesale_min, wholesale_max, grade, treads
        )
    where, filter_params = _tracking_filters(
        year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, grade=None, treads=treads
    )
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    bound_sql, bound_params = _count_bounds(wholesale_min, wholesale_max, "g.sold")
    outside_sql, outside_params = _outside_union(
        include_outside,
        product_bs,
        year_week,
        baskets,
        sku,
        size,
        section,
        aspect,
        rim,
        brand,
        name,
        wholesale_min,
        wholesale_max,
        treads=treads,
        wrapper="""
        SELECT
            '(no basket)' AS basket,
            outside_skus.sku,
            coalesce(outside_skus.sale_grade, '') AS grade,
            coalesce(nullif(outside_skus.size, ''), '(no size)') AS size,
            outside_skus.section,
            outside_skus.aspect,
            outside_skus.rim,
            coalesce(nullif(outside_skus.brand, ''), '(no brand)') AS brand,
            coalesce(nullif(outside_skus.name, ''), '(no name)') AS name,
            CAST(0 AS DOUBLE) AS stock,
            outside_skus.sold AS sold
        FROM ({outside_select}) outside_skus
        """,
    )
    sql = """
        WITH {graded_ctes},
        filtered AS (
            SELECT
                g.basket,
                g.sku,
                g.grade,
                coalesce(nullif(g.size, ''), '(no size)') AS size,
                g.section,
                g.aspect,
                g.rim,
                coalesce(nullif(g.brand, ''), '(no brand)') AS brand,
                coalesce(nullif(g.name, ''), '(no name)') AS name,
                g.stock,
                g.sold
            FROM graded g
            WHERE {bounds}
            {outside_sql}
        )
    """.format(
        graded_ctes=_graded_ctes(where, date_sql, grade),
        bounds=bound_sql,
        outside_sql=outside_sql,
    )
    return sql, list(date_params) + list(filter_params) + list(bound_params) + list(outside_params)


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
    year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, start, end, wholesale_min, wholesale_max, grade=None, treads=None
):
    if product_bs:
        return _empty_basket_summary()
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    outside_select, outside_params = _outside_skus_sql(
        year_week, baskets, sku, size, section, aspect, rim, brand, name, wholesale_min, wholesale_max, treads
    )
    return db.fetch_dicts(
        """
        WITH sold AS (
            {sold_sql}
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
        """.format(sold_sql=_sold_sql(date_sql, grade), outside_select=outside_select),
        list(date_params) + list(outside_params),
    )[0]


def _outside_only_rows(
    year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, start, end, wholesale_min, wholesale_max, limit, grade=None, treads=None
):
    if product_bs:
        return []
    date_sql, date_params = _sale_date_sql(start, end, column="sale_date")
    outside_select, outside_params = _outside_skus_sql(
        year_week, baskets, sku, size, section, aspect, rim, brand, name, wholesale_min, wholesale_max, treads
    )
    limit_sql = ""
    params = list(date_params) + list(outside_params)
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(int(limit))
    return db.fetch_dicts(
        """
        WITH sold AS (
            {sold_sql}
        )
        SELECT
            '(no basket)' AS "Basket",
            outside_skus.sku AS "SKU",
            outside_skus.sale_grade AS "Grade",
            outside_skus.size AS "Size",
            outside_skus.section AS "Section",
            outside_skus.aspect AS "Aspect",
            outside_skus.rim AS "Rim",
            outside_skus.brand AS "Brand",
            outside_skus.name AS "Name",
            outside_skus.model AS "Model",
            outside_skus.tread AS "Tread",
            outside_skus.condition AS "Condition",
            NULL AS "Product BS",
            CAST(0 AS DOUBLE) AS "Stock",
            outside_skus.sold AS "Wholesale"
        FROM ({outside_select}) outside_skus
        ORDER BY "Size", "SKU", "Grade"
        {limit_sql}
        """.format(
            sold_sql=_sold_sql(date_sql, grade),
            outside_select=outside_select,
            limit_sql=limit_sql,
        ),
        params,
    )


def _outside_only_members_sql(
    year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, start, end, wholesale_min, wholesale_max, grade=None, treads=None
):
    if product_bs:
        return (
            """
            WITH filtered AS (
                SELECT
                    CAST(NULL AS VARCHAR) AS basket,
                    CAST(NULL AS VARCHAR) AS sku,
                    CAST(NULL AS VARCHAR) AS grade,
                    CAST(NULL AS VARCHAR) AS size,
                    CAST(NULL AS VARCHAR) AS section,
                    CAST(NULL AS VARCHAR) AS aspect,
                    CAST(NULL AS VARCHAR) AS rim,
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
        year_week, baskets, sku, size, section, aspect, rim, brand, name, wholesale_min, wholesale_max, treads
    )
    sql = """
        WITH sold AS (
            {sold_sql}
        ),
        filtered AS (
            SELECT
                '(no basket)' AS basket,
                outside_skus.sku,
                coalesce(outside_skus.sale_grade, '') AS grade,
                coalesce(nullif(outside_skus.size, ''), '(no size)') AS size,
                outside_skus.section,
                outside_skus.aspect,
                outside_skus.rim,
                coalesce(nullif(outside_skus.brand, ''), '(no brand)') AS brand,
                coalesce(nullif(outside_skus.name, ''), '(no name)') AS name,
                CAST(0 AS DOUBLE) AS stock,
                outside_skus.sold AS sold
            FROM ({outside_select}) outside_skus
        )
    """.format(
        sold_sql=_sold_sql(date_sql, grade),
        outside_select=outside_select,
    )
    return sql, list(date_params) + list(outside_params)


def _outside_union(
    include_outside,
    product_bs,
    year_week,
    baskets,
    sku,
    size,
    section,
    aspect,
    rim,
    brand,
    name,
    wholesale_min,
    wholesale_max,
    wrapper,
    treads=None,
):
    """Rows for wholesale SKUs that are absent from the selected tracking baskets.

    A product BS filter leaves these SKUs out: they have no product BS.
    """
    if not include_outside or product_bs:
        return "", []
    outside_select, params = _outside_skus_sql(
        year_week, baskets, sku, size, section, aspect, rim, brand, name, wholesale_min, wholesale_max, treads
    )
    return "UNION ALL " + wrapper.format(outside_select=outside_select), params


def _outside_skus_sql(year_week, baskets, sku, size, section, aspect, rim, brand, name, wholesale_min, wholesale_max, treads=None):
    membership, membership_params = _tracking_membership(year_week, baskets)
    text_sql, text_params = _attribute_sql(
        sku, size, section, aspect, rim, brand, name,
        "w.sku", "d.size", "d.section", "d.aspect", "d.rim", "d.brand", "d.name",
        treads=treads,
        tread_col="d.tread",
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
            w.sale_grade,
            d.size,
            d.section,
            d.aspect,
            d.rim,
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


def _tracking_filters(year_week, baskets, product_bs, sku, size, section, aspect, rim, brand, name, grade=None, treads=None):
    clauses = ["t.year_week = ?"]
    params = [year_week]
    clauses.append(_in_clause("t.basket", baskets, params))
    if product_bs:
        clauses.append(_in_clause("t.product_bs", product_bs, params))
    grade_sql = _tracking_grade_clause(grade)
    if grade_sql != "TRUE":
        clauses.append(grade_sql)
    text_sql, text_params = _attribute_sql(
        sku, size, section, aspect, rim, brand, name,
        "t.sku", "d.size", "d.section", "d.aspect", "d.rim", "d.brand", "d.name",
        treads=treads,
        tread_col="d.tread",
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


def _exact_sql(pairs):
    """Match the whole trimmed value. An empty value adds no condition."""
    clauses = []
    params = []
    for column, value in pairs:
        if value and str(value).strip():
            clauses.append("trim(coalesce({column}, '')) = ?".format(column=column))
            params.append(str(value).strip())
    return " AND ".join(clauses), params


def _attribute_sql(
    sku, size, section, aspect, rim, brand, name,
    sku_col, size_col, section_col, aspect_col, rim_col, brand_col, name_col,
    treads=None,
    tread_col=None,
):
    contains_sql, contains_params = _contains_sql(((name_col, name),))
    exact_sql, exact_params = _exact_sql(
        (
            (sku_col, sku),
            (brand_col, brand),
            (size_col, size),
            (section_col, section),
            (aspect_col, aspect),
            (rim_col, rim),
        )
    )
    clauses = []
    params = []
    if contains_sql:
        clauses.append(contains_sql)
        params.extend(contains_params)
    if exact_sql:
        clauses.append(exact_sql)
        params.extend(exact_params)
    tread_sql, tread_params = _tread_sql(treads, tread_col)
    if tread_sql:
        clauses.append(tread_sql)
        params.extend(tread_params)
    return " AND ".join(clauses), params


def _tread_sql(treads, column):
    """Exact tread match. An empty selection adds no condition."""
    if not column or not treads:
        return "", []
    values = []
    for value in treads:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            values.append(text)
    if not values:
        return "", []
    params = []
    clause = _in_clause("trim(coalesce({column}, ''))".format(column=column), values, params)
    return clause, params


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


def _wholesale_where(year_week, baskets, sku, size, section, aspect, rim, brand, name, start, end, grade=None, treads=None):
    clauses = []
    params = []
    date_sql, date_params = _sale_date_sql(start, end)
    if date_sql:
        clauses.append(date_sql)
        params.extend(date_params)
    sale_sql = _sale_grade_clause(grade, "w.majority")
    if sale_sql != "TRUE":
        clauses.append(sale_sql)
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
    text_sql, text_params = _attribute_sql(
        sku, size, section, aspect, rim, brand, name,
        "w.sku", "d.size", "d.section", "d.aspect", "d.rim", "d.brand", "d.name",
        treads=treads,
        tread_col="d.tread",
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


def _sku_membership_filters(year_week, baskets, sku, size, section, aspect, rim, brand, name, grade=None, treads=None):
    """SKUs in the selected baskets. Grade filters the sale, not this membership."""
    del grade
    clauses = ["t.year_week = ?"]
    params = [year_week]
    if baskets:
        clauses.append(_in_clause("t.basket", baskets, params))
    text_sql, text_params = _attribute_sql(
        sku, size, section, aspect, rim, brand, name,
        "t.sku", "d.size", "d.section", "d.aspect", "d.rim", "d.brand", "d.name",
        treads=treads,
        tread_col="d.tread",
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
