"""证据链平面：证据包构建、三级验证、证据快照双源解析。

统一了两份文档的证据链设计：
  * 技术方案 §6.4：证据包 + Merkle 根 + L0/L1/L2 三级离线验证（司法级可追溯）
  * 交底书机制二：row_hash 引用锚点 + 系统级引用校验 + 快照双源解析（10 年可核验）
"""
from vela.evidencepack.builder import EvidenceBuilder
from vela.evidencepack.snapshot import SnapshotStore, resolve_citation
from vela.evidencepack.verifier import verify_l0, verify_l1, verify_l2, verify_all

__all__ = ["EvidenceBuilder", "SnapshotStore", "resolve_citation",
           "verify_l0", "verify_l1", "verify_l2", "verify_all"]
