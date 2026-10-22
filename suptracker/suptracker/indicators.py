"""Within-filière peer benchmarks.

Peers = same session x fil_lib_voe_acc (detailed national track). Every metric is
an official SIES indicator or a raw count share; no access rate is ever derived
from prop_tot over voe_tot.

Admitted-profile metrics (mentions, bourse, gender, origin) are only ranked for
formations with acc_tot >= LOW_N_THRESHOLD, and only such formations enter the
reference distribution: a 3-student cohort at 100 % TB would otherwise anchor
the national top decile. taux_acces_ens rests on the phase-principale applicant
pool, not on acc_tot, so it is ranked for every formation that publishes it.
"""
from __future__ import annotations

import duckdb

from . import config

# metric -> (SQL expression, needs acc_tot >= threshold, label, higher_is_more_selective)
PEER_METRICS: dict[str, tuple[str, bool, str, bool]] = {
    "taux_acces_ens": ("taux_acces_ens", False, "Taux d'accès (PP)", False),
    "part_terminale_generale_en_position_admis_pp": (
        "part_terminale_generale_en_position_admis_pp", False,
        "Part des terminales générales en position d'admis (PP)", False),
    "pct_tb_tbf": ("pct_tb + coalesce(pct_tbf, 0)", True, "% mention TB (+ félicitations)", True),
    "pct_bours": ("pct_bours", True, "% boursiers", False),
    "pct_f": ("pct_f", True, "% femmes", False),
    "pct_bg": ("pct_bg", True, "% bac général", False),
    "pct_aca_orig": ("pct_aca_orig", True, "% même académie", False),
    "pct_etab_orig": ("pct_etab_orig", True, "% même établissement", False),
}


def build_peers(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    long_parts, dist_parts = [], []
    for key, (expr, needs_n, _, _) in PEER_METRICS.items():
        elig = f"({expr}) IS NOT NULL" + (f" AND acc_tot >= {config.LOW_N_THRESHOLD}" if needs_n else "")
        long_parts.append(f"""
          SELECT session, cod_aff_form, fil_lib_voe_acc, '{key}' AS metric, ({expr})::DOUBLE AS value,
                 {elig} AS in_reference
          FROM core.formation_year""")
        dist_parts.append(f"""
          SELECT session, fil_lib_voe_acc, '{key}' AS metric, count(*) AS n_peers,
                 quantile_cont(({expr})::DOUBLE, [0.1, 0.25, 0.5, 0.75, 0.9]) AS q
          FROM core.formation_year WHERE {elig} GROUP BY ALL""")
    con.execute("CREATE OR REPLACE TABLE mart._peer_long AS " + " UNION ALL ".join(long_parts))
    con.execute("CREATE OR REPLACE TABLE mart.peer_distribution AS SELECT session, fil_lib_voe_acc, metric, "
                "n_peers, q[1] AS p10, q[2] AS p25, q[3] AS p50, q[4] AS p75, q[5] AS p90, "
                f"n_peers < {config.MIN_PEERS} AS unstable FROM (" + " UNION ALL ".join(dist_parts) + ")")
    # Rank a formation inside the reference set with a mid-rank percentile (ties share the
    # average position). Formations outside it (low n) get NULL, so the UI shows a warning
    # instead of a misleading percentile.
    con.execute("""
    CREATE OR REPLACE TABLE mart.peer_rank AS
    WITH ranked AS (
      SELECT session, cod_aff_form, metric,
        rank() OVER w - 1 AS n_below,
        count(*) OVER (PARTITION BY session, metric, fil_lib_voe_acc, value) AS n_tied
      FROM mart._peer_long WHERE in_reference
      WINDOW w AS (PARTITION BY session, metric, fil_lib_voe_acc ORDER BY value)
    )
    SELECT l.*, d.n_peers, d.p10, d.p25, d.p50, d.p75, d.p90, d.unstable,
      CASE WHEN l.in_reference AND d.n_peers > 1
           THEN round(100.0 * (r.n_below + 0.5 * (r.n_tied - 1)) / (d.n_peers - 1), 1) END AS peer_percentile
    FROM mart._peer_long l
    LEFT JOIN ranked r USING (session, cod_aff_form, metric)
    LEFT JOIN mart.peer_distribution d
      ON d.session = l.session AND d.metric = l.metric
     AND d.fil_lib_voe_acc IS NOT DISTINCT FROM l.fil_lib_voe_acc
    """)
    con.execute("DROP TABLE mart._peer_long")
