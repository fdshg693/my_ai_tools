# Basic

## ツールの説明文の書き方

- description などを引数で指定することで、 Doc String などの自動読み取り結果を使わずに、ツールの説明文を明示的に指定することができます。
    - https://gofastmcp.com/servers/tools#decorator-arguments

## ツールの可視性

- タグなどを元に、サーバーレベルでツールの有効/無効を切り替えることができます。
    - https://gofastmcp.com/servers/visibility#disabling-components

- サーバーレベルでなく、セッションレベルでツールの有効/無効を切り替えることもできます。
    - https://gofastmcp.com/servers/visibility#per-session-visibility

- 詳細・検証結果・落とし穴（`list_changed` 通知が自動で飛ぶこと等）は [visibility.md](./visibility.md) に、
  セッション操作に必要な `ctx: Context` の注入は [context.md](./context.md) にまとめた。