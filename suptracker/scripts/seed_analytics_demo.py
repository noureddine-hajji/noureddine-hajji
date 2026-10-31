"""Fill a local analytics store with synthetic traffic, to preview the dashboard.

    SUPTRACKER_ANALYTICS_DIR=/tmp/st-demo python scripts/seed_analytics_demo.py --days 90
    SUPTRACKER_ANALYTICS_DIR=/tmp/st-demo SUPTRACKER_STATS_TOKEN=demo-token-0123456789 uvicorn suptracker.api:app
    → http://localhost:8000/#/stats  (token: demo-token-0123456789)

Never point it at the production store: every number it writes is invented.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suptracker import analytics as A  # noqa: E402

QUERIES = ["bts ndrc", "prepa hec", "medecine", "psycho lyon", "staps", "iut informatique", "droit", "infirmier",
           "sciences po", "kine", "but gea", "licence anglais", "dcg", "ecole ingenieur", "mpsi"]
ZERO = ["bachelor commerce", "bts esthetique paris", "ecole de pilote", "dut gea", "prepa veto lyon"]
COD = ["10417", "6372", "14022", "23412", "31144", "4590", "8812"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    if os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL"):
        sys.exit("refusing to seed demo data into a Redis store")
    rnd = random.Random(a.seed)
    end = A.today()
    real_today = A.today
    try:
        for back in range(a.days - 1, -1, -1):
            day = end - timedelta(days=back)
            A.today = lambda d=day: d
            phase = A.phase_of(day)
            base = {"Formulation des vœux": 140, "Découverte des formations": 90, "Phase d'admission principale": 110}.get(phase, 45)
            n = int(base * (0.75 if day.weekday() >= 5 else 1.0) * rnd.uniform(0.85, 1.15) * (1 + (a.days - back) / a.days / 2))
            for v in range(n):
                h = {"user-agent": f"Mozilla/5.0 demo{v % 7}", "x-real-ip": f"10.{back % 250}.{v // 250}.{v % 250}"}
                dev = rnd.choices(A.DEVICES, [70, 8, 22])[0]
                A.record("view", {"route": "home", "device": dev,
                                  "source": rnd.choices(A.SOURCES, [30, 35, 12, 6, 2, 8, 6, 1])[0]}, h)
                if rnd.random() < 0.72:
                    zero = rnd.random() < (0.11 if back > 30 else 0.06)
                    q = rnd.choice(ZERO) if zero else rnd.choice(QUERIES)
                    A.record("search", {"q": q, "total": 0 if zero else 12, "partial": False}, h)
                    A.record("view", {"route": "search", "device": dev, "source": None}, h)
                    if not zero and rnd.random() < 0.6:
                        cod = rnd.choice(COD)
                        A.record("view", {"route": "fiche", "device": dev, "source": None, "cod": cod}, h)
                        if rnd.random() < 0.35:
                            A.record("out", {"cod": cod}, h)
                        if rnd.random() < 0.08:
                            up = rnd.random() < 0.78
                            A.record("feedback", {"page": "fiche", "vote": "up" if up else "down",
                                                  "reason": "utile" if up else rnd.choice(A.FEEDBACK_REASONS[1:])}, h)
                if rnd.random() < 0.18:
                    A.record("view", {"route": "parcours", "device": dev, "source": None}, h)
                    A.record("journey", {"stage": "stage1"}, h)
                    if rnd.random() < 0.5:
                        A.record("journey", {"stage": "stage2"}, h)
                if rnd.random() < 0.004:
                    A.record("jserr", {"route": "fiche"}, h)
            for _ in range(rnd.randint(5, 30)):
                A.record("view", {"route": "home", "device": "desktop", "source": None}, {"user-agent": "Googlebot/2.1"})
    finally:
        A.today = real_today
    print(f"seeded {a.days} days into {A.store().kind} store")
    return 0


if __name__ == "__main__":
    sys.exit(main())
