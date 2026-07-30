"""把统一事件模型渲染为 13 种真实车端日志文本格式之一。

一个组件固定一种格式（与真实车端一致：每个进程有自己的日志库），
从而使整包日志天然具备"多格式混排"特征，用以检验解析器注册表与时间基准推断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc

_LEVEL_SHORT = {"TRACE": "V", "DEBUG": "D", "INFO": "I", "NOTICE": "I",
                "WARN": "W", "ERROR": "E", "FATAL": "F"}
_LEVEL_CN = {"DEBUG": "调试", "INFO": "信息", "NOTICE": "提示",
             "WARN": "警告", "ERROR": "错误", "FATAL": "严重"}
_KLEVEL = {"TRACE": 7, "DEBUG": 7, "INFO": 6, "NOTICE": 5,
           "WARN": 4, "ERROR": 3, "FATAL": 2}
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class LogEvent:
    ts: datetime
    component: str
    level: str
    message: str
    logger: str = ""
    pid: int = 0
    tid: int = 0
    ecu_id: str | None = None
    phase: str | None = None
    mono_s: float = 0.0
    extra: dict = field(default_factory=dict)
    multiline: list[str] = field(default_factory=list)   # 续行（栈帧等）


# ---------------------------------------------------------------------------
# 组件 -> 输出规格
# fmt 名称与 config/parsers.yaml 中的解析器 name 一一对应，便于回归比对
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Sink:
    component: str
    fmt: str
    rel_dir: str
    file_name: str
    encoding: str = "utf-8"
    rotate: int = 0                # >0 表示产生 .1/.2 滚动切片


SINKS: dict[str, Sink] = {
    "ota_master":      Sink("ota_master", "iso_bracket_comp", "ota_master", "ota_master.log"),
    "campaign_client": Sink("campaign_client", "kv_structured", "campaign", "campaign.log"),
    "downloader":      Sink("downloader", "iso_pid_tid", "downloader", "downloader.log", rotate=2),
    "verify_svc":      Sink("verify_svc", "json_line", "verify", "verify.jsonl"),
    "uds_stack":       Sink("uds_stack", "dlt_verbose", "uds", "uds_client.log"),
    "flash_agent":     Sink("flash_agent", "glog_style", "flash", "flash_agent.log"),
    "diag_router":     Sink("diag_router", "short_nodate", "diag", "diag_router.log"),
    "power_mgr":       Sink("power_mgr", "syslog_rfc3164", "power", "powerd.log"),
    "storage_svc":     Sink("storage_svc", "cn_bracket_level", "storage", "storage_svc.log", encoding="gb18030"),
    "tbox_comm":       Sink("tbox_comm", "logcat_threadtime", "tbox", "tbox_comm.log"),
    "ivi_app":         Sink("ivi_app", "logcat_threadtime", "ivi", "ivi_app.log"),
    "kernel":          Sink("kernel", "dmesg_monotonic", "kernel", "dmesg.log"),
    "bootloader":      Sink("bootloader", "uptime_relative", "flash", "bootloader.log"),
}


def _iso(ts: datetime, digits: int = 3) -> str:
    s = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
    return s[: -(6 - digits)] if digits < 6 else s


def render(ev: LogEvent, fmt: str, tz: timezone | None = None) -> str:
    """渲染单条事件（含续行），返回不带结尾换行的完整记录文本。

    tz 为车辆本地时区：真实车端日志按本地时间打印，且多数格式不带时区标识，
    因此下游必须依赖包元数据/配置做时区推断 —— 这是机制五的现实来源。
    """
    lvl = ev.level
    msg = ev.message
    ts = ev.ts.astimezone(tz or UTC)

    if fmt == "iso_bracket_comp":
        head = f"{_iso(ts)} [{ev.logger or ev.component}] {lvl} {msg}"
    elif fmt == "iso_pid_tid":
        head = f"{_iso(ts)} {ev.pid} {ev.tid} {_LEVEL_SHORT.get(lvl,'I')} {ev.logger or ev.component}: {msg}"
    elif fmt == "logcat_threadtime":
        head = (f"{ts.strftime('%m-%d %H:%M:%S')}.{ts.microsecond//1000:03d} "
                f"{ev.pid:5d} {ev.tid:5d} {_LEVEL_SHORT.get(lvl,'I')} {ev.logger or ev.component}: {msg}")
    elif fmt == "dmesg_monotonic":
        head = f"[{ev.mono_s:12.6f}] <{_KLEVEL.get(lvl,6)}>{msg}"
    elif fmt == "syslog_rfc3164":
        head = (f"{_MONTHS[ts.month-1]} {ts.day:2d} {ts.strftime('%H:%M:%S')} "
                f"tbox {ev.logger or ev.component}[{ev.pid}]: {msg}")
    elif fmt == "dlt_verbose":
        head = (f"{ts.strftime('%Y/%m/%d %H:%M:%S.%f')} ECU1 "
                f"{(ev.logger or 'UDSC')[:4].upper():<4s} MAIN log {lvl.lower()} {msg}")
    elif fmt == "glog_style":
        head = (f"{_LEVEL_SHORT.get(lvl,'I')}{ts.strftime('%m%d %H:%M:%S.%f')} "
                f"{ev.tid:5d} {ev.extra.get('src','flash_agent.cc')}:{ev.extra.get('line',100)}] {msg}")
    elif fmt == "json_line":
        import json
        obj = {"ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
               # 注：本格式保留时区偏移，用于验证"含时区"与"不含时区"两类格式的置信度差异
               "lvl": lvl, "module": ev.logger or ev.component, "msg": msg,
               "pid": ev.pid, "tid": ev.tid}
        obj.update({k: v for k, v in ev.extra.items() if k not in ("src", "line")})
        head = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    elif fmt == "cn_bracket_level":
        head = f"{ts.strftime('%Y-%m-%d %H:%M:%S')} 【{_LEVEL_CN.get(lvl,'信息')}】{msg}"
    elif fmt == "kv_structured":
        head = (f"ts={ts.isoformat(timespec='microseconds').replace('+00:00','Z')} "
                f"level={lvl.lower()} comp={ev.logger or ev.component} {msg}")
    elif fmt == "short_nodate":
        head = f"{ts.strftime('%m-%d %H:%M:%S')} {lvl} {msg}"
    elif fmt == "uptime_relative":
        head = f"+{ev.mono_s:.3f}s {lvl} {msg}"
    else:                                                     # pragma: no cover
        head = f"{_iso(ts)} {lvl} {msg}"

    if ev.multiline:
        return head + "\n" + "\n".join(ev.multiline)
    return head


JAVA_STACK = [
    "    at com.vendor.ota.flash.FlashSession.transfer(FlashSession.java:412)",
    "    at com.vendor.ota.flash.FlashSession.run(FlashSession.java:188)",
    "    at java.base/java.lang.Thread.run(Thread.java:840)",
    "Caused by: com.vendor.uds.NegativeResponseException: sid=0x36 nrc=0x72",
    "    at com.vendor.uds.UdsClient.checkResponse(UdsClient.java:266)",
]

CPP_BACKTRACE = [
    "  #0 0x00007f2a1c3b4d21 in flash_erase_sector(uint32_t) at flash_hal.cc:88",
    "  #1 0x00007f2a1c3b6f04 in FlashAgent::program(Block const&) at flash_agent.cc:214",
    "  #2 0x00007f2a1c3c1a55 in FlashAgent::run() at flash_agent.cc:501",
]
