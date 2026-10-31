"""Probe mode of the data workflow: every linked file is kept, none overwrites another."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from probe_source import dest_name  # noqa: E402


def test_same_basename_links_get_distinct_names():
    taken = {"page.html", "index.json"}
    urls = ["https://x.fr/2024/results.csv", "https://x.fr/2025/results.csv",
            "https://x.fr/dl/results.csv?v=2", "https://x.fr/page.html", "https://x.fr/a/", "https://x.fr/b/"]
    names = [dest_name(u, taken) for u in urls]
    assert len(set(names)) == len(names), names
    assert names[0] == "results.csv" and names[1].startswith("results-") and names[1].endswith(".csv")
    assert names[3] != "page.html"            # never overwrites the saved page itself


def test_names_are_safe_and_deterministic():
    a = dest_name("https://x.fr/f/Tableaux%20r%C3%A9ussite%20(2024).xlsx", set())
    assert "/" not in a and " " not in a and a.endswith(".xlsx")
    assert dest_name("https://x.fr/2025/r.csv", {"r.csv"}) == dest_name("https://x.fr/2025/r.csv", {"r.csv"})
