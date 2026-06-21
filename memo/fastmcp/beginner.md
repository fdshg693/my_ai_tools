# 以下のシンプルなPythonコードを元にMCPサーバーをどのようにFastMCPが構築するか理解する

https://gofastmcp.com/getting-started/quickstart

```python
from fastmcp import FastMCP

mcp = FastMCP("My MCP Server")


@mcp.tool
def greet(name: str) -> str:
    return f"Hello, {name}!"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
```

1. `mcp.run()`は以下の引数を受け取ります:
`Transport = Literal["stdio", "http", "sse", "streamable-http"]`となっていて、MCPサーバーが使用する通信手段を指定します。
```python
transport: Transport | None = None,
show_banner: bool | None = None,
```

2. `mcp.run()`は非同期関数`self.run_async`を同期的に実行するために`anyio.run`を使用します:
- partial(self.run_async, transport, show_banner=..., **transport_kwargs)
    → run_async() に 必要な引数を固定して、引数なしで呼べる関数を作る。
- anyio.run(...)
    → 新しいイベントループを起動し、上の関数（= run_async）を 最初から最後まで実行する。
```python
anyio.run(
    partial(
        self.run_async,
        transport,
        show_banner=show_banner,
        **transport_kwargs,
    )
)
```