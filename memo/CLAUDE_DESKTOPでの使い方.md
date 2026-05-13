# Claude Desktop での使い方

## 設定方法

Claude Desktop の設定ファイル (`claude_desktop_config.json`) に MCP サーバーを登録する。
設定ファイルの場所は `%APPDATA%\Claude\claude_desktop_config.json`（Windows の場合）。

本リポジトリの `claude_desktop_config.jsonc` に設定例を載せている。
`--project` のパスを自分の環境に合わせて書き換えるだけで使える。

```jsonc
// claude_desktop_config.jsonc より
{
    "mcpServers": {
        "dynamic_prompt": {
            "command": "uv",
            "args": [
                "run",
                "--project",
                "your/path/to/fastmcp_mcps",  // ← 自分の環境に合わせる
                "dynamic_prompt"               // ← pyproject.toml のエントリーポイント名
            ]
        }
    }
}
```

`uv run dynamic_prompt` は `pyproject.toml` の `[project.scripts]` で定義された
エントリーポイント `dynamic_prompt.main:main` を呼び出す。
`main()` 内で `mcp.run(transport="stdio")` が実行され、Claude Desktop と stdio で通信する。

設定後、Claude Desktop を再起動するとツール一覧（6個）が表示される。

---

## 過去に発生した問題と教訓

### 問題1：`fastmcp run` + ファイルパス指定で「ツール 0 個」になる

#### 症状

Claude Desktop からサーバーに接続すると、ツールが 0 個と表示される。
一方、FastMCP の `Client` を使ったインプロセステストでは正常に 6 個のツールが見える。

#### 原因：`mcp` インスタンスの二重生成

以前の設定では `fastmcp run` にファイルパスを渡していた：

```json
"fastmcp", "run", "C:/.../main.py"
```

この場合、Python のモジュールシステム上で以下のことが起きる：

```
1. fastmcp run が main.py をファイルパスで読み込む
   → importlib.util.spec_from_file_location("main", "C:/.../main.py")
   → モジュール名は "main"（パッケージの一部ではない独立モジュール扱い）
   → mcp インスタンス A が作られる

2. main.py 内の `import dynamic_prompt.tools` が実行される
   → Python は sys.modules に "dynamic_prompt.main" がないので、
     パッケージとして改めて dynamic_prompt.main をインポートする
   → mcp インスタンス B が作られる（A とは別オブジェクト）

3. tools.py の `from dynamic_prompt.main import mcp` は
   パッケージ側の mcp（インスタンス B）を参照する
   → @mcp.tool デコレータはすべてインスタンス B に登録される

4. fastmcp run はファイルから読み込んだモジュール内の mcp を探す
   → インスタンス A が見つかる（ツール 0 個）
   → インスタンス B（ツール 6 個）は使われない
```

検証コードと結果：

```python
import importlib.util
from fastmcp import Client

# ファイルパスで読み込み（fastmcp run の挙動を再現）
spec = importlib.util.spec_from_file_location('main', '.../main.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# パッケージとしてインポート
from dynamic_prompt.main import mcp as pkg_mcp

print(mod.mcp is pkg_mcp)  # → False（別オブジェクト）

# Client で確認
# file_mcp: 0 tools  ← fastmcp run はこちらを使う
# pkg_mcp:  6 tools  ← ツールはこちらに登録されている
```

#### なぜインプロセステストでは問題が起きなかったか

テストコードでは `from dynamic_prompt.main import mcp` でパッケージとしてインポートする。
この場合モジュールは 1 回しか読み込まれず、`mcp` インスタンスは 1 つだけ。
ツールはそのインスタンスに正しく登録される。

### 問題2：`fastmcp run` + モジュールパス指定で「File not found」になる

#### 症状

問題1の対処として `fastmcp run` にモジュールパスを渡すと、ファイルが見つからないエラーになる。

```json
"fastmcp", "run", "dynamic_prompt.main:mcp"
```

```
ERROR  File not found: C:\Windows\System32\dynamic_prompt.main
```

#### 原因

`fastmcp run` の SERVER-SPEC はファイルパスしか受け付けない（v3.0.0b1 時点）。
`dynamic_prompt.main:mcp` は `dynamic_prompt.main` という名前のファイルとして解釈され、
CWD（Claude Desktop の場合は `C:\Windows\System32`）から探してしまう。

### 最終的な対処：`fastmcp run` を使わない

`fastmcp run` を経由せず、`uv run` でエントリーポイントを直接呼ぶ方式に変更した。

```jsonc
// 修正前（NG）
"args": ["run", "--project", "...", "fastmcp", "run", "C:/.../main.py"]

// 修正後（OK）
"args": ["run", "--project", "...", "dynamic_prompt"]
```

この方式では：

- `uv run dynamic_prompt` → `pyproject.toml` のエントリーポイント `dynamic_prompt.main:main` が呼ばれる
- `main.py` はパッケージの一部として正しくインポートされる（`sys.modules["dynamic_prompt.main"]`）
- `import dynamic_prompt.tools` で `tools.py` が読み込まれ、同一の `mcp` インスタンスにツールが登録される
- `main()` 内で `mcp.run(transport="stdio")` が実行される

同時に、`init_db()` を `main()` 内からモジュールレベルに移動した。
これにより、どの経路で起動しても DB 初期化が確実に行われる。

```python
# main.py（最終形）
mcp = FastMCP("dynamic_prompt")
import dynamic_prompt.tools   # ツール登録（side-effect import）
init_db()                      # モジュール読み込み時に実行

def main():
    mcp.run(transport="stdio")
```
