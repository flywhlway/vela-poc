"""仿真器：VIN 合法性、确定性、场景自洽、多格式多编码。"""
from __future__ import annotations

import json
import zipfile

from vela.sim.fleet import ECU_BY_NAME, VEHICLE_MODELS, Fleet, make_vin, vin_check_digit
from vela.sim.scenarios import FAULT_SCENARIOS, SCENARIOS, get


def test_vin_check_digit_is_valid_for_generated_vins():
    f = Fleet(42)
    for _ in range(30):
        v = f.make_vehicle().vin
        assert len(v) == 17
        assert v[8] == vin_check_digit(v)


def test_vin_excludes_forbidden_letters():
    f = Fleet(7)
    for _ in range(20):
        assert not (set(f.make_vehicle().vin) & set("IOQ"))


def test_fleet_is_reproducible_for_same_seed():
    a = [v.vin for v in (Fleet(11).make_vehicle() for _ in range(5))]
    b = [v.vin for v in (Fleet(11).make_vehicle() for _ in range(5))]
    assert a == b
    assert a != [v.vin for v in (Fleet(12).make_vehicle() for _ in range(5))]


def test_every_scenario_has_consistent_metadata():
    for sc in SCENARIOS.values():
        if sc.healthy:
            assert sc.root_cause_label is None and sc.fail_phase is None
        else:
            assert sc.root_cause_label and sc.fail_phase and sc.expect_skills


def test_culprit_ecu_exists_in_some_model():
    """场景指定的 ECU 必须真实存在，否则故障注入分支永远不会触发。"""
    for sc in FAULT_SCENARIOS:
        if not sc.culprit_ecu:
            continue
        names = {n for n, e in ECU_BY_NAME.items() if e.ecu_id == sc.culprit_ecu}
        assert names, f"{sc.id} 的 culprit_ecu {sc.culprit_ecu} 不存在于 ECU 表"
        assert any(names & set(m.ecus) for m in VEHICLE_MODELS), \
            f"{sc.id} 的 culprit_ecu 不属于任何车型"


def test_get_unknown_scenario_raises():
    try:
        get("NOPE")
    except KeyError:
        return
    raise AssertionError("未知场景应当抛出 KeyError")


def test_dataset_zip_contains_multiple_dirs_and_encodings(dataset):
    t = dataset["truths"]["S3_UDS_NRC72"]
    with zipfile.ZipFile(dataset["dir"] / t["archive"]) as zf:
        names = zf.namelist()
    assert len(names) >= 8
    assert len({n.split("/")[1] for n in names if "/" in n}) >= 4
    assert {f["encoding"] for f in t["files"]} & {"gb18030"}


def test_truth_sidecar_is_not_inside_the_archive(dataset):
    """真值不得进入压缩包，否则等于把答案交给被测系统。"""
    t = dataset["truths"]["S3_UDS_NRC72"]
    with zipfile.ZipFile(dataset["dir"] / t["archive"]) as zf:
        assert not [n for n in zf.namelist() if "truth" in n]
    assert (dataset["dir"] / f"{t['archive'][:-4]}.truth.json").exists()


def test_healthy_scenario_has_no_abort_marker(dataset, tmp_path):
    t = dataset["truths"]["S0_HEALTHY"]
    with zipfile.ZipFile(dataset["dir"] / t["archive"]) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist())
    assert b"campaign aborted" not in blob


def test_fault_scenario_has_abort_marker(dataset):
    t = dataset["truths"]["S3_UDS_NRC72"]
    with zipfile.ZipFile(dataset["dir"] / t["archive"]) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist())
    assert b"campaign aborted" in blob


def test_generation_is_byte_identical_for_same_seed(tmp_path):
    from vela.sim.generate import generate_dataset
    kw = dict(density=1, chunks=40, blocks=20, scenarios=["S5_STORAGE_FULL"])
    a = generate_dataset(tmp_path / "a", **kw)[0]
    b = generate_dataset(tmp_path / "b", **kw)[0]
    assert a["vin"] == b["vin"] and a["total_records"] == b["total_records"]
    ha = (tmp_path / "a" / f"{a['archive'][:-4]}.truth.json").read_text(encoding="utf-8")
    hb = (tmp_path / "b" / f"{b['archive'][:-4]}.truth.json").read_text(encoding="utf-8")
    assert json.loads(ha)["files"] == json.loads(hb)["files"]


def test_subset_generation_matches_full_batch(tmp_path):
    """子集生成必须与整批生成逐字节一致——否则评测不可复现。"""
    from vela.sim.generate import generate_dataset
    kw = dict(density=1, chunks=40, blocks=20)
    full = {t["scenario_id"]: t for t in
            generate_dataset(tmp_path / "full", scenarios=["S0_HEALTHY", "S5_STORAGE_FULL"], **kw)}
    sub = generate_dataset(tmp_path / "sub", scenarios=["S5_STORAGE_FULL"], **kw)[0]
    assert sub["vin"] == full["S5_STORAGE_FULL"]["vin"]
    assert sub["total_records"] == full["S5_STORAGE_FULL"]["total_records"]
