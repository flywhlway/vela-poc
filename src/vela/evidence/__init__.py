"""证据平面：从日志包到可查询、可取证的列式数据库。

Stage-0 安全解包 -> Stage-1 清单/编码/组件归属 -> Stage-2 行迭代（字节偏移+多行合并）
-> Stage-3 解析器注册表 -> Stage-4 时间归一与富化 -> Stage-5 指纹与模板
-> Stage-6 Parquet(Bronze/Silver) -> Stage-7 DuckDB(Gold) -> Stage-8 质量校验
"""
