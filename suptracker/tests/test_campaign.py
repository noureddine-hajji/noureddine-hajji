"""Campaign 2027 readiness: the SIES rollover, the live harvest's order, and the rebuild after a harvest."""
import re
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import config, ingest  # noqa: E402

DATA_WF = ROOT.parent / ".github" / "workflows" / "suptracker-data.yml"


def fake_portal(monkeypatch, served: dict):
    """ods id -> session held (None = the id does not exist yet). Every other dataset is skipped (--only)."""
    calls = []

    def download(url, dest, retries=4):
        ods = re.search(r"/datasets/([^/]+)/exports", url).group(1)
        calls.append(ods)
        if served.get(ods) is None:
            raise RuntimeError("404")
        pq.write_table(pa.table({"session": [served[ods]] * 3, "cod_aff_form": ["1", "2", "3"]}), dest)

    monkeypatch.setattr(ingest, "_download", download)
    return calls


VOEUX = {f"parcoursup_{y}" for y in (2025, config.NEXT_YEAR)}


def test_today_rolling_id_holds_2025(tmp_path, monkeypatch, capsys):
    calls = fake_portal(monkeypatch, {"fr-esr-parcoursup": 2025})
    man = ingest.ingest(tmp_path, only=VOEUX, force=True)
    assert man["parcoursup_2025"]["ods_id"] == "fr-esr-parcoursup"
    assert "parcoursup_2026" not in man and not (tmp_path / "parcoursup_2026.parquet").exists()   # optional: not fatal
    assert ingest.sessions(tmp_path / "parcoursup_2025.parquet") == {2025}
    assert "Nouvelle campagne" not in capsys.readouterr().out
    assert calls.count("fr-esr-parcoursup") == 2                                                    # tried for both years


def test_rollover_never_loads_2026_as_2025(tmp_path, monkeypatch, capsys):
    """SIES publishes 2026: the rolling id moves to 2026, 2025 gets its frozen id."""
    fake_portal(monkeypatch, {"fr-esr-parcoursup": 2026, "fr-esr-parcoursup_2025": 2025})
    man = ingest.ingest(tmp_path, only=VOEUX, force=True)
    assert man["parcoursup_2025"]["ods_id"] == "fr-esr-parcoursup_2025"
    assert man["parcoursup_2026"]["ods_id"] == "fr-esr-parcoursup"
    assert ingest.sessions(tmp_path / "parcoursup_2025.parquet") == {2025}
    assert ingest.sessions(tmp_path / "parcoursup_2026.parquet") == {2026}
    assert "::warning title=Nouvelle campagne SIES::SIES a publié la session 2026" in capsys.readouterr().out


def test_rollover_before_the_frozen_id_exists_fails_loudly(tmp_path, monkeypatch):
    """The rolling id already holds 2026 but the 2025 copy is not out yet: never 2026 under 2025, the refresh stops."""
    fake_portal(monkeypatch, {"fr-esr-parcoursup": 2026})
    with pytest.raises(RuntimeError, match="holds session"):
        ingest.ingest(tmp_path, only=VOEUX, force=True)
    assert not (tmp_path / "parcoursup_2025.parquet").exists()


def test_session_check(tmp_path):
    f = tmp_path / "x.parquet"
    pq.write_table(pa.table({"annee": ["2026", "2026"]}), f)                          # the SIES alias, as text
    voeux25 = next(d for d in config.DATASETS if d.key == "parcoursup_2025")
    voeux26 = next(d for d in config.DATASETS if d.key == f"parcoursup_{config.NEXT_YEAR}")
    assert ingest.check_session(voeux25, f) == "holds session(s) [2026], not 2025"
    assert ingest.check_session(voeux26, f) is None
    other = next(d for d in config.DATASETS if d.kind != "voeux")
    assert ingest.check_session(other, f) is None


def test_live_harvest_reads_first_the_fiches_without_the_newest_report(tmp_path):
    """Campaign 2027: SIES stops at 2025, the fiches link 2026 reports. A formation with a 2025 report but no 2026 one
    comes before one that already has its 2026 report."""
    import rapports_live as L
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER)")
    con.execute("INSERT INTO core.formation_year VALUES ('1', 2025), ('2', 2025), ('3', 2025)")
    con.execute("CREATE TABLE core.cartographie (cod_aff_form VARCHAR, carto_session INTEGER)")
    con.execute("INSERT INTO core.cartographie VALUES ('4', 2027)")
    con.execute("CREATE TABLE core.rapport (cod_aff_form VARCHAR, session INTEGER)")
    con.execute("INSERT INTO core.rapport VALUES ('1', 2025), ('2', 2025), ('2', 2026), ('3', 2026)")
    con.close()
    order = L.codes(str(db))
    assert order == ["1", "4", "2", "3"], order


def test_a_harvest_reaches_the_site():
    wf = DATA_WF.read_text()
    assert re.search(r"workflow_run:\n\s+workflows: \[suptracker-rapports\]\n\s+types: \[completed\]\n\s+branches: \[main\]", wf)
    assert "github.event.workflow_run.conclusion == 'success'" in wf
    fp = re.search(r"fp=\$\( \{ jq.*?\| sha256sum", wf, re.S).group(0)
    assert "data/rapports/harvest" in fp                                  # new reports alone publish a new warehouse
    assert "data/harvest_fingerprint.txt" in wf.split("git add", 1)[1]
    assert "needs.harvest-changed.outputs.changed == 'true'" in wf
    assert '- cron: "17 3 * * 1"' in wf                                   # weekly: a new cartographie or SIES campaign
