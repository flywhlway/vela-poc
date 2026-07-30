"""
VELA — Vehicle Evidence & Log Analytics
车联网 OTA 日志证据化与智能诊断 POC。

统一了两份技术文档的方案：
  * 《车端 OTA 升级日志预处理与本地列式取证库技术方案》  -> vela.evidence / vela.query / vela.evidencepack
  * 《基于预算感知证据压缩与可追溯证据链的…专利技术交底书 V3》 -> vela.agent / vela.gateway / vela.obs / vela.eval
"""
from vela.version import __version__, SCHEMA_VERSION, PIPELINE_VERSION

__all__ = ["__version__", "SCHEMA_VERSION", "PIPELINE_VERSION"]
