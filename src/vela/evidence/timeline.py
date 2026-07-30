"""Stage-4 时间戳规整：车端日志最难的一环。

六种形态 -> 统一 UTC 时间轴，并诚实地给出置信度：
  WALL          带完整日期的墙钟
  WALL(无年份)  logcat/syslog/glog 形态，年份需推断（含跨年回绕检测）
  MONOTONIC     dmesg 单调时钟，需锚点对齐到墙钟
  BOOT_RELATIVE bootloader 开机相对时间
  DERIVED       解析失败/续行，继承上一条时间
  NONE          完全无时间信息

置信度（ts_confidence）随后贯穿传播到工具结果 -> 证据条目 -> 报告结论
（交底书机制五：底层数据质量的不确定性被确定性地传导至最终结论）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from vela.util.timeutil import UTC, parse_bsd_month_day

TS_WALL, TS_MONO, TS_BOOT, TS_DERIVED, TS_NONE = "WALL", "MONOTONIC", "BOOT_RELATIVE", "DERIVED", "NONE"

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,9}))?"
                     r"(Z|[+-]\d{2}:?\d{2})?$")
_SLASH_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d{1,6})$")
_MD_RE = re.compile(r"^(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$")
_GLOG_RE = re.compile(r"^(\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d{1,6})$")


@dataclass
class TimeResult:
    ts_utc: datetime | None
    ts_local: datetime | None
    ts_kind: str
    ts_confidence: float
    monotonic_ns: int | None
    has_tz: bool
    has_year: bool
    precision_digits: int


def compute_ts_confidence(kind: str, *, has_tz: bool, has_year: bool, precision_digits: int,
                          anchor_conf: float = 1.0, monotonic_ok: bool = True) -> float:
    """技术方案 §7.7 打分规则。"""
    base = {TS_WALL: 0.95, TS_BOOT: 0.80, TS_MONO: 0.80, TS_DERIVED: 0.60, TS_NONE: 0.0}.get(kind, 0.0)
    score = base
    if not has_tz:
        score -= 0.05
    if not has_year:
        score -= 0.08
    if precision_digits == 0:
        score -= 0.05
    if not monotonic_ok:
        score -= 0.20
    score *= anchor_conf
    return round(max(0.0, min(1.0, score)), 3)


@dataclass
class ClockAnchor:
    boot_id: str
    monotonic_ns: int
    wall_utc: datetime
    source_file_id: int
    source_line_no: int
    method: str
    residual_ms: float = 0.0
    weight: float = 1.0


class TimestampNormalizer:
    """单文件维度的时间归一器（文件间通过共享 anchors 协同）。"""

    def __init__(self, *, local_tz: str = "Asia/Shanghai", reference_time: datetime | None = None,
                 year_inference: bool = True, clock_jump_threshold_ms: int = 5000):
        self.tz = ZoneInfo(local_tz)
        self.reference_time = reference_time or datetime.now(UTC)
        self.year_inference = year_inference
        self.jump_ms = clock_jump_threshold_ms
        self.anchors: list[ClockAnchor] = []
        # 每文件状态
        self.reset_file()

    def reset_file(self, boot_id: str = "boot-0") -> None:
        self.prev_utc: datetime | None = None
        self.clock_epoch = 0
        self.boot_id = boot_id
        self._year = self.reference_time.year
        self._last_md: tuple[int, int] | None = None

    # -- 解析 ------------------------------------------------------------
    def _parse_wall(self, ts_raw: str, fmt: str | None) -> tuple[datetime | None, bool, bool, int]:
        """返回 (aware_utc, has_tz, has_year, precision_digits)。"""
        s = ts_raw.strip()
        m = _ISO_RE.match(s)
        if m:
            y, mo, d, hh, mm, ss, frac, tzs = m.groups()
            micro = int((frac or "0").ljust(6, "0")[:6])
            digits = len(frac or "")
            if tzs:
                off = 0 if tzs == "Z" else (int(tzs[1:3]) * 60 + int(tzs[-2:])) * (1 if tzs[0] == "+" else -1)
                dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss), micro,
                              tzinfo=timezone(timedelta(minutes=off)))
                return dt.astimezone(UTC), True, True, digits
            dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss), micro, tzinfo=self.tz)
            return dt.astimezone(UTC), False, True, digits

        m = _SLASH_RE.match(s)
        if m:
            y, mo, d, hh, mm, ss, frac = m.groups()
            dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss),
                          int(frac.ljust(6, "0")[:6]), tzinfo=self.tz)
            return dt.astimezone(UTC), False, True, len(frac)

        if fmt in ("md_hms_ms", "md_hms"):
            m = _MD_RE.match(s)
            if m:
                mo, d, hh, mm, ss, ms = m.groups()
                year = self._infer_year(int(mo), int(d))
                dt = datetime(year, int(mo), int(d), int(hh), int(mm), int(ss),
                              int((ms or "0").ljust(6, "0")[:6]), tzinfo=self.tz)
                return dt.astimezone(UTC), False, False, len(ms or "")

        if fmt == "glog_mmdd":
            m = _GLOG_RE.match(s)
            if m:
                mo, d, hh, mm, ss, frac = m.groups()
                year = self._infer_year(int(mo), int(d))
                dt = datetime(year, int(mo), int(d), int(hh), int(mm), int(ss),
                              int(frac.ljust(6, "0")[:6]), tzinfo=self.tz)
                return dt.astimezone(UTC), False, False, len(frac)

        if fmt == "bsd_mdt":
            year = self.reference_time.year
            mm_ = re.match(r"^([A-Z][a-z]{2})\s+(\d{1,2})", s)
            if mm_:
                mon = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7,
                       "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}[mm_.group(1)]
                year = self._infer_year(mon, int(mm_.group(2)))
            dt = parse_bsd_month_day(s, year)
            if dt is not None:
                dt = dt.replace(tzinfo=self.tz)
                return dt.astimezone(UTC), False, False, 0
        return None, False, False, 0

    def _infer_year(self, month: int, day: int) -> int:
        """
        F3 年份推断 + 跨年回绕检测：
        若当前 (月,日) 明显早于上一条（如 12-31 -> 01-01），年份 +1。
        """
        if not self.year_inference:
            return self.reference_time.year
        if self._last_md is not None:
            lm, ld = self._last_md
            if (month, day) < (lm, ld) and (lm - month) >= 6:
                self._year += 1
        self._last_md = (month, day)
        return self._year

    # -- 主流程 ----------------------------------------------------------
    def normalize(self, *, ts_raw: str | None, ts_kind: str, ts_format: str | None,
                  mono_s: float | None, file_mtime: datetime | None = None) -> TimeResult:
        has_tz = has_year = False
        digits = 0
        ts_utc: datetime | None = None
        mono_ns: int | None = None
        kind = ts_kind

        if ts_kind == TS_WALL and ts_raw:
            ts_utc, has_tz, has_year, digits = self._parse_wall(ts_raw, ts_format)
            if ts_utc is None:
                kind = TS_DERIVED

        elif ts_kind in (TS_MONO, TS_BOOT) and mono_s is not None:
            mono_ns = int(round(mono_s * 1e9))
            base = self._anchor_base(file_mtime)
            if base is not None:
                ts_utc = base + timedelta(seconds=mono_s)
                digits = 6
            else:
                kind = TS_NONE

        if ts_utc is None and kind in (TS_DERIVED, TS_NONE):
            if self.prev_utc is not None:
                ts_utc = self.prev_utc                  # 继承上一条：DERIVED
                kind = TS_DERIVED
            else:
                kind = TS_NONE

        monotonic_ok = True
        if ts_utc is not None and self.prev_utc is not None:
            delta_ms = (ts_utc - self.prev_utc).total_seconds() * 1000.0
            if delta_ms < -self.jump_ms:
                self.clock_epoch += 1                   # 时钟跳变：纪元 +1
                monotonic_ok = False
            elif delta_ms < 0:
                monotonic_ok = False

        anchor_conf = 1.0 if kind == TS_WALL else (0.95 if self.anchors else 0.85)
        conf = compute_ts_confidence(kind, has_tz=has_tz, has_year=has_year,
                                     precision_digits=digits, anchor_conf=anchor_conf,
                                     monotonic_ok=monotonic_ok)
        if ts_utc is not None:
            self.prev_utc = ts_utc
        local = ts_utc.astimezone(self.tz) if ts_utc else None
        return TimeResult(ts_utc=ts_utc, ts_local=local, ts_kind=kind, ts_confidence=conf,
                          monotonic_ns=mono_ns, has_tz=has_tz, has_year=has_year,
                          precision_digits=digits)

    # -- 锚点 ------------------------------------------------------------
    def add_anchor(self, anchor: ClockAnchor) -> None:
        self.anchors.append(anchor)

    def _anchor_base(self, file_mtime: datetime | None) -> datetime | None:
        """
        monotonic -> wall 的基准时刻（boot 时刻）。
        优先级：强锚点（同行双戳/回归拟合） > 文件 mtime 反推 > 参考时间反推。
        """
        if self.anchors:
            best = sorted(self.anchors, key=lambda a: (-a.weight, a.source_line_no))[0]
            return best.wall_utc - timedelta(microseconds=best.monotonic_ns / 1000.0)
        if file_mtime is not None:
            return file_mtime - timedelta(hours=1)      # 保守假设：日志覆盖最近 1 小时
        return self.reference_time - timedelta(hours=1)


@dataclass
class TimelineStats:
    total: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    clock_jumps: int = 0
    out_of_order: int = 0
    low_conf: int = 0

    def observe(self, tr: TimeResult, gap_ms: int | None) -> None:
        self.total += 1
        self.by_kind[tr.ts_kind] = self.by_kind.get(tr.ts_kind, 0) + 1
        if tr.ts_confidence < 0.6:
            self.low_conf += 1
        if gap_ms is not None and gap_ms < 0:
            self.out_of_order += 1
