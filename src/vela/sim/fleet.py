"""车型 / VIN / ECU / 软件版本等基础主数据（仿真用，结构与生产主数据一致）。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# VIN：按 ISO 3779 + NHTSA 校验位算法生成，第 9 位为合法校验位
# ---------------------------------------------------------------------------
_VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"       # 排除 I O Q
_TRANSLIT = {
    **{c: i + 1 for i, c in enumerate("ABCDEFGH")},
    **{c: i + 1 for i, c in enumerate("JKLMN")},
    "P": 7, "R": 9,
    **{c: i + 2 for i, c in enumerate("STUVWXYZ")},
    **{str(d): d for d in range(10)},
}
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def vin_check_digit(vin17: str) -> str:
    total = sum(_TRANSLIT[c] * w for c, w in zip(vin17, _WEIGHTS))
    r = total % 11
    return "X" if r == 10 else str(r)


def make_vin(rng: random.Random, wmi: str = "LSV", model_code: str = "A5E", year_char: str = "S") -> str:
    """生成结构合法（含正确校验位）的 17 位 VIN。WMI 使用非真实厂商前缀。"""
    vds = model_code + "".join(rng.choice(_VIN_CHARS) for _ in range(2))       # 4-8 位
    plant = rng.choice("ABCDEFGH")
    serial = "".join(rng.choice("0123456789") for _ in range(6))
    body = f"{wmi}{vds}0{year_char}{plant}{serial}"                            # 先占位校验位
    vin = body[:8] + "0" + body[9:]
    return vin[:8] + vin_check_digit(vin) + vin[9:]


# ---------------------------------------------------------------------------
# ECU 目录
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ECU:
    ecu_id: str            # 诊断地址，如 0x1A
    name: str              # 缩写，如 VCU
    zh: str                # 中文名
    supplier: str
    bus: str               # CAN-FD / Ethernet / LIN
    flashable: bool
    sw_prefix: str


ECU_CATALOG: list[ECU] = [
    ECU("0x10", "TBOX", "车载通信终端", "SUP-TL", "Ethernet", True, "TB"),
    ECU("0x1A", "VCU", "整车控制器", "SUP-VC", "CAN-FD", True, "VC"),
    ECU("0x22", "BMS", "电池管理系统", "SUP-BM", "CAN-FD", True, "BM"),
    ECU("0x28", "MCU", "电机控制器", "SUP-MC", "CAN-FD", True, "MC"),
    ECU("0x30", "IVI", "座舱主机", "SUP-IV", "Ethernet", True, "IV"),
    ECU("0x36", "ADAS", "智驾域控", "SUP-AD", "Ethernet", True, "AD"),
    ECU("0x40", "BCM", "车身控制器", "SUP-BC", "CAN-FD", True, "BC"),
    ECU("0x46", "EPS", "电动助力转向", "SUP-EP", "CAN-FD", True, "EP"),
    ECU("0x4C", "ESP", "车身稳定系统", "SUP-ES", "CAN-FD", True, "ES"),
    ECU("0x52", "ACU", "安全气囊控制器", "SUP-AC", "CAN-FD", False, "AC"),
    ECU("0x58", "HUD", "抬头显示", "SUP-HU", "LIN", True, "HU"),
    ECU("0x5E", "GW", "中央网关", "SUP-GW", "Ethernet", True, "GW"),
]
ECU_BY_ID = {e.ecu_id: e for e in ECU_CATALOG}
ECU_BY_NAME = {e.name: e for e in ECU_CATALOG}


# ---------------------------------------------------------------------------
# 车型
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VehicleModel:
    code: str
    zh: str
    platform: str
    powertrain: str
    model_code: str        # 进 VIN 的 VDS 段
    ecus: tuple[str, ...]  # ECU name 列表


VEHICLE_MODELS: list[VehicleModel] = [
    VehicleModel("EV-A5", "远行 A5", "EP1", "BEV", "A5E",
                 ("TBOX", "VCU", "BMS", "MCU", "IVI", "BCM", "EPS", "ESP", "GW")),
    VehicleModel("EV-X7", "远行 X7", "EP2", "BEV", "X7E",
                 ("TBOX", "VCU", "BMS", "MCU", "IVI", "ADAS", "BCM", "EPS", "ESP", "HUD", "GW")),
    VehicleModel("PHEV-M3", "远行 M3", "HP1", "PHEV", "M3H",
                 ("TBOX", "VCU", "BMS", "MCU", "IVI", "BCM", "ESP", "ACU", "GW")),
]
MODEL_BY_CODE = {m.code: m for m in VEHICLE_MODELS}


@dataclass
class Vehicle:
    vin: str
    model: VehicleModel
    region: str
    timezone: str
    mileage_km: int
    battery_soc: int
    sw_versions: dict[str, str] = field(default_factory=dict)

    @property
    def target_ecus(self) -> list[ECU]:
        return [ECU_BY_NAME[n] for n in self.model.ecus]


REGIONS = [("CN-SH", "Asia/Shanghai"), ("CN-BJ", "Asia/Shanghai"),
           ("CN-GZ", "Asia/Shanghai"), ("CN-CD", "Asia/Shanghai")]


class Fleet:
    """确定性车队生成器：同 seed 必得同一批车。"""

    def __init__(self, seed: int = 20260729):
        self.rng = random.Random(seed)

    def make_vehicle(self, model_code: str | None = None) -> Vehicle:
        model = (MODEL_BY_CODE[model_code] if model_code
                 else self.rng.choice(VEHICLE_MODELS))
        region, tz = self.rng.choice(REGIONS)
        vin = make_vin(self.rng, model_code=model.model_code)
        sw = {}
        for name in model.ecus:
            e = ECU_BY_NAME[name]
            sw[name] = f"{e.sw_prefix}{self.rng.randint(1, 4)}.{self.rng.randint(0, 9)}.{self.rng.randint(0, 30)}"
        return Vehicle(vin=vin, model=model, region=region, timezone=tz,
                       mileage_km=self.rng.randint(1200, 96000),
                       battery_soc=self.rng.randint(35, 98), sw_versions=sw)

    def make_fleet(self, n: int) -> list[Vehicle]:
        return [self.make_vehicle() for _ in range(n)]


def next_version(cur: str) -> str:
    """给出目标升级版本：末位 +1。"""
    head, _, tail = cur.rpartition(".")
    try:
        return f"{head}.{int(tail) + 1}"
    except ValueError:                                   # pragma: no cover
        return cur + ".1"
