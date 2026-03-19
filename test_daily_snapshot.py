"""
test_daily_snapshot.py — Tests for collect_daily_snapshot.py

Tests the offline/unit logic (CSV append, idempotency, logging, schema).
Does NOT call real Roblox APIs — mocks are used for network calls.
"""

import csv
import json
import tempfile
import shutil
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

# Import the module under test
import collect_daily_snapshot as snap


@pytest.fixture
def tmp_dirs(tmp_path):
    """Set up temp directories and patch module-level paths."""
    ts_dir = tmp_path / "timeseries"
    ts_dir.mkdir()
    csv_path = ts_dir / "roblox_daily_snapshot.csv"
    log_path = ts_dir / "collection_log.json"

    with mock.patch.object(snap, "TIMESERIES_DIR", ts_dir), \
         mock.patch.object(snap, "SNAPSHOT_CSV", csv_path), \
         mock.patch.object(snap, "COLLECTION_LOG", log_path):
        yield {
            "dir": ts_dir,
            "csv": csv_path,
            "log": log_path,
        }


# ── Schema tests ──────────────────────────────────────────────

def test_csv_fields_has_snapshot_date():
    """snapshot_date must be the first column."""
    assert snap.CSV_FIELDS[0] == "snapshot_date"


def test_csv_fields_has_required_columns():
    required = [
        "universe_id", "game_name", "playing_ccu", "total_visits",
        "favorited_count", "up_votes", "down_votes", "like_ratio",
        "engagement_score", "tier", "is_breakout", "ccu_rank",
    ]
    for col in required:
        assert col in snap.CSV_FIELDS, f"Missing required column: {col}"


# ── append_rows tests ────────────────────────────────────────

def test_append_rows_creates_file_with_header(tmp_dirs):
    """First append should create the CSV with a header row."""
    rows = [{"snapshot_date": "2026-03-19", "universe_id": 123, "game_name": "Test"}]
    snap.append_rows(rows)

    lines = tmp_dirs["csv"].read_text().strip().splitlines()
    assert len(lines) == 2  # header + 1 data row
    assert lines[0].startswith("snapshot_date,")


def test_append_rows_appends_without_duplicate_header(tmp_dirs):
    """Second append should NOT write another header."""
    row1 = [{"snapshot_date": "2026-03-19", "universe_id": 1, "game_name": "A"}]
    row2 = [{"snapshot_date": "2026-03-20", "universe_id": 2, "game_name": "B"}]

    snap.append_rows(row1)
    snap.append_rows(row2)

    lines = tmp_dirs["csv"].read_text().strip().splitlines()
    assert len(lines) == 3  # 1 header + 2 data rows
    # Only the first line should be the header
    headers = [l for l in lines if l.startswith("snapshot_date,")]
    assert len(headers) == 1


# ── today_already_collected tests ────────────────────────────

def test_today_not_collected_when_no_file(tmp_dirs):
    assert not snap.today_already_collected()


def test_today_not_collected_when_different_date(tmp_dirs):
    rows = [{"snapshot_date": "2020-01-01", "universe_id": 1, "game_name": "Old"}]
    snap.append_rows(rows)
    assert not snap.today_already_collected()


def test_today_collected_when_date_matches(tmp_dirs):
    today = date.today().isoformat()
    rows = [{"snapshot_date": today, "universe_id": 1, "game_name": "Today"}]
    snap.append_rows(rows)
    assert snap.today_already_collected()


# ── update_log tests ─────────────────────────────────────────

def test_update_log_creates_file(tmp_dirs):
    entry = {"date": "2026-03-19", "n_games": 56}
    snap.update_log(entry)

    log = json.loads(tmp_dirs["log"].read_text())
    assert len(log) == 1
    assert log[0]["n_games"] == 56


def test_update_log_appends(tmp_dirs):
    snap.update_log({"date": "2026-03-19", "n_games": 56})
    snap.update_log({"date": "2026-03-20", "n_games": 55})

    log = json.loads(tmp_dirs["log"].read_text())
    assert len(log) == 2
    assert log[1]["date"] == "2026-03-20"


# ── idempotency / main() tests ──────────────────────────────

def test_main_skips_if_already_collected(tmp_dirs, capsys):
    """main() should print SKIP and not call collect() if today exists."""
    today = date.today().isoformat()
    rows = [{"snapshot_date": today, "universe_id": 1, "game_name": "X"}]
    snap.append_rows(rows)

    with mock.patch.object(snap, "collect") as mock_collect:
        snap.main()
        mock_collect.assert_not_called()

    captured = capsys.readouterr()
    assert "[SKIP]" in captured.out


def test_main_calls_collect_when_no_data(tmp_dirs):
    """main() should call collect() when there's no data for today."""
    with mock.patch.object(snap, "collect") as mock_collect:
        snap.main()
        mock_collect.assert_called_once()


# ── collect() integration test (mocked API) ──────────────────

FAKE_GAME_DETAILS = [
    {
        "id": 999,
        "name": "FakeGame",
        "genre": "Adventure",
        "genre_l1": "",
        "genre_l2": "",
        "playing": 5000,
        "visits": 1000000,
        "favoritedCount": 50000,
        "created": "2023-01-15T00:00:00Z",
        "maxPlayers": 50,
        "creator": {"name": "TestDev", "type": "User", "hasVerifiedBadge": False},
    }
]

FAKE_VOTES = {999: {"upVotes": 9000, "downVotes": 1000}}


def test_collect_writes_csv_and_log(tmp_dirs):
    """Full collect() with mocked APIs should produce CSV + log."""
    fake_known = {
        "FakeGame": {
            "place_id": 111,
            "tier": "mid",
            "is_breakout": False,
            "breakout_year": None,
        }
    }

    with mock.patch.object(snap, "KNOWN_GAMES", fake_known), \
         mock.patch.object(snap, "resolve_universe_ids", return_value={111: 999}), \
         mock.patch.object(snap, "fetch_game_details", return_value=FAKE_GAME_DETAILS), \
         mock.patch.object(snap, "fetch_votes", return_value=FAKE_VOTES):

        result = snap.collect()

    # Check CSV was written
    assert tmp_dirs["csv"].exists()
    with open(tmp_dirs["csv"], "r") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        assert reader[0]["game_name"] == "FakeGame"
        assert reader[0]["snapshot_date"] == date.today().isoformat()
        assert int(reader[0]["playing_ccu"]) == 5000
        assert reader[0]["ccu_rank"] == "1"

    # Check log was written
    assert tmp_dirs["log"].exists()
    log = json.loads(tmp_dirs["log"].read_text())
    assert len(log) == 1
    assert log[0]["n_games"] == 1
    assert log[0]["date"] == date.today().isoformat()

    # Check return value
    assert result["n_games"] == 1


def test_collect_handles_zero_resolved(tmp_dirs, capsys):
    """collect() should log error and not crash when no IDs resolve."""
    fake_known = {
        "BadGame": {
            "place_id": 111,
            "tier": "mid",
            "is_breakout": False,
            "breakout_year": None,
        }
    }

    with mock.patch.object(snap, "KNOWN_GAMES", fake_known), \
         mock.patch.object(snap, "resolve_universe_ids", return_value={}):

        result = snap.collect()

    assert result["n_games"] == 0
    assert result["n_errors"] > 0
    assert "No universe IDs resolved" in str(result["errors"])

    # Log should still be written
    log = json.loads(tmp_dirs["log"].read_text())
    assert len(log) == 1
