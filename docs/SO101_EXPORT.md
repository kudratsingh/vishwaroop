# SO-101 recordings: what an export must contain (WO-023)

This repository reads real SO-101 recordings only as **completed, sealed exports** (`AGENTS.md §1.2`, `§13.4`). The owner records with LeRobot, then seals the finished dataset with the tool below. Agents never record, never touch the arm, and never edit an export.

## 1. Seal a finished recording (owner)
After `lerobot-record` has finished and called `finalize()`:

```bash
python -m vishwaroop.data.so101_import seal \
  --dataset <the LeRobot dataset directory> \
  --declaration <declaration.json> \
  --extra <calibration.json> --extra <rubric.json> [--extra <labels.json>] \
  --export-id <a new id, e.g. so101-pilot-2026-11-12a> \
  --out <export root>
```

`seal` copies the dataset to `<export root>/<export id>/dataset/` and copies each `--extra` file next to it, by file name. It then writes `MANIFEST.json`, with every file's sha256 and the declaration, and writes `COMPLETE` last. The recording itself is only read. An existing export id is refused: a new recording gets a new id.

## 2. The declaration
This JSON is stored in `MANIFEST.json` as `identities.so101`. Every field is required unless marked optional. Nothing is guessed, and a missing or unknown value is refused.

| Field | Meaning |
|---|---|
| `format` | `"lerobot-v3.0"` (the dataset's `meta/info.json` must say `codebase_version: "v3.0"`) |
| `dataset_root` | `"dataset"` |
| `units` | one unit per joint name in `observation.state`, each one of `deg`, `rad`, `normalized_m100_100`, `normalized_0_100`. LeRobot's SO-101 follower records normalized values (−100 to 100 for the joints, 0 to 100 for the gripper) unless `use_degrees` was set. Declare what was actually used. |
| `calibration` | file name of the follower's calibration file, passed with `--extra` |
| `rubric` | file name of the task's success rubric, passed with `--extra` |
| `task_id`, `task_version`, `protocol_version` | the task and the collection protocol, as frozen before recording |
| `recorded_at` | ISO 8601 time of the session |
| `robot_id` | the follower's LeRobot id |
| `purpose` | `"demonstration"` (teleop data) or `"evaluation"` (policy rollouts) |
| `sessions` | every episode index mapped to its session id, e.g. `{"0": "2026-11-12a", "1": "2026-11-12a"}` |
| `policy` | `{"origin": "teleop"}`, or `{"origin": "trained", "checkpoint_id", "training_run_id", "family_id", "weights", "config"}`. Weights and config are file names passed with `--extra`. An optional `policy_run_group_id` defaults to the run id. |
| `labels` (optional) | `null`, or `{"file": "labels.json", "method": "blinded_review" \| "physical_sensor_and_review"}`. The file maps each episode index to `{"success": true \| false, "reviewer_ids": [...], "terminated", "truncated", "reason"}`. |
| `object_pose` (optional) | `null`, or `{"feature": "<the dataset feature>", "frame_id": "<its frame>", "units": [one per element]}`. It is imported as a `reference_only` stream that no policy input may use. |

## 3. The split, declared before import
The import needs a split file, committed before the import runs:

```json
{"split_id": "so101-real-v1", "sessions": {"2026-11-12a": {"partition": "train", "scene_group_id": "bench-v1"}}}
```

- Every session in the export must appear in it.
- Partitions are `train`, `dev` or `regression`.
- `sealed` is refused, because sealed suites stay outside agent reach.
- A session, scene group, or policy training run that spans two partitions is refused before anything is copied.

## 4. What the import produces and claims
For each episode, the import writes `data/derived/so101-real/<export id>/<episode id>/` as a contract-v1 episode with `environment_kind: real`. It holds:

| Stream | Role | Notes |
|---|---|---|
| joint state | input | in the declared units |
| one `rgb_<camera>` stream per camera | input | |
| `object_pose` | reference only | when declared |
| the recorded action | — | as the requested stage only |

- **Clock.** Times are LeRobot's nominal frame times (clock domain `lerobot_nominal_frame_time`). True capture latency is not recorded and is not invented.
- **Video.** Camera frames stay in the recorded MP4 shards, hard-linked and never re-encoded. `lerobot-adapter.json` says where each episode's frames start in its shard. Frames are not decoded on import.
- **Outcome.** `success` is set only from a declared label file.

The import also writes one line to `ledgers/imports.jsonl`. The copy in `data/imports/<export id>/` is read-only and is never deleted.
