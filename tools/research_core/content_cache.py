from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import cache_contract_version


class ContentAddressedCache:
    """Small content-addressed cache for fetched/extracted research material."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def path_for(self, digest: str, suffix: str = ".bin") -> Path:
        clean = digest.removeprefix("sha256:")
        if not re_full_sha256(clean):
            raise ValueError("cache digest 必须是 SHA256")
        if not suffix.startswith(".") or any(char in suffix for char in ("/", "\\", "..")):
            raise ValueError("cache suffix 必须是简单文件扩展名")
        return self.root / clean[:2] / f"{clean}{suffix}"

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        tmp = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def _atomic_write_json(cls, path: Path, payload: dict[str, Any]) -> None:
        cls._atomic_write(
            path,
            (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )

    def put_bytes(self, data: bytes, *, suffix: str = ".bin", metadata: dict[str, Any] | None = None) -> dict:
        digest = self.digest(data)
        path = self.path_for(digest, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        cache_hit = path.exists()
        if cache_hit:
            existing_digest = self.digest(path.read_bytes())
            if existing_digest != digest:
                raise IOError(f"cache 内容损坏，路径 hash 与内容不一致: {path}")
        else:
            self._atomic_write(path, data)
        metadata_hit = False
        metadata_path: str | None = None
        if metadata is not None:
            metadata_dir = path.with_suffix(path.suffix + ".meta")
            metadata_dir.mkdir(parents=True, exist_ok=True)
            metadata_bytes = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            metadata_digest = self.digest(metadata_bytes)
            record_path = metadata_dir / f"{metadata_digest}.json"
            metadata_hit = record_path.exists()
            if metadata_hit:
                self._validate_metadata_record(record_path, digest, metadata_digest)
            else:
                self._atomic_write_json(
                    record_path,
                    {
                        "cache_contract_version": cache_contract_version(),
                        "content_hash": f"sha256:{digest}",
                        "provenance": dict(metadata),
                    },
                )
            metadata_path = str(record_path)
        return {
            "hash": f"sha256:{digest}",
            "path": str(path),
            "cache_hit": cache_hit,
            "metadata_hit": metadata_hit,
            "metadata_path": metadata_path,
            "cache_contract_version": cache_contract_version(),
        }

    def put_text(self, text: str, *, suffix: str = ".txt", metadata: dict[str, Any] | None = None) -> dict:
        return self.put_bytes(text.encode("utf-8"), suffix=suffix, metadata=metadata)

    @classmethod
    def _validate_metadata_record(cls, path: Path, content_digest: str, metadata_digest: str) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict):
            raise IOError(f"cache provenance 记录损坏: {path}")
        actual_metadata_digest = cls.digest(
            json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if actual_metadata_digest != metadata_digest or payload.get("content_hash") != f"sha256:{content_digest}":
            raise IOError(f"cache provenance hash 校验失败: {path}")
        return payload

    def read_bytes(self, digest: str, *, suffix: str = ".bin") -> bytes:
        path = self.path_for(digest, suffix)
        data = path.read_bytes()
        if self.digest(data) != digest.removeprefix("sha256:"):
            raise IOError(f"cache 内容损坏，路径 hash 与内容不一致: {path}")
        return data

    def provenance_records(self, digest: str, *, suffix: str = ".bin") -> list[dict[str, Any]]:
        path = self.path_for(digest, suffix)
        metadata_dir = path.with_suffix(path.suffix + ".meta")
        records: list[dict[str, Any]] = []
        if metadata_dir.is_dir():
            for record_path in sorted(metadata_dir.glob("*.json")):
                metadata_digest = record_path.stem
                if not re_full_sha256(metadata_digest):
                    raise IOError(f"cache provenance 文件名不是 SHA256: {record_path}")
                payload = self._validate_metadata_record(
                    record_path,
                    digest.removeprefix("sha256:"),
                    metadata_digest,
                )
                if isinstance(payload.get("provenance"), dict):
                    records.append(payload["provenance"])
        legacy_path = path.with_suffix(path.suffix + ".meta.json")
        if legacy_path.is_file():
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            if isinstance(payload.get("provenance_records"), list):
                records.extend(item for item in payload["provenance_records"] if isinstance(item, dict))
            elif isinstance(payload, dict):
                records.append(payload)
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            key = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen.add(key)
                deduped.append(record)
        return deduped


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)
