"""WO-019's import checks on FABRICATED exports in a temporary directory; nothing reads banshee."""

from __future__ import annotations

import copy
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from vishwaroop.data import banshee_import as bi

ROOT = Path(__file__).resolve().parents[1]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_export(
    root: Path, export_id: str = "x-episodes", kind: str = "episodes", **manifest_changes: Any
) -> tuple[Path, str]:
    """A small export with one episode: its directory and its manifest sha256."""
    directory = root / export_id
    files = {}
    shared = dict.fromkeys(bi.SHARED_ENTRY_FIELDS)
    shared.update(
        stack="jazzy", split="train", partition="train", success=True, run_id="r1", family_id="f"
    )
    if kind == "episodes":
        episode = {
            "episode_id": "e1",
            "schema_version": "1.0.0",
            "split": {"partition": "train", "scene_group_id": "f"},
        }
        files["episodes/r1/episode.json"] = json.dumps(episode).encode()
        files["episodes/r1/transitions.jsonl"] = b"{}\n"
        entries = [{"episode_id": "e1", "path": "episodes/r1", **shared}]
    else:
        files["ulogs/r1/a.ulg"] = b"ulog"
        ulogs = [{"path": "ulogs/r1/a.ulg", "sha256": _sha(b"ulog")}]
        entries = [{"episode_id": "e1", "ulogs": ulogs, **shared}]
    for relative, data in files.items():
        (directory / relative).parent.mkdir(parents=True, exist_ok=True)
        (directory / relative).write_bytes(data)
    manifest = {
        "export_id": export_id,
        "producer": "banshee",
        "kind": kind,
        "contract": {"name": "ironclad contracts v1", "schema_version": "1.0.0"},
        "entries": entries,
        "counts": {
            "entries": 1,
            "by_stack_and_split": {"jazzy/train": 1},
            "successful": 1,
            "failed": 0,
        },
        "files": [
            {"path": relative, "sha256": _sha(data), "bytes": len(data)}
            for relative, data in files.items()
        ],
    }
    manifest.update(manifest_changes)
    raw = json.dumps(manifest).encode()
    (directory / "MANIFEST.json").write_bytes(raw)
    (directory / "COMPLETE").write_text(_sha(raw) + "\n", encoding="ascii")
    return directory, _sha(raw)


def test_the_frozen_rules_are_pinned() -> None:
    assert bi.check_frozen(ROOT) == {str(k): v for k, v in bi.FROZEN.items()}
    amendment = json.loads((ROOT / "evals/M4-amendment-1.json").read_text(encoding="utf-8"))
    assert "contract.schema_version" in amendment["ET-M4-1"]["schema_check"]
    assert amendment["amends_sha256"] == bi.FROZEN[Path("evals/M4-exit-tests.json")]


def test_a_clean_export_verifies(tmp_path: Path) -> None:
    directory, digest = make_export(tmp_path)
    export = bi.verify_export(directory, "x-episodes", digest)
    assert export.kind == "episodes"


@pytest.mark.parametrize(
    ("contract", "extra", "match"),
    [
        (None, {}, "no contract object"),
        ({"name": "v1"}, {}, "missing"),
        ({"schema_version": 1.0}, {}, "not a string"),
        ({"schema_version": "1.0"}, {}, "not '1.0.0'"),
        ({"schema_version": "1.0.0 "}, {}, "not '1.0.0'"),
        ({"schema_version": "1.0.0"}, {"schema_version": "1.1.0"}, "conflicting"),
        ({"schema_version": "1.0.0"}, {"meta": {"schema_version": "2"}}, "conflicting"),
    ],
)
def test_the_amended_schema_check_stops(
    tmp_path: Path, contract: Any, extra: dict[str, Any], match: str
) -> None:
    changes: dict[str, Any] = {"contract": contract, **extra}
    directory, digest = make_export(tmp_path, **changes)
    with pytest.raises(bi.ImportStopError, match=match):
        bi.verify_export(directory, "x-episodes", digest)


def test_a_matching_top_level_schema_version_is_not_a_conflict(tmp_path: Path) -> None:
    directory, digest = make_export(tmp_path, schema_version="1.0.0")
    bi.verify_export(directory, "x-episodes", digest)


def test_complete_must_hold_the_expected_manifest_hash(tmp_path: Path) -> None:
    directory, digest = make_export(tmp_path)
    with pytest.raises(bi.ImportStopError, match="expected"):
        bi.verify_export(directory, "x-episodes", "0" * 64)
    (directory / "COMPLETE").write_text("f" * 64, encoding="ascii")
    with pytest.raises(bi.ImportStopError, match="COMPLETE"):
        bi.verify_export(directory, "x-episodes", digest)
    (directory / "COMPLETE").unlink()
    with pytest.raises(bi.ImportStopError, match="no COMPLETE"):
        bi.verify_export(directory, "x-episodes", digest)


def test_a_changed_missing_or_unlisted_file_stops(tmp_path: Path) -> None:
    directory, digest = make_export(tmp_path)
    target = directory / "episodes/r1/transitions.jsonl"
    target.write_bytes(b"[]\n")
    with pytest.raises(bi.ImportStopError, match="sha256"):
        bi.verify_export(directory, "x-episodes", digest)
    target.write_bytes(b"{}\n")
    (directory / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(bi.ImportStopError, match="not in the manifest"):
        bi.verify_export(directory, "x-episodes", digest)
    (directory / "extra.txt").unlink()
    target.unlink()
    with pytest.raises(bi.ImportStopError, match="missing"):
        bi.verify_export(directory, "x-episodes", digest)


def test_an_unsafe_path_stops(tmp_path: Path) -> None:
    directory, _ = make_export(tmp_path)
    manifest = json.loads((directory / "MANIFEST.json").read_bytes())
    manifest["files"][0]["path"] = "../outside"
    raw = json.dumps(manifest).encode()
    (directory / "MANIFEST.json").write_bytes(raw)
    (directory / "COMPLETE").write_text(_sha(raw), encoding="ascii")
    with pytest.raises(bi.ImportStopError, match="unsafe"):
        bi.verify_export(directory, "x-episodes", _sha(raw))


def test_an_episode_on_another_schema_version_stops(tmp_path: Path) -> None:
    directory, _ = make_export(tmp_path)
    data = json.dumps({"episode_id": "e1", "schema_version": "1.1.0", "split": {}}).encode()
    (directory / "episodes/r1/episode.json").write_bytes(data)
    manifest = json.loads((directory / "MANIFEST.json").read_bytes())
    manifest["files"][0].update(sha256=_sha(data), bytes=len(data))
    raw = json.dumps(manifest).encode()
    (directory / "MANIFEST.json").write_bytes(raw)
    (directory / "COMPLETE").write_text(_sha(raw), encoding="ascii")
    with pytest.raises(bi.ImportStopError, match=r"1\.1\.0"):
        bi.verify_export(directory, "x-episodes", _sha(raw))


def test_the_copy_is_byte_for_byte_read_only_and_write_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, digest = make_export(tmp_path / "source")
    monkeypatch.setitem(bi.EXPORTS, "x-episodes", digest)
    export = bi.verify_export(directory, "x-episodes", digest)
    repo = tmp_path / "repo"
    target = bi.copy_export(export, repo)
    for name in ("MANIFEST.json", "COMPLETE", "episodes/r1/episode.json"):
        assert (target / name).read_bytes() == (directory / name).read_bytes()
        assert not (target / name).stat().st_mode & stat.S_IWUSR
    with pytest.raises(bi.ImportStopError, match="write-once"):
        bi.copy_export(export, repo)
    record = bi.import_record(
        bi.Export(
            "x-episodes",
            directory,
            export.manifest_bytes,
            {
                **export.manifest,
                "source_commit": "c",
                "created_at": "t",
                "counts": {},
                "rights": "r",
            },
        ),
        {"evals/M4-amendment-1.json": "a" * 64},
        "c0ffee",
    )
    assert record["stacks"]["by_stack"] == {"jazzy": 1} and record["tool_commit"] == "c0ffee"
    assert record["source"] == "banshee:data/exports/x-episodes"
    assert not record["target"].startswith("/") and "Users" not in json.dumps(record)


def _episode(eid: str, family: str, split: str, triple: tuple[str, str, str], h: str) -> Any:
    entry = {
        "episode_id": eid,
        "family_id": family,
        "route_id": triple[0],
        "wind_id": triple[1],
        "fault_family": triple[2],
        "split": split,
        "partition": "train" if split == "train" else "dev",
        "success": True,
        "stack": "jazzy",
    }
    episode = {
        "episode_id": eid,
        "split": {
            "scene_group_id": family,
            "partition": "train" if split == "train" else "dev",
            "session_group_id": eid,
        },
        "data": {"transitions_artifact": {"sha256": h}},
        "action_spec": {"labels": list(bi.ACTION_LABELS), "units": list(bi.ACTION_UNITS)},
        "streams": [{"name": "state", "frame_id": "enu_local", "shape": [7]}],
    }
    return {"export_id": "x", "entry": entry, "episode": episode}


def _good() -> list[Any]:
    return [
        _episode("a", "f1", "train", ("r", "calm", "nominal"), "h1"),
        _episode("b", "f1", "train", ("r", "calm", "nominal"), "h2"),
        _episode("c", "f2", "heldout", ("r", "wind", "nominal"), "h3"),
    ]


def test_the_m4_data_checks_pass_on_a_clean_union() -> None:
    result = bi.data_checks(_good())
    assert result["passed"], result["problems"]
    assert result["by_partition"]["train"]["episodes"] == 2
    assert result["families"]["f2"]["partition"] == "heldout"


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (lambda e: e[1]["entry"].update(split="heldout"), "partitions"),
        (
            lambda e: e[2]["episode"]["data"]["transitions_artifact"].update(sha256="h1"),
            "transitions",
        ),
        (lambda e: e[1]["entry"].update(wind_id="wind"), "triples"),
        (lambda e: e[1]["entry"].update(episode_id="a"), "occurs 2 times"),
        (lambda e: e[0]["episode"]["action_spec"].update(labels=["vx"]), "action_spec"),
        (lambda e: e[0]["episode"]["streams"][0].update(shape=[6]), "state"),
        (lambda e: [i["entry"].update(split="train") for i in e], "designate"),
    ],
)
def test_the_m4_data_checks_catch_each_problem(edit: Any, match: str) -> None:
    episodes = copy.deepcopy(_good())
    edit(episodes)
    result = bi.data_checks(episodes)
    assert not result["passed"]
    assert any(match in problem for problem in result["problems"]), result["problems"]


def test_consistency_checks_outside_the_freeze_are_reported_not_gated() -> None:
    episodes = copy.deepcopy(_good())
    episodes[1]["episode"]["split"]["session_group_id"] = "c"
    result = bi.data_checks(episodes)
    assert result["passed"]
    assert not result["other_checks_passed"]
    assert any("session" in problem for problem in result["other_problems"])


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (lambda e: e[2]["entry"].update(family_id="f3"), "scene_group_id"),
        (lambda e: e[2]["episode"]["split"].update(partition="train"), "published mapping"),
    ],
)
def test_amendment_2_checks_are_gated(edit: Any, match: str) -> None:
    episodes = copy.deepcopy(_good())
    edit(episodes)
    result = bi.data_checks(episodes)
    assert not result["passed"]
    assert any(match in problem for problem in result["problems"]), result["problems"]


@pytest.mark.parametrize(
    ("entry", "split", "match"),
    [
        ({"split": "train", "partition": "train", "family_id": "f"}, {"partition": "dev"}, "not"),
        (
            {"split": "heldout", "partition": "train", "family_id": "f"},
            {"partition": "train"},
            "dev",
        ),
        (
            {"split": "train", "partition": "dev", "family_id": "f"},
            {"partition": "train"},
            "differs",
        ),
        (
            {"split": "train", "partition": "train", "family_id": "g"},
            {"partition": "train"},
            "scene",
        ),
        (
            {"split": "sealed", "partition": "dev", "family_id": "f"},
            {"partition": "dev"},
            "neither",
        ),
    ],
)
def test_the_published_split_is_checked_before_copying(
    entry: dict[str, Any], split: dict[str, Any], match: str
) -> None:
    episode = {"split": {"scene_group_id": "f", **split}}
    with pytest.raises(bi.ImportStopError, match=match):
        bi.check_published_split({"episode_id": "e", **entry}, episode, "x")
    good = {"episode_id": "e", "split": "heldout", "partition": "dev", "family_id": "f"}
    bi.check_published_split(good, {"split": {"scene_group_id": "f", "partition": "dev"}}, "x")


def test_a_duplicate_key_stops(tmp_path: Path) -> None:
    directory, _ = make_export(tmp_path)
    raw = (directory / "MANIFEST.json").read_bytes()
    raw = raw.replace(b'"producer": "banshee"', b'"producer": "banshee", "producer": "banshee"')
    (directory / "MANIFEST.json").write_bytes(raw)
    (directory / "COMPLETE").write_text(_sha(raw), encoding="ascii")
    with pytest.raises(bi.ImportStopError, match="duplicate"):
        bi.verify_export(directory, "x-episodes", _sha(raw))


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"counts": {"entries": 2}}, "counts.entries"),
        ({"counts": {"entries": 1, "by_stack_and_split": {"humble/train": 1}}}, "stack"),
    ],
)
def test_counts_must_match_the_entries(tmp_path: Path, change: dict[str, Any], match: str) -> None:
    directory, digest = make_export(tmp_path, **change)
    with pytest.raises(bi.ImportStopError, match=match):
        bi.verify_export(directory, "x-episodes", digest)


def test_an_unknown_stack_stops(tmp_path: Path) -> None:
    directory, _ = make_export(tmp_path)
    manifest = json.loads((directory / "MANIFEST.json").read_bytes())
    manifest["entries"][0]["stack"] = None
    raw = json.dumps(manifest).encode()
    (directory / "MANIFEST.json").write_bytes(raw)
    (directory / "COMPLETE").write_text(_sha(raw), encoding="ascii")
    with pytest.raises(bi.ImportStopError, match="unknown stacks"):
        bi.verify_export(directory, "x-episodes", _sha(raw))


def test_episode_and_ulog_exports_must_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, a = make_export(tmp_path, "x-episodes")
    ulogs, b = make_export(tmp_path, "x-ulogs", kind="ulogs")
    monkeypatch.setattr(bi, "EXPORTS", {"x-episodes": a, "x-ulogs": b})
    monkeypatch.setattr(bi, "ULOG_FOR", {"x-episodes": "x-ulogs"})
    assert len(bi.verify_all(tmp_path)) == 2
    manifest = json.loads((ulogs / "MANIFEST.json").read_bytes())
    manifest["entries"][0]["success"] = False
    manifest["counts"].update(successful=0, failed=1)
    raw = json.dumps(manifest).encode()
    (ulogs / "MANIFEST.json").write_bytes(raw)
    (ulogs / "COMPLETE").write_text(_sha(raw), encoding="ascii")
    monkeypatch.setattr(bi, "EXPORTS", {"x-episodes": a, "x-ulogs": _sha(raw)})
    with pytest.raises(bi.ImportStopError, match="differs in"):
        bi.verify_all(tmp_path)


def test_the_partition_table_records_split_partition_by_m4_split(tmp_path: Path) -> None:
    directory, digest = make_export(tmp_path)
    export = bi.verify_export(directory, "x-episodes", digest)
    assert bi.partition_table(export) == {"train -> train": 1}


def test_a_stopped_import_resumes_without_deleting_or_duplicating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FABRICATED: the second run re-verifies the first copy and writes no second ledger line."""
    import argparse

    source = tmp_path / "source"
    _, a = make_export(source, "x-episodes")
    _, b = make_export(source, "x-ulogs", kind="ulogs")
    repo = tmp_path / "repo"
    (repo / "ledgers").mkdir(parents=True)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(bi, "EXPORTS", {"x-episodes": a, "x-ulogs": b})
    monkeypatch.setattr(bi, "ULOG_FOR", {"x-episodes": "x-ulogs"})
    monkeypatch.setattr(bi, "check_frozen", lambda root=Path("."): {"rules": "f" * 64})
    monkeypatch.setattr(bi, "git_state", lambda repo=Path("."): {"commit": "c", "dirty": False})
    monkeypatch.setattr(
        bi,
        "import_record",
        lambda export, frozen, commit: {
            "export_id": export.export_id,
            "manifest_sha256": bi.EXPORTS[export.export_id],
        },
    )
    args = argparse.Namespace(source=source)
    assert bi._cmd_import(args) == 0
    assert bi._cmd_import(args) == 0
    lines = (repo / "ledgers/imports.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert len((repo / "ledgers/licenses.jsonl").read_text().splitlines()) == 1
    monkeypatch.setattr(bi, "git_state", lambda repo=Path("."): {"commit": "c", "dirty": True})
    with pytest.raises(bi.ImportStopError, match="commit first"):
        bi._cmd_import(args)
