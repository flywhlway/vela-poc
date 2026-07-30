# 生产数据接入目录

把真实车端 OTA 日志压缩包放在这里，然后：

```bash
vela build ./data/incoming/你的压缩包.zip ./workspace/你的工作区名
```

与仿真数据集（`data/dataset/`）走**完全相同**的建库/诊断命令，无需任何额外配置。

可选：压缩包根目录放一个 `package_meta.json`（缺失则走推断兜底）：

```json
{"vin": "LSVxxxxxxxxxxxxx", "timezone": "Asia/Shanghai", "collected_at": "2026-07-20T11:15:00Z"}
```

详见项目根目录 `README.md` 的"生产数据接入"一节。

本目录下的 `*.zip` 已在 `.gitignore` 中排除，不会被意外提交真实车辆数据。
