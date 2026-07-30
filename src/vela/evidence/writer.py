"""Stage-6 Bronze/Silver 写出：Arrow 批构建 -> Parquet -> DuckDB 全局排序与分区。"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from vela.evidence.models import LOG_LINES_SCHEMA


class ShardWriter:
    """按批把行字典写成 Bronze 分片（分片内保持产生顺序）。"""

    def __init__(self, bronze_dir: Path, batch_rows: int = 50_000, compression: str = "zstd"):
        self.dir = Path(bronze_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.batch_rows = batch_rows
        self.compression = compression
        self._buf: list[dict] = []
        self._part = 0
        self.rows_written = 0
        self.files: list[Path] = []

    def add(self, row: dict) -> None:
        self._buf.append(row)
        if len(self._buf) >= self.batch_rows:
            self.flush()

    def extend(self, rows: Iterable[dict]) -> None:
        for r in rows:
            self.add(r)

    def flush(self) -> None:
        if not self._buf:
            return
        table = _rows_to_table(self._buf)
        path = self.dir / f"part-{self._part:04d}.parquet"
        pq.write_table(table, path, compression=self.compression, use_dictionary=True)
        self.files.append(path)
        self.rows_written += len(self._buf)
        self._part += 1
        self._buf.clear()

    def close(self) -> None:
        self.flush()


def _rows_to_table(rows: list[dict]) -> pa.Table:
    cols: dict[str, list] = {name: [] for name in LOG_LINES_SCHEMA.names}
    for r in rows:
        for name in cols:
            cols[name].append(r.get(name))
    arrays = []
    for field in LOG_LINES_SCHEMA:
        arrays.append(pa.array(cols[field.name], type=field.type))
    return pa.Table.from_arrays(arrays, schema=LOG_LINES_SCHEMA)


SILVER_SQL = """
COPY (
  SELECT * REPLACE (
      row_number() OVER (
          ORDER BY ts_utc NULLS LAST, source_rank, file_id, line_no
      ) - 1 AS line_id
  )
  FROM read_parquet($bronze_glob)
  ORDER BY ts_utc NULLS LAST, source_rank, file_id, line_no
) TO $silver_dir
(FORMAT parquet, COMPRESSION zstd, PARTITION_BY (component, dt),
 ROW_GROUP_SIZE {row_group}, OVERWRITE_OR_IGNORE);
"""


def build_silver(con, bronze_dir: Path, silver_dir: Path, row_group_size: int = 200_000) -> int:
    """
    Silver 层：全局排序 + 稠密 line_id + Hive 分区写出。
    排序是性能关键——Parquet 的 min/max 统计只有在数据有序时才具备强剪枝能力。
    """
    silver_dir = Path(silver_dir)
    if silver_dir.exists():
        import shutil
        shutil.rmtree(silver_dir)
    silver_dir.parent.mkdir(parents=True, exist_ok=True)
    sql = SILVER_SQL.format(row_group=row_group_size)
    con.execute(sql, {"bronze_glob": str(Path(bronze_dir) / "*.parquet"),
                      "silver_dir": str(silver_dir)})
    n = con.execute("SELECT count(*) FROM read_parquet($g)",
                    {"g": str(silver_dir / "**" / "*.parquet")}).fetchone()[0]
    return int(n)


def iter_parquet_rows(path: Path, columns: list[str] | None = None) -> Iterator[dict]:
    for batch in pq.ParquetFile(path).iter_batches(columns=columns):
        for row in batch.to_pylist():
            yield row
