"""YAML 設定ファイルの取得ソース抽象。

ローカルファイルシステムと GCS バケットの両方に対応する。
`PROMPTS_URI` 環境変数で切り替える:

- `gs://bucket/prefix/` で始まる場合 → GCSConfigSource
- それ以外（パス文字列）または未設定 → LocalConfigSource (デフォルトは
  パッケージ同梱の `prompts/` ディレクトリ)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse


class ConfigSource(Protocol):
    """YAML 設定ファイルを取得するソースの最小インターフェース。"""

    def read_text(self, relative_path: str) -> str:
        """`relative_path` (例 "user_config.yaml") のテキストを返す。"""

    def list_yaml(self, subdir: str) -> list[str]:
        """`subdir` (例 "languages") 配下の YAML ファイルの相対パスを返す。

        返り値は `relative_path` として再度 `read_text` に渡せる形式。
        """


# ---------------------------------------------------------------------------
# Local filesystem
# ---------------------------------------------------------------------------


class LocalConfigSource:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def read_text(self, relative_path: str) -> str:
        return (self.base_dir / relative_path).read_text(encoding="utf-8")

    def list_yaml(self, subdir: str) -> list[str]:
        d = self.base_dir / subdir
        return sorted(f"{subdir}/{p.name}" for p in d.glob("*.yaml"))

    def __repr__(self) -> str:
        return f"LocalConfigSource({self.base_dir})"


# ---------------------------------------------------------------------------
# Google Cloud Storage
# ---------------------------------------------------------------------------


class GCSConfigSource:
    """GCS バケットを設定ソースとして扱う。

    `google-cloud-storage` SDK を使う。Cloud Run 上では Workload Identity
    で認証される。
    """

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket_name = bucket
        # 末尾スラッシュを正規化（後ろに付ける）
        self.prefix = prefix.strip("/")
        self._client = None
        self._bucket = None

    def _ensure_client(self):
        if self._bucket is None:
            from google.cloud import storage  # 遅延 import

            self._client = storage.Client()
            self._bucket = self._client.bucket(self.bucket_name)
        return self._bucket

    def _key(self, relative_path: str) -> str:
        rel = relative_path.lstrip("/")
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def read_text(self, relative_path: str) -> str:
        bucket = self._ensure_client()
        blob = bucket.blob(self._key(relative_path))
        return blob.download_as_text(encoding="utf-8")

    def list_yaml(self, subdir: str) -> list[str]:
        bucket = self._ensure_client()
        sub = subdir.strip("/")
        list_prefix = self._key(sub) + "/"
        blobs = bucket.list_blobs(prefix=list_prefix)
        results: list[str] = []
        # bucket-level prefix を剥がして "subdir/x.yaml" 形式に戻す
        base_strip = (self.prefix + "/") if self.prefix else ""
        for b in blobs:
            if not b.name.endswith(".yaml"):
                continue
            rel = b.name[len(base_strip):] if base_strip else b.name
            results.append(rel)
        return sorted(results)

    def __repr__(self) -> str:
        return f"GCSConfigSource(gs://{self.bucket_name}/{self.prefix})"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


DEFAULT_LOCAL_PROMPTS_DIR = Path(__file__).parent / "prompts"


def make_config_source(uri: str | None = None) -> ConfigSource:
    """環境変数 `PROMPTS_URI` から ConfigSource を作る。

    - `gs://bucket/prefix/...` → GCSConfigSource
    - パス文字列または未設定 → LocalConfigSource
    """
    if uri is None:
        uri = os.environ.get("PROMPTS_URI", "").strip()

    if not uri:
        return LocalConfigSource(DEFAULT_LOCAL_PROMPTS_DIR)

    if uri.startswith("gs://"):
        parsed = urlparse(uri)
        bucket = parsed.netloc
        prefix = parsed.path.lstrip("/")
        if not bucket:
            raise ValueError(f"Invalid GCS URI (missing bucket): {uri!r}")
        return GCSConfigSource(bucket=bucket, prefix=prefix)

    return LocalConfigSource(Path(uri))
