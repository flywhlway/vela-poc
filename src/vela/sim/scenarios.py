"""OTA 故障场景库：每个场景 = 一条可判定真值的根因标签 + 注入点 + 期望证据特征。

评测（vela/eval）以 root_cause_label 为真值口径；
健康场景（S0）用于计算**特异度 / 假阳性率**——只报命中率不报特异度是不可辩护的口径。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    id: str
    zh: str
    root_cause_label: str | None       # None = 健康（无根因）
    fail_phase: str | None             # 在哪个 OTA 阶段中断
    culprit_components: tuple[str, ...]
    culprit_ecu: str | None            # ECU 诊断地址，如 "0x1A"
    expect_keywords: tuple[str, ...]   # 期望在证据中出现的关键词（评测辅助口径）
    expect_skills: tuple[str, ...]     # 期望被选中的技能（检索质量口径）
    narrative: str                     # 真值解释，仅评测使用，绝不进入模型上下文
    healthy: bool = False
    knobs: dict = field(default_factory=dict)


SCENARIOS: dict[str, Scenario] = {
    "S0_HEALTHY": Scenario(
        id="S0_HEALTHY", zh="升级成功（健康负样本）", root_cause_label=None,
        fail_phase=None, culprit_components=(), culprit_ecu=None,
        expect_keywords=(), expect_skills=("SK-PHASE-OVERVIEW",),
        narrative="全流程无故障，用于检验系统在健康会话上是否会硬编根因（假阳性）。",
        healthy=True),

    "S1_DOWNLOAD_TIMEOUT": Scenario(
        id="S1_DOWNLOAD_TIMEOUT", zh="下载分片超时（CDN/链路）",
        root_cause_label="download_cdn_timeout", fail_phase="DOWNLOAD",
        culprit_components=("downloader", "tbox_comm"), culprit_ecu="0x10",
        expect_keywords=("timeout", "chunk", "retry", "HTTP"),
        expect_skills=("SK-DL-TIMEOUT", "SK-NET-LINK"),
        narrative="下载至 62% 时 CDN 节点响应超时，连续重试 5 次均失败，任务在 DOWNLOAD 阶段中止。",
        knobs={"fail_at_chunk_ratio": 0.62, "retries": 5}),

    "S2_SIGNATURE_FAIL": Scenario(
        id="S2_SIGNATURE_FAIL", zh="升级包签名校验失败",
        root_cause_label="signature_verify_fail", fail_phase="VERIFY",
        culprit_components=("verify_svc",), culprit_ecu=None,
        expect_keywords=("signature", "sha256", "invalid", "mismatch"),
        expect_skills=("SK-SIG-VERIFY",),
        narrative="下载完成但包体 sha256 与清单不一致，验签失败，任务在 VERIFY 阶段中止。"),

    "S3_UDS_NRC72": Scenario(
        id="S3_UDS_NRC72", zh="刷写编程失败（UDS NRC 0x72）",
        root_cause_label="uds_nrc_programming_failure", fail_phase="FLASH",
        culprit_components=("uds_stack", "flash_agent"), culprit_ecu="0x1A",
        expect_keywords=("NRC", "0x72", "TransferData", "erase"),
        expect_skills=("SK-UDS-NRC",),
        narrative="VCU(0x1A) 在传输第 47 块时返回 NRC 0x72 generalProgrammingFailure，Flash 擦写异常。",
        knobs={"fail_block": 47}),

    "S4_POWER_DROP": Scenario(
        id="S4_POWER_DROP", zh="电压过低导致刷写中止",
        root_cause_label="power_voltage_drop", fail_phase="FLASH",
        culprit_components=("power_mgr", "uds_stack"), culprit_ecu="0x22",
        expect_keywords=("voltage", "0x93", "battery", "10."),
        expect_skills=("SK-POWER",),
        narrative="蓄电池电压跌至 10.6V 低于 11.0V 阈值，BMS(0x22) 返回 NRC 0x93 voltageTooLow 拒绝刷写。"),

    "S5_STORAGE_FULL": Scenario(
        id="S5_STORAGE_FULL", zh="存储空间不足",
        root_cause_label="storage_insufficient", fail_phase="DOWNLOAD",
        culprit_components=("storage_svc", "kernel", "downloader"), culprit_ecu="0x30",
        expect_keywords=("ENOSPC", "space", "空间", "write"),
        expect_skills=("SK-STORAGE",),
        narrative="下载缓存分区 /data/ota 剩余 42MB 不足以容纳 512MB 包体，写入返回 ENOSPC。"),

    "S6_ECU_SILENT": Scenario(
        id="S6_ECU_SILENT", zh="目标 ECU 无响应（静默）",
        root_cause_label="ecu_no_response", fail_phase="TRANSFER",
        culprit_components=("uds_stack", "diag_router"), culprit_ecu="0x36",
        expect_keywords=("no response", "timeout", "P2", "0x36"),
        expect_skills=("SK-ECU-SILENT",),
        narrative="ADAS(0x36) 在进入编程会话后 45 秒无任何响应，诊断路由判定链路中断。",
        knobs={"silence_seconds": 45}),

    "S7_DEP_MISMATCH": Scenario(
        id="S7_DEP_MISMATCH", zh="依赖版本不匹配",
        root_cause_label="dependency_mismatch", fail_phase="QUERY",
        culprit_components=("campaign_client", "ota_master"), culprit_ecu="0x5E",
        expect_keywords=("version", "dependency", "mismatch", "precondition"),
        expect_skills=("SK-DEP-VER",),
        narrative="网关 GW(0x5E) 当前版本低于包依赖声明的最低版本，前置条件校验未通过。"),

    "S8_ACTIVATE_ROLLBACK": Scenario(
        id="S8_ACTIVATE_ROLLBACK", zh="激活自检失败并回滚",
        root_cause_label="activate_rollback", fail_phase="ACTIVATE",
        culprit_components=("ota_master", "flash_agent", "diag_router"), culprit_ecu="0x28",
        expect_keywords=("activate", "rollback", "self-check", "revert"),
        expect_skills=("SK-ROLLBACK",),
        narrative="MCU(0x28) 刷写成功但激活后自检超时，系统回滚至旧分区，整单判失败。"),

    "S9_TIME_DRIFT": Scenario(
        id="S9_TIME_DRIFT", zh="跨模块时钟漂移导致时序不可判",
        root_cause_label="time_sync_drift", fail_phase="TRANSFER",
        culprit_components=("kernel", "uds_stack", "tbox_comm"), culprit_ecu="0x1A",
        expect_keywords=("clock", "time", "sync", "jump"),
        expect_skills=("SK-TIMEBASE",),
        narrative="TBOX 完成 NTP 同步导致墙钟前跳 87 秒，跨模块事件先后关系不可直接用于因果推断。",
        knobs={"jump_seconds": 87}),
}

FAULT_SCENARIOS = [s for s in SCENARIOS.values() if not s.healthy]
ALL_LABELS = sorted({s.root_cause_label for s in SCENARIOS.values() if s.root_cause_label})


def get(scenario_id: str) -> Scenario:
    if scenario_id not in SCENARIOS:
        raise KeyError(f"未知场景 {scenario_id}，可选: {sorted(SCENARIOS)}")
    return SCENARIOS[scenario_id]
