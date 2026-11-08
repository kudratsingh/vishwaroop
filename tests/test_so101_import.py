"""WO-023: the SO-101 LeRobot v3.0 importer, on FABRICATED fixtures (tests/lerobot_fixture.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from ironclad.contracts.v1 import validate

import lerobot_fixture as fx
from vishwaroop.data import so101_import as si
from vishwaroop.importer import ExportImportError


def _sealed(tmp_path: Path, *, decl: dict[str, Any] | None = None, labels=None, **dataset) -> Path:
    data = fx.write_dataset(tmp_path / "recording", **dataset)
    decl_path = tmp_path / "declaration.json"
    decl_path.write_text(json.dumps(decl or fx.declaration()))
    extras = fx.extras(tmp_path / "extras", labels=labels)
    return si.seal(data, decl_path, extras, "fixture-export-1", tmp_path / "exports")


def _split(tmp_path: Path, doc: dict[str, Any] | None = None) -> Path:
    path = tmp_path / "split.json"
    path.write_text(json.dumps(doc or fx.split()))
    return path


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "ledgers").mkdir(parents=True)
    return repo


def _reseal(export: Path) -> None:
    """Rewrite MANIFEST.json's hashes after a test edits a file, as a producer would."""
    from ironclad.core.artifacts import sha256_file

    manifest = json.loads((export / "MANIFEST.json").read_text())
    manifest["files"] = {
        p.relative_to(export).as_posix(): sha256_file(p)
        for p in sorted(export.rglob("*"))
        if p.is_file() and p.name not in ("MANIFEST.json", "COMPLETE")
    }
    (export / "MANIFEST.json").write_text(json.dumps(manifest))


def test_seal_verify_import_end_to_end(tmp_path: Path) -> None:
    export = _sealed(tmp_path)
    assert (export / "COMPLETE").is_file()
    checked = si.check_export(export)
    assert [c.name for c in checked.dataset.cameras] == ["front", "top"]
    repo = _repo(tmp_path)

    record = si.import_export(export, _split(tmp_path), repo)

    assert record["episodes"] == 3
    assert record["episodes_by_partition"] == {"train": 2, "dev": 1}
    assert record["frames_decoded"] is False
    assert record["target"] == "data/imports/fixture-export-1"  # repository-relative
    ledger = (repo / "ledgers" / "imports.jsonl").read_text().splitlines()
    assert len(ledger) == 1
    derived = repo / si.DERIVED_DIR / "fixture-export-1"
    episode_dirs = sorted(derived.iterdir())
    assert [d.name for d in episode_dirs] == [
        "fixture-export-1-ep000000",
        "fixture-export-1-ep000001",
        "fixture-export-1-ep000002",
    ]
    for ep_dir in episode_dirs:
        result = validate.validate_episode(ep_dir / "episode.json")
        assert result["status"] == "contract_valid"
        assert result["environment_kind"] == "real"


def test_converted_episode_fields(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    si.import_export(_sealed(tmp_path), _split(tmp_path), repo)
    ep_dir = repo / si.DERIVED_DIR / "fixture-export-1" / "fixture-export-1-ep000002"
    episode = json.loads((ep_dir / "episode.json").read_text())
    assert episode["simulator"] is None
    assert episode["configuration"]["embodiment_id"] == "so101_real"
    assert episode["split"]["partition"] == "dev"
    assert episode["split"]["session_group_id"] == "fixture-session-b"
    assert episode["outcome"]["success"] is None
    roles = {s["name"]: s["role"] for s in episode["streams"]}
    assert roles == {
        "state": "input",
        "rgb_front": "input",
        "rgb_top": "input",
        "object_pose": "reference_only",
    }
    state = next(s for s in episode["streams"] if s["name"] == "state")
    assert state["units"][-1] == "normalized_0_100"
    assert episode["action_spec"]["lower"][0] == -100.0

    records = [json.loads(line) for line in (ep_dir / "transitions.jsonl").read_text().splitlines()]
    assert len(records) == 6
    assert records[1]["t_ns"] == round(1 / 30 * 1e9)
    first = {o["stream"]: o for o in records[0]["observations"]}
    assert first["state"]["value"][0] == pytest.approx(20.0)
    assert first["rgb_front"]["artifact"]["path"] == "video-front.mp4"
    assert records[0]["action"]["requested"][0] == pytest.approx(20.5)
    assert records[0]["action"]["applied"] is None
    pose = {o["stream"]: o for o in records[1]["observations"]}["object_pose"]
    assert pose["valid"] is False and pose["value"] is None  # NaN in the recording
    last_next = records[-1]["next_observations"]
    assert all(not o["valid"] for o in last_next)

    adapter = json.loads((ep_dir / "lerobot-adapter.json").read_text())
    assert adapter["frames_decoded"] is False
    assert adapter["cameras"]["front"]["from_timestamp"] == pytest.approx(9 / 30)
    imported = repo / si.IMPORTS_DIR / "fixture-export-1"
    shard = imported / "dataset/videos/observation.images.front/chunk-000/file-000.mp4"
    assert (ep_dir / "video-front.mp4").stat().st_ino == shard.stat().st_ino  # linked, not copied
    assert not (shard.stat().st_mode & 0o222)  # the import stays read-only


def test_labels_set_success(tmp_path: Path) -> None:
    labels = {
        str(i): {"success": i != 1, "terminated": True, "reviewer_ids": ["owner"]} for i in range(3)
    }
    decl = fx.declaration(labels={"file": "labels.json", "method": "blinded_review"})
    repo = _repo(tmp_path)
    si.import_export(_sealed(tmp_path, decl=decl, labels=labels), _split(tmp_path), repo)
    base = repo / si.DERIVED_DIR / "fixture-export-1"
    outcomes = [
        json.loads((base / f"fixture-export-1-ep00000{i}" / "episode.json").read_text())["outcome"]
        for i in range(3)
    ]
    assert [o["success"] for o in outcomes] == [True, False, True]
    assert outcomes[0]["assessment_method"] == "blinded_review"
    assert outcomes[0]["final_assessment_artifact"]["path"] == "labels.json"


def test_trained_policy_carries_its_identities(tmp_path: Path) -> None:
    decl = fx.declaration(
        purpose="evaluation",
        policy={
            "origin": "trained",
            "checkpoint_id": "ckpt-1",
            "training_run_id": "run-1",
            "family_id": "act",
            "weights": "weights.safetensors",
            "config": "policy-config.json",
        },
    )
    data = fx.write_dataset(tmp_path / "recording")
    (tmp_path / "declaration.json").write_text(json.dumps(decl))
    extras = fx.extras(tmp_path / "extras")
    (tmp_path / "extras" / "weights.safetensors").write_bytes(b"FABRICATED weights")
    (tmp_path / "extras" / "policy-config.json").write_text("{}")
    extras += [
        tmp_path / "extras" / "weights.safetensors",
        tmp_path / "extras" / "policy-config.json",
    ]
    export = si.seal(
        data, tmp_path / "declaration.json", extras, "fixture-export-1", tmp_path / "x"
    )
    repo = _repo(tmp_path)
    # One training run spread over train and dev is leakage, and the split audit refuses it.
    with pytest.raises(si.So101ImportError, match="group leakage"):
        si.import_export(export, _split(tmp_path), repo)
    assert not (repo / si.IMPORTS_DIR / "fixture-export-1").exists()  # refused before copying
    assert not (repo / "ledgers" / "imports.jsonl").exists()
    # With the run's episodes in one partition, the same export imports.
    both_train = fx.split(**{"fixture-session-b": {"partition": "train", "scene_group_id": "b"}})
    repo = tmp_path / "repo2"
    (repo / "ledgers").mkdir(parents=True)
    si.import_export(export, _split(tmp_path, both_train), repo)
    ep = repo / si.DERIVED_DIR / "fixture-export-1" / "fixture-export-1-ep000000" / "episode.json"
    episode = json.loads(ep.read_text())
    assert episode["policy"]["origin"] == "trained"
    assert episode["split"]["policy_run_group_id"] == "run-1"


# ------------------------------------------------------------------ refusals


def test_refuses_without_complete(tmp_path: Path) -> None:
    export = _sealed(tmp_path)
    (export / "COMPLETE").unlink()
    with pytest.raises(ExportImportError, match="COMPLETE"):
        si.check_export(export)


def test_refuses_hash_mismatch(tmp_path: Path) -> None:
    export = _sealed(tmp_path)
    (export / "dataset" / "meta" / "info.json").write_text("{}")
    with pytest.raises(ExportImportError, match="hash mismatch"):
        si.check_export(export)


def test_refuses_unlisted_dataset_file(tmp_path: Path) -> None:
    export = _sealed(tmp_path)
    (export / "dataset" / "stray.parquet").write_bytes(b"x")
    with pytest.raises(si.So101ImportError, match="not hashed"):
        si.check_export(export)


def test_refuses_other_codebase_version(tmp_path: Path) -> None:
    doc = fx.info()
    doc["codebase_version"] = "v2.1"
    with pytest.raises(si.So101ImportError, match="codebase_version"):
        _sealed(tmp_path, info_doc=doc)


def test_refuses_undeclared_units(tmp_path: Path) -> None:
    units = fx.declaration()["units"]
    del units["gripper.pos"]
    with pytest.raises(si.So101ImportError, match="declared units cover"):
        _sealed(tmp_path, decl=fx.declaration(units=units))


def test_refuses_unknown_unit(tmp_path: Path) -> None:
    units = fx.declaration()["units"] | {"gripper.pos": "percent"}
    with pytest.raises(si.So101ImportError, match="not one of"):
        _sealed(tmp_path, decl=fx.declaration(units=units))


def test_refuses_session_missing_from_split(tmp_path: Path) -> None:
    export = _sealed(tmp_path)
    doc = fx.split()
    del doc["sessions"]["fixture-session-b"]
    with pytest.raises(si.So101ImportError, match="not declared in split"):
        si.import_export(export, _split(tmp_path, doc), _repo(tmp_path))


def test_refuses_sealed_partition(tmp_path: Path) -> None:
    export = _sealed(tmp_path)
    doc = fx.split(**{"fixture-session-b": {"partition": "sealed", "scene_group_id": "b"}})
    with pytest.raises(si.So101ImportError, match="sealed"):
        si.import_export(export, _split(tmp_path, doc), _repo(tmp_path))


def test_refuses_trained_policy_without_ids(tmp_path: Path) -> None:
    decl = fx.declaration(policy={"origin": "trained", "checkpoint_id": "ckpt-1"})
    with pytest.raises(si.So101ImportError, match="a trained policy needs"):
        _sealed(tmp_path, decl=decl)


def test_refuses_row_count_other_than_length(tmp_path: Path) -> None:
    rows = fx.episodes()
    rows[1]["length"] = 7
    with pytest.raises(si.So101ImportError, match="length is 7"):
        si.check_export(_sealed(tmp_path, episode_rows=rows))


def test_refuses_out_of_order_frame_index(tmp_path: Path) -> None:
    rows = fx.frames()
    rows[2]["frame_index"], rows[3]["frame_index"] = 3, 2
    with pytest.raises(si.So101ImportError, match="frame_index"):
        si.check_export(_sealed(tmp_path, frame_rows=rows))


def test_refuses_dropped_frame_timestamps(tmp_path: Path) -> None:
    rows = fx.frames()
    rows[3]["timestamp"] = 5 / 30  # frame 3 recorded at frame 5's time
    with pytest.raises(si.So101ImportError, match="frames off its index"):
        si.check_export(_sealed(tmp_path, frame_rows=rows))


def test_refuses_short_state_vector(tmp_path: Path) -> None:
    rows = fx.frames()
    rows[0]["observation.state"] = rows[0]["observation.state"][:5]
    with pytest.raises(si.So101ImportError, match="must have 6 values"):
        si.check_export(_sealed(tmp_path, frame_rows=rows))


def test_refuses_video_key_absent_from_info(tmp_path: Path) -> None:
    rows = fx.episodes()
    for row in rows:
        row["videos/observation.images.wrist/chunk_index"] = 0
    with pytest.raises(si.So101ImportError, match=r"absent from info\.json"):
        _sealed(tmp_path, episode_rows=rows)


def test_refuses_sessions_not_matching_episodes(tmp_path: Path) -> None:
    decl = fx.declaration(sessions={"0": "fixture-session-a"})
    with pytest.raises(si.So101ImportError, match="sessions are declared"):
        _sealed(tmp_path, decl=decl)


def test_refuses_second_import(tmp_path: Path) -> None:
    export = _sealed(tmp_path)
    repo = _repo(tmp_path)
    si.import_export(export, _split(tmp_path), repo)
    with pytest.raises(si.So101ImportError, match="write-once"):
        si.import_export(export, _split(tmp_path), repo)
    assert len((repo / "ledgers" / "imports.jsonl").read_text().splitlines()) == 1


def test_refuses_resealed_edit_that_breaks_frames(tmp_path: Path) -> None:
    """A producer may re-hash after an edit; the frame checks still catch a broken table."""
    export = _sealed(tmp_path)
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = fx.frames()[:-1]  # drop episode 2's last frame
    data = export / "dataset" / "data" / "chunk-000" / "file-000.parquet"
    data.chmod(0o644)
    pq.write_table(pa.Table.from_pylist(rows), data)
    _reseal(export)
    with pytest.raises(si.So101ImportError, match="rows in its shard"):
        si.check_export(export)


def test_cli_refusal_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    export = _sealed(tmp_path)
    (export / "COMPLETE").unlink()
    assert si.main(["verify", "--export", str(export)]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_failed_conversion_is_ledgered_and_keeps_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = _sealed(tmp_path)
    repo = _repo(tmp_path)

    def boom(**_: Any) -> Path:
        raise si.So101ImportError("simulated conversion failure")

    monkeypatch.setattr(si, "convert_episode", boom)
    with pytest.raises(si.So101ImportError, match="simulated"):
        si.import_export(export, _split(tmp_path), repo)
    assert (repo / si.IMPORTS_DIR / "fixture-export-1" / "COMPLETE").is_file()
    assert not (repo / si.DERIVED_DIR / "fixture-export-1").exists()
    (line,) = (repo / "ledgers" / "imports.jsonl").read_text().splitlines()
    assert json.loads(line)["status"] == "conversion_failed"
