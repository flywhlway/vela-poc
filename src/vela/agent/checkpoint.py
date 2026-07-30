"""会话检查点：每轮落盘，进程被杀后可从最后一轮续跑。"""
from __future__ import annotations

from pathlib import Path

from vela.agent.state import SessionState
from vela.util.jsonl import read_json, write_json


class CheckpointStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        return self.root / f"{session_id}.state.json"

    def save(self, st: SessionState) -> Path:
        p = self.path_for(st.session_id)
        write_json(p, st.to_dict())          # 原子写：tmp + os.replace
        return p

    def load(self, session_id: str) -> SessionState | None:
        p = self.path_for(session_id)
        if not p.exists():
            return None
        return SessionState.from_dict(read_json(p))

    def exists(self, session_id: str) -> bool:
        return self.path_for(session_id).exists()
