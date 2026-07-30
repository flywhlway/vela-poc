"""OTA 全流程跨 ECU 日志仿真器。

设计目标：
  1. 让证据平面 / 推理平面 / 评测体系在**没有真实车端日志**时也能端到端跑通并被验证；
  2. 数据形态尽量贴近真实（多格式、多编码、乱序、时钟跳变、日志风暴、多行栈、滚动切片）；
  3. 完全确定：给定 seed，产物逐字节可复现（评测与 CI 依赖此性质）。

生产切换：真实日志包直接放入 data/incoming/ 并用 `vela build <zip>` 处理，
仿真器只是**同一入口的另一个数据来源**，下游全链路代码零改动。
"""
from vela.sim.fleet import Fleet, Vehicle, ECU, make_vin
from vela.sim.scenarios import SCENARIOS, Scenario

__all__ = ["Fleet", "Vehicle", "ECU", "make_vin", "SCENARIOS", "Scenario"]
