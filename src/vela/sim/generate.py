"""OTA 完整升级流程跨 ECU 日志仿真生成器。

产出：一个 zip 日志包（结构与真实车端上传包一致） + 一个 sidecar 真值文件。
真值文件 **不在 zip 内**，保证诊断链路无法看到答案（评测口径的基本纪律）。
"""
from __future__ import annotations

import os
import random
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vela.sim.emitters import CPP_BACKTRACE, JAVA_STACK, SINKS, LogEvent, render
from vela.sim.fleet import ECU_BY_ID, ECU_BY_NAME, Fleet, Vehicle, next_version
from vela.sim.scenarios import Scenario, get as get_scenario
from vela.util.jsonl import write_json

UTC = timezone.utc

PHASES = ["INIT", "QUERY", "DOWNLOAD", "VERIFY", "TRANSFER", "FLASH", "ACTIVATE", "REPORT"]


@dataclass
class SessionSpec:
    vehicle: Vehicle
    scenario: Scenario
    task_id: str
    campaign_id: str
    seed: int
    start: datetime
    density: int = 10                     # 背景噪声密度倍率（控制日志规模）
    chunks: int = 2600                    # 下载分片数
    blocks: int = 260                     # 每 ECU 刷写块数


@dataclass
class _Ctx:
    rng: random.Random
    events: list[LogEvent] = field(default_factory=list)
    t: datetime = None                    # type: ignore
    boot_epoch: datetime = None           # type: ignore
    clock_shift_s: float = 0.0            # 已施加的墙钟跳变累计

    def mono(self) -> float:
        return (self.t - self.boot_epoch).total_seconds()

    def emit(self, comp: str, level: str, msg: str, *, logger: str = "", pid: int = 0,
             tid: int = 0, ecu: str | None = None, phase: str | None = None,
             dt_ms: float = 0.0, multiline: list[str] | None = None, **extra) -> LogEvent:
        if dt_ms:
            self.t = self.t + timedelta(milliseconds=dt_ms)
        ev = LogEvent(ts=self.t, component=comp, level=level, message=msg,
                      logger=logger or comp, pid=pid or _PID[comp], tid=tid or _PID[comp] + 31,
                      ecu_id=ecu, phase=phase, mono_s=self.mono(),
                      extra=extra, multiline=list(multiline or []))
        self.events.append(ev)
        return ev


_PID = {"ota_master": 1301, "campaign_client": 1322, "downloader": 1420, "verify_svc": 1455,
        "uds_stack": 1502, "flash_agent": 1533, "diag_router": 1560, "power_mgr": 812,
        "storage_svc": 940, "tbox_comm": 1101, "ivi_app": 2201, "kernel": 0, "bootloader": 1}


# ---------------------------------------------------------------------------
# 背景噪声：贯穿全程的心跳/采样/轮询 —— 压缩机制的主要压缩对象
# ---------------------------------------------------------------------------
def _background(ctx: _Ctx, t0: datetime, t1: datetime, spec: SessionSpec) -> None:
    """贯穿全程的心跳/采样/轮询：真实车端日志的主体，也是压缩机制的主要压缩对象。"""
    rng = ctx.rng
    save = ctx.t
    total_s = max(1.0, (t1 - t0).total_seconds())
    n_beats = max(1, int(total_s / 2.0) * spec.density)
    step = total_s / n_beats
    for i in range(n_beats):
        ctx.t = t0 + timedelta(seconds=i * step + rng.random() * step * 0.4)
        rsrp = -78 - rng.randint(0, 22)
        ctx.emit("tbox_comm", "INFO",
                 f"heartbeat seq={i} link=up rsrp={rsrp}dBm rtt={rng.randint(28,180)}ms")
        if i % 3 == 0:
            ctx.emit("ivi_app", "DEBUG",
                     f"ui tick frame={i*2} fps={rng.randint(52,60)} mem={rng.randint(410,520)}MB",
                     logger="IviUi")
        if i % 5 == 0:
            volt = 12.6 - rng.random() * 0.35
            ctx.emit("power_mgr", "INFO",
                     f"battery voltage {volt:.2f}V soc={spec.vehicle.battery_soc}% state=idle",
                     logger="powerd")
        if i % 7 == 0:
            ctx.emit("diag_router", "DEBUG",
                     f"poll dtc snapshot ecu_count={len(spec.vehicle.model.ecus)} pending=0")
        if i % 11 == 0:
            ctx.emit("kernel", "INFO",
                     f"CAN0: tx_queue depth={rng.randint(0,7)} err_cnt=0")
        if i % 13 == 0:
            ctx.emit("ivi_app", "INFO",
                     f"ota progress banner refreshed pct={min(99, i*100//n_beats)}", logger="IviOta")
        if i % 23 == 0:
            ctx.emit("storage_svc", "INFO",
                     f"分区 /data/ota 可用空间 {rng.randint(600,2400)}MB，inode 使用率 {rng.randint(3,18)}%")
        if i % 29 == 0:
            ctx.emit("kernel", "DEBUG",
                     f"mmc0: clock rate {rng.choice([50000000,100000000,200000000])} Hz, bus width 8")
    ctx.t = save


def _rare_lines(ctx: _Ctx, spec: SessionSpec) -> None:
    """低频/一次性事件：稀有模板豁免机制的验证对象（根因常藏于此）。"""
    v = spec.vehicle
    ctx.emit("kernel", "NOTICE", f"thermal zone cpu-thermal trip 78C throttle level 1")
    ctx.emit("ota_master", "NOTICE",
             f"vehicle profile model={v.model.code} platform={v.model.platform} mileage={v.mileage_km}km")
    ctx.emit("storage_svc", "WARN", "文件系统 /data 上次异常卸载，已完成日志重放")
    ctx.emit("tbox_comm", "NOTICE", f"apn switched to ota-dedicated bearer cid=3", logger="TboxNet")
    ctx.emit("bootloader", "INFO", "bootloader entered programming session, watchdog disabled")


# ---------------------------------------------------------------------------
# 各阶段
# ---------------------------------------------------------------------------
def _phase_init(ctx: _Ctx, spec: SessionSpec) -> None:
    v, s = spec.vehicle, spec
    ctx.emit("ota_master", "INFO", f"ota master start, session begin task={s.task_id} vin={v.vin}",
             logger="OtaMaster", phase="INIT")
    ctx.emit("ota_master", "INFO",
             f"OtaManager init config profile={v.model.platform} region={v.region} tz={v.timezone}", dt_ms=120)
    ctx.emit("tbox_comm", "INFO", f"tsp channel established endpoint=tsp-ota-gw:8883 tls=1.3", dt_ms=80)
    ctx.emit("kernel", "INFO", "systemd: Started OTA Update Service.", dt_ms=40)


def _phase_query(ctx: _Ctx, spec: SessionSpec) -> tuple[bool, str]:
    v, s, sc = spec.vehicle, spec, spec.scenario
    ctx.emit("campaign_client", "INFO",
             f"checking for update campaign_id={s.campaign_id} vin_masked=***{v.vin[-4:]}",
             logger="campaign", phase="QUERY", dt_ms=200)
    ctx.emit("campaign_client", "INFO",
             f"policy fetched targets={len(v.model.ecus)} size_mb=512 priority=normal", dt_ms=150)
    for name in sorted(v.model.ecus):
        e = ECU_BY_NAME[name]
        ctx.emit("campaign_client", "DEBUG",
                 f"precondition check ecu={e.ecu_id} name={e.name} cur={v.sw_versions[name]} "
                 f"target={next_version(v.sw_versions[name])} ok=true", dt_ms=25)
    if sc.id == "S7_DEP_MISMATCH":
        e = ECU_BY_ID[sc.culprit_ecu]
        cur = v.sw_versions.get(e.name, "GW1.0.0")
        ctx.emit("campaign_client", "ERROR",
                 f"precondition check ecu={e.ecu_id} name={e.name} cur={cur} "
                 f"required_min=GW3.4.0 result=version mismatch", dt_ms=60)
        ctx.emit("ota_master", "ERROR",
                 f"dependency check failed: ECU {e.ecu_id} version {cur} below required GW3.4.0, abort task",
                 logger="OtaMaster", dt_ms=40)
        ctx.emit("ota_master", "ERROR",
                 "campaign aborted at QUERY phase reason=DEPENDENCY_MISMATCH", dt_ms=30)
        return False, "QUERY"
    ctx.emit("ota_master", "INFO", "all preconditions satisfied, proceed to download", dt_ms=50)
    return True, "QUERY"


def _phase_download(ctx: _Ctx, spec: SessionSpec) -> tuple[bool, str]:
    sc, rng = spec.scenario, ctx.rng
    total = spec.chunks
    ctx.emit("downloader", "INFO",
             f"start download package url=https://cdn-ota.example.net/pkg/{spec.campaign_id}.upd size=536870912",
             logger="OtaDl", phase="DOWNLOAD", dt_ms=300)
    ctx.emit("storage_svc", "INFO", f"为下载分配缓存目录 /data/ota/{spec.task_id}，预留 512MB", dt_ms=60)

    fail_at = int(total * sc.knobs.get("fail_at_chunk_ratio", 1.1)) if sc.id == "S1_DOWNLOAD_TIMEOUT" else total + 1
    space_fail_at = int(total * 0.35) if sc.id == "S5_STORAGE_FULL" else total + 1

    for i in range(1, total + 1):
        if i == space_fail_at:
            ctx.emit("storage_svc", "ERROR",
                     f"写入缓存文件失败：/data/ota/{spec.task_id}/pkg.part 剩余空间 42MB 不足，errno=28 ENOSPC", dt_ms=30)
            ctx.emit("kernel", "ERROR", "EXT4-fs (mmcblk0p12): no space left on device, write failed", dt_ms=10)
            ctx.emit("downloader", "ERROR",
                     f"chunk {i} write failed: ENOSPC no space left on device (need 2MB free 0MB)",
                     logger="OtaDl", dt_ms=15)
            ctx.emit("downloader", "FATAL",
                     "download aborted: insufficient storage space on /data/ota", logger="OtaDl", dt_ms=20)
            ctx.emit("ota_master", "ERROR",
                     "campaign aborted at DOWNLOAD phase reason=STORAGE_INSUFFICIENT", dt_ms=25)
            return False, "DOWNLOAD"

        if i == fail_at:
            for r in range(1, sc.knobs.get("retries", 5) + 1):
                ctx.emit("downloader", "WARN",
                         f"chunk {i} failed, retry {r}: read timeout after 30000ms peer=cdn-node-7",
                         logger="OtaDl", dt_ms=800)
                ctx.emit("tbox_comm", "WARN",
                         f"link degraded rsrp=-113dBm rtt=2450ms retransmit={r*4}", dt_ms=60)
            ctx.emit("downloader", "ERROR",
                     f"HTTP GET https://cdn-ota.example.net/pkg/{spec.campaign_id}.upd "
                     f"failed status=504 gateway timeout after 5 retries", logger="OtaDl", dt_ms=200)
            ctx.emit("downloader", "FATAL",
                     f"download aborted at chunk {i}/{total} ({i*100//total}%), reason=CDN_TIMEOUT",
                     logger="OtaDl", dt_ms=50)
            ctx.emit("ota_master", "ERROR",
                     "campaign aborted at DOWNLOAD phase reason=DOWNLOAD_TIMEOUT", dt_ms=40)
            return False, "DOWNLOAD"

        ctx.emit("downloader", "DEBUG" if i % 10 else "INFO",
                 f"downloading chunk {i}/{total} offset={i*2441406} speed={rng.randint(1100,4200)}KB/s",
                 logger="OtaDl", dt_ms=380 + rng.random() * 90)
        if i % 4 == 0:
            ctx.emit("downloader", "DEBUG",
                     f"HTTP GET /pkg/{spec.campaign_id}.upd range={i*2441406}-{(i+1)*2441406-1} "
                     f"status=206 ttfb={rng.randint(18,160)}ms", logger="OtaDl", dt_ms=12)
        if i % 25 == 0:
            ctx.emit("storage_svc", "INFO", f"已写入 {i*2}MB，缓存目录剩余 {512-i*2}MB", dt_ms=20)

    ctx.emit("downloader", "INFO", f"download completed bytes=536870912 elapsed_ms={total*120}",
             logger="OtaDl", dt_ms=100)
    return True, "DOWNLOAD"


def _phase_verify(ctx: _Ctx, spec: SessionSpec) -> tuple[bool, str]:
    sc = spec.scenario
    ctx.emit("verify_svc", "INFO", "verifying checksum of downloaded package",
             logger="verify", phase="VERIFY", dt_ms=200, alg="sha256")
    if sc.id == "S2_SIGNATURE_FAIL":
        ctx.emit("verify_svc", "ERROR",
                 "sha256 mismatch expected=9f3c1b7e04a2 actual=c81d55af9033",
                 logger="verify", dt_ms=400, expected="9f3c1b7e04a2", actual="c81d55af9033")
        ctx.emit("verify_svc", "ERROR",
                 "signature invalid: package integrity verification failed, cert_chain=OK",
                 logger="verify", dt_ms=60)
        ctx.emit("ota_master", "ERROR",
                 "campaign aborted at VERIFY phase reason=SIGNATURE_VERIFY_FAIL", dt_ms=40)
        return False, "VERIFY"
    ctx.emit("verify_svc", "INFO", "sha256 match, signature ok cert=ota-signing-2026",
             logger="verify", dt_ms=380)
    return True, "VERIFY"


def _phase_transfer_flash(ctx: _Ctx, spec: SessionSpec) -> tuple[bool, str]:
    v, sc, rng = spec.vehicle, spec.scenario, ctx.rng
    targets = [ECU_BY_NAME[n] for n in v.model.ecus if ECU_BY_NAME[n].flashable]
    for e in targets:
        ctx.emit("uds_stack", "INFO",
                 f"DiagnosticSessionControl 0x10 0x02 ecu={e.ecu_id} enter programming session",
                 logger="UDSC", ecu=e.ecu_id, phase="TRANSFER", dt_ms=150)
        ctx.emit("uds_stack", "DEBUG", f"SecurityAccess 0x27 seed/key ok ecu={e.ecu_id}",
                 logger="UDSC", ecu=e.ecu_id, dt_ms=90)

        if sc.id == "S6_ECU_SILENT" and e.ecu_id == sc.culprit_ecu:
            silence = sc.knobs.get("silence_seconds", 45)
            ctx.emit("uds_stack", "INFO", f"RequestDownload 0x34 ecu={e.ecu_id} size=41943040",
                     logger="UDSC", ecu=e.ecu_id, dt_ms=60)
            ctx.t = ctx.t + timedelta(seconds=silence)          # 制造静默区间
            ctx.emit("uds_stack", "ERROR",
                     f"no response from ecu={e.ecu_id} after P2*Server=45000ms, request timeout",
                     logger="UDSC", ecu=e.ecu_id)
            ctx.emit("diag_router", "ERROR",
                     f"ecu {e.ecu_id} unreachable on Ethernet bus, 3 consecutive probes lost", dt_ms=30)
            ctx.emit("ota_master", "ERROR",
                     f"campaign aborted at TRANSFER phase reason=ECU_NO_RESPONSE ecu={e.ecu_id}", dt_ms=40)
            return False, "TRANSFER"

        if sc.id == "S9_TIME_DRIFT" and e.ecu_id == sc.culprit_ecu:
            jump = sc.knobs.get("jump_seconds", 87)
            ctx.emit("uds_stack", "INFO", f"RequestDownload 0x34 ecu={e.ecu_id} size=41943040",
                     logger="UDSC", ecu=e.ecu_id, dt_ms=60)
            ctx.emit("uds_stack", "WARN",
                     f"transfer timing anomaly ecu={e.ecu_id}: response received before request "
                     f"timestamp, delta=-{jump}.000s", logger="UDSC", ecu=e.ecu_id, dt_ms=200)
            ctx.emit("diag_router", "ERROR",
                     f"P2 timer invalid for ecu={e.ecu_id}: monotonic/wall clock disagree by "
                     f"{jump}s, cannot judge request-response ordering", dt_ms=40)
            ctx.emit("ota_master", "ERROR",
                     f"campaign aborted at TRANSFER phase reason=TIME_SYNC_ANOMALY "
                     f"ecu={e.ecu_id} clock_delta={jump}s", dt_ms=40)
            return False, "TRANSFER"

        if sc.id == "S4_POWER_DROP" and e.ecu_id == sc.culprit_ecu:
            for volt in (11.4, 11.0, 10.8, 10.6):
                ctx.emit("power_mgr", "WARN",
                         f"battery voltage {volt:.1f}V below threshold 11.0V state=flashing",
                         logger="powerd", dt_ms=1200)
            ctx.emit("uds_stack", "ERROR",
                     f"NRC received: sid=0x34 nrc=0x93 voltageTooLow ecu={e.ecu_id}",
                     logger="UDSC", ecu=e.ecu_id, dt_ms=100)
            ctx.emit("flash_agent", "ERROR",
                     f"programming precondition not met ecu={e.ecu_id} reason=voltage_too_low",
                     src="flash_agent.cc", line=302, dt_ms=50)
            ctx.emit("ota_master", "ERROR",
                     f"campaign aborted at FLASH phase reason=POWER_VOLTAGE_LOW ecu={e.ecu_id}", dt_ms=40)
            return False, "FLASH"

        ctx.emit("uds_stack", "INFO", f"RequestDownload 0x34 ecu={e.ecu_id} size=41943040",
                 logger="UDSC", ecu=e.ecu_id, dt_ms=60)
        ctx.emit("flash_agent", "INFO", f"erase flash sector range 0x08010000-0x0803FFFF ecu={e.ecu_id}",
                 src="flash_agent.cc", line=180, dt_ms=400)

        nblocks = spec.blocks
        fail_block = sc.knobs.get("fail_block", -1) if sc.id == "S3_UDS_NRC72" else -1
        for b in range(1, nblocks + 1):
            if e.ecu_id == sc.culprit_ecu and b == fail_block:
                ctx.emit("uds_stack", "ERROR",
                         f"NRC received: sid=0x36 nrc=0x72 generalProgrammingFailure ecu={e.ecu_id} block={b}",
                         logger="UDSC", ecu=e.ecu_id, dt_ms=120)
                ctx.emit("flash_agent", "ERROR",
                         f"erase sector failed at block {b}, hal_status=-5 retry exhausted",
                         src="flash_agent.cc", line=214, dt_ms=60,
                         multiline=CPP_BACKTRACE)
                ctx.emit("ota_master", "ERROR",
                         f"flash session exception ecu={e.ecu_id}", dt_ms=40, multiline=JAVA_STACK)
                ctx.emit("ota_master", "ERROR",
                         f"campaign aborted at FLASH phase reason=UDS_NRC_0x72 ecu={e.ecu_id}", dt_ms=30)
                return False, "FLASH"
            if b % 17 == 0:
                ctx.emit("uds_stack", "DEBUG",
                         f"NRC received: sid=0x36 nrc=0x78 responsePending ecu={e.ecu_id} block={b}",
                         logger="UDSC", ecu=e.ecu_id, dt_ms=30)
            ctx.emit("uds_stack", "DEBUG",
                     f"TransferData 0x36 block {b} / {nblocks} ecu={e.ecu_id} len=4096 crc=0x{rng.randrange(1<<16):04x}",
                     logger="UDSC", ecu=e.ecu_id, dt_ms=120)
        ctx.emit("uds_stack", "INFO", f"RequestTransferExit 0x37 ecu={e.ecu_id} ok", logger="UDSC",
                 ecu=e.ecu_id, dt_ms=80)
        ctx.emit("flash_agent", "INFO",
                 f"programming start dependency check 0x31 routine=0xFF01 ecu={e.ecu_id} result=ok",
                 src="flash_agent.cc", line=401, dt_ms=250)
        ctx.emit("bootloader", "INFO", f"flash write verified ecu={e.ecu_id} crc32 ok")
    return True, "FLASH"


def _phase_activate(ctx: _Ctx, spec: SessionSpec) -> tuple[bool, str]:
    v, sc = spec.vehicle, spec.scenario
    targets = [ECU_BY_NAME[n] for n in v.model.ecus if ECU_BY_NAME[n].flashable]
    for e in targets:
        ctx.emit("uds_stack", "INFO", f"ECUReset 0x11 0x01 ecu={e.ecu_id} activate new bank",
                 logger="UDSC", ecu=e.ecu_id, phase="ACTIVATE", dt_ms=200)
        if sc.id == "S8_ACTIVATE_ROLLBACK" and e.ecu_id == sc.culprit_ecu:
            ctx.emit("diag_router", "WARN", f"ecu {e.ecu_id} self-check pending after reset", dt_ms=3000)
            ctx.emit("diag_router", "ERROR",
                     f"ecu {e.ecu_id} self-check timeout after 30000ms, activation not confirmed", dt_ms=6000)
            ctx.emit("flash_agent", "ERROR",
                     f"activate failed ecu={e.ecu_id}, initiating rollback to previous slot",
                     src="flash_agent.cc", line=612, dt_ms=100)
            ctx.emit("ota_master", "WARN", f"rollback started ecu={e.ecu_id} revert to bank A", dt_ms=80)
            ctx.emit("bootloader", "INFO", "restore previous backup image, switch to bank A")
            ctx.emit("ota_master", "ERROR",
                     f"campaign aborted at ACTIVATE phase reason=ACTIVATE_SELFCHECK_TIMEOUT ecu={e.ecu_id}",
                     dt_ms=60)
            return False, "ACTIVATE"
        ctx.emit("diag_router", "INFO", f"ecu {e.ecu_id} self-check ok, version confirmed", dt_ms=800)
    return True, "ACTIVATE"


def _phase_report(ctx: _Ctx, spec: SessionSpec, ok: bool, fail_phase: str | None) -> None:
    status = "SUCCESS" if ok else "FAILED"
    ctx.emit("ota_master", "INFO" if ok else "ERROR",
             f"report result to tsp task={spec.task_id} status={status} "
             f"fail_phase={fail_phase or 'NONE'}", logger="OtaMaster", phase="REPORT", dt_ms=200)
    ctx.emit("campaign_client", "INFO",
             f"campaign result uploaded status={status} code={'0' if ok else '5001'}", dt_ms=150)
    ctx.emit("tbox_comm", "INFO", f"tsp ack received for task={spec.task_id}", dt_ms=100)


def _inject_clock_jump(ctx: _Ctx, spec: SessionSpec) -> None:
    """时钟跳变注入：把某一时刻之后的墙钟整体前跳，制造 clock_epoch 变化与乱序。"""
    jump = spec.scenario.knobs.get("jump_seconds", 87)
    if not ctx.events:
        return
    idx = int(len(ctx.events) * 0.55)
    pivot = ctx.events[idx].ts
    ctx.events.insert(idx, LogEvent(
        ts=pivot, component="tbox_comm", level="NOTICE", logger="TboxNet",
        message=f"ntp sync applied, wall clock stepped forward by {jump}s (was drifting)",
        pid=_PID["tbox_comm"], tid=_PID["tbox_comm"] + 31))
    for ev in ctx.events[idx + 1:]:
        if ev.component in ("tbox_comm", "ivi_app", "ota_master", "campaign_client"):
            ev.ts = ev.ts + timedelta(seconds=jump)
    ctx.events.insert(idx + 2, LogEvent(
        ts=pivot, component="kernel", level="WARN",
        message=f"clocksource: time jump detected, delta={jump}.000s source=arch_sys_counter",
        pid=0, tid=0, mono_s=(pivot - ctx.boot_epoch).total_seconds()))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def build_events(spec: SessionSpec) -> list[LogEvent]:
    rng = random.Random(spec.seed)
    ctx = _Ctx(rng=rng, t=spec.start, boot_epoch=spec.start - timedelta(seconds=1042.5))
    t_begin = spec.start

    _phase_init(ctx, spec)
    ok, ph = _phase_query(ctx, spec)
    fail_phase = None if ok else ph
    if ok:
        ok, ph = _phase_download(ctx, spec)
        fail_phase = None if ok else ph
    if ok:
        ok, ph = _phase_verify(ctx, spec)
        fail_phase = None if ok else ph
    if ok:
        ok, ph = _phase_transfer_flash(ctx, spec)
        fail_phase = None if ok else ph
    if ok:
        ok, ph = _phase_activate(ctx, spec)
        fail_phase = None if ok else ph
    _phase_report(ctx, spec, ok, fail_phase)

    t_end = ctx.t
    # 前置 15 分钟 + 后置 2 分钟：真实日志包包含 OTA 前后的常态运行日志
    _background(ctx, t_begin - timedelta(seconds=900), t_end + timedelta(seconds=120), spec)
    _rare_lines(ctx, spec)
    if spec.scenario.id == "S9_TIME_DRIFT":
        _inject_clock_jump(ctx, spec)

    # 稳定排序：ts 相同时按 (component, message) 字典序消解并列 -> 确定性
    ctx.events.sort(key=lambda e: (e.ts, e.component, e.message))

    # 轻量乱序注入（真实车端多进程写盘的必然现象）
    n = len(ctx.events)
    for i in range(0, n - 3, max(97, n // 60 or 97)):
        ctx.events[i], ctx.events[i + 2] = ctx.events[i + 2], ctx.events[i]
    return ctx.events


def write_session(spec: SessionSpec, out_dir: Path) -> dict:
    """把事件写成多文件多编码的日志目录树，再打成 zip；返回 sidecar 真值 manifest。"""
    events = build_events(spec)
    # 写盘文件的 mtime 必须落在仿真时间线内（用最后一条事件的时间，贴近"日志最后
    # 一次被写入"的真实语义），而不是仿真器这个 Python 进程恰好执行的真实时刻——
    # 否则 unpack 阶段还原出的 mtime 会指向"生成/测试当天"，进而污染
    # TimestampNormalizer 对纯 monotonic 行的锚点兜底反推（见 timeline.py
    # _anchor_base 的 file_mtime 分支），使同一份归档在不同日期重跑得到不同证据。
    session_mtime = (events[-1].ts if events else spec.start).timestamp()
    root = out_dir / f"raw_{spec.task_id}"
    if root.exists():
        import shutil
        shutil.rmtree(root)
    from zoneinfo import ZoneInfo
    local_tz = ZoneInfo(spec.vehicle.timezone)
    buckets: dict[str, list[str]] = {c: [] for c in SINKS}
    for ev in events:
        sink = SINKS[ev.component]
        buckets[ev.component].append(render(ev, sink.fmt, local_tz))

    files_written: list[dict] = []
    for comp, lines in sorted(buckets.items()):
        if not lines:
            continue
        sink = SINKS[comp]
        d = root / "logs" / sink.rel_dir
        d.mkdir(parents=True, exist_ok=True)
        if sink.rotate:                       # 滚动切片：最老的进 .N
            parts = sink.rotate + 1
            size = len(lines) // parts + 1
            chunks = [lines[i * size:(i + 1) * size] for i in range(parts)]
            names = [sink.file_name] + [f"{sink.file_name}.{i}" for i in range(1, parts)]
            payloads = list(reversed(chunks))          # .N 最老
            for name, payload in zip(names, payloads):
                p = d / name
                p.write_bytes(("\n".join(payload) + "\n").encode(sink.encoding, errors="replace"))
                os.utime(p, (session_mtime, session_mtime))
                files_written.append({"path": str(p.relative_to(root)), "lines": len(payload),
                                      "encoding": sink.encoding, "format": sink.fmt})
        else:
            p = d / sink.file_name
            p.write_bytes(("\n".join(lines) + "\n").encode(sink.encoding, errors="replace"))
            os.utime(p, (session_mtime, session_mtime))
            files_written.append({"path": str(p.relative_to(root)), "lines": len(lines),
                                  "encoding": sink.encoding, "format": sink.fmt})

    # 包内元数据（真实上传包一般都有）
    meta = {
        "task_id": spec.task_id, "campaign_id": spec.campaign_id,
        "vin": spec.vehicle.vin, "model": spec.vehicle.model.code,
        "region": spec.vehicle.region, "timezone": spec.vehicle.timezone,
        "collected_at": spec.start.isoformat().replace("+00:00", "Z"),
        "ecus": [{"ecu_id": ECU_BY_NAME[n].ecu_id, "name": n,
                  "sw_version": spec.vehicle.sw_versions[n]} for n in sorted(spec.vehicle.model.ecus)],
    }
    write_json(root / "package_meta.json", meta)
    os.utime(root / "package_meta.json", (session_mtime, session_mtime))

    zip_path = out_dir / f"OTA_{spec.vehicle.vin[-6:]}_{spec.task_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(root)))
    import shutil
    shutil.rmtree(root)

    truth = {
        "archive": zip_path.name,
        "task_id": spec.task_id, "campaign_id": spec.campaign_id,
        "vin": spec.vehicle.vin, "vin_last4": spec.vehicle.vin[-4:],
        "model": spec.vehicle.model.code, "region": spec.vehicle.region,
        "scenario_id": spec.scenario.id, "scenario_zh": spec.scenario.zh,
        "root_cause_label": spec.scenario.root_cause_label,
        "healthy": spec.scenario.healthy,
        "fail_phase": spec.scenario.fail_phase,
        "culprit_ecu": spec.scenario.culprit_ecu,
        "culprit_components": list(spec.scenario.culprit_components),
        "expect_keywords": list(spec.scenario.expect_keywords),
        "expect_skills": list(spec.scenario.expect_skills),
        "narrative": spec.scenario.narrative,
        "seed": spec.seed,
        "total_records": len(events),
        "files": files_written,
    }
    write_json(out_dir / f"{zip_path.stem}.truth.json", truth)
    return truth


def _model_for_scenario(sc) -> str | None:
    """选一个真实包含该场景 culprit ECU 的车型。

    否则故障注入分支（如 S6 的 ADAS 0x36）会因车型不含该 ECU 而永不触发，
    生成出"元数据说失败、日志却显示成功"的自相矛盾样本。
    """
    if not sc.culprit_ecu:
        return None
    from vela.sim.fleet import ECU_BY_NAME, VEHICLE_MODELS
    want = {n for n, e in ECU_BY_NAME.items() if e.ecu_id == sc.culprit_ecu}
    if not want:
        return None
    for m in VEHICLE_MODELS:
        if want & set(m.ecus):
            return m.code
    return None


def _scenario_seed(scenario_id: str, seed: int) -> int:
    """由 (场景ID, 全局seed) 派生的稳定子种子——不使用 Python hash（受哈希随机化影响）。"""
    import hashlib
    d = hashlib.blake2b(f"{scenario_id}|{seed}".encode("utf-8"), digest_size=6).digest()
    return int.from_bytes(d, "big")


def generate_dataset(out_dir: Path, scenarios: list[str] | None = None, seed: int = 20260729,
                     density: int = 10, chunks: int = 2600, blocks: int = 260,
                     start: datetime | None = None) -> list[dict]:
    """生成一批会话（默认每个场景一条）。返回真值 manifest 列表。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from vela.sim.scenarios import SCENARIOS
    ids = scenarios or sorted(SCENARIOS)
    base = start or datetime(2026, 7, 20, 2, 15, 0, tzinfo=UTC)
    out = []
    all_ids = sorted(SCENARIOS)
    for sid in sorted(ids):
        sc = get_scenario(sid)
        # 场景槽位由全量场景表决定，与本次生成了哪些场景无关 -> 子集生成与整批生成逐字节一致
        slot = all_ids.index(sid)
        sub = _scenario_seed(sid, seed)
        veh = Fleet(sub).make_vehicle(model_code=_model_for_scenario(sc))
        spec = SessionSpec(vehicle=veh, scenario=sc,
                           task_id=f"TASK-{10000 + slot * 7 + (seed % 97)}",
                           campaign_id=f"CMP-2026Q3-{100 + slot}",
                           seed=sub % (2**31),
                           start=base + timedelta(hours=slot * 3),
                           density=density, chunks=chunks, blocks=blocks)
        out.append(write_session(spec, out_dir))
    return out
