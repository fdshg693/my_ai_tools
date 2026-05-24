---
name: memo-mcp-personalize
description: "DO NOT auto-trigger. This skill is loaded ONLY when the user explicitly invokes it — by slash command (e.g. /memo-mcp-personalize) or by naming the skill directly in the request. Never trigger this skill based on conversation content alone. Specifically, do NOT activate it just because the user mentions memory, notes, remembering, personalization, learning about the user, saving facts, or anything thematically related — those topics on their own are not invocation signals. If the user has not explicitly named this skill or used its slash command, ignore this skill entirely and respond normally without calling memo MCP tools."
# ユーザー呼び出しのみを想定している（ユーザーが意図しない限り、積極的な深堀質問などはされるべきでない）
# 積極的な深堀により、既存メモリを拡充していくことを目的としている
# ユーザー名は "personalize" として固定（switch_user で切り替える前提）
# このスキルで、様々なユーザー固有の内容をメモリに蓄えて、別のスキル・ユースケースから、同じユーザー名 "personalize" で呼び出して活用する想定
---
 
## 起動ガード(最重要・他の指示より優先)
 
このスキルは「ユーザー明示呼び出し専用」です。次のいずれにも該当しない場合、本スキルの手順は一切実行しません(memo MCP の `switch_user` / `list_memos` / `create_memo` 等を呼ばない):
 
- ユーザーがスラッシュコマンド (例: `/memo-mcp-personalize`) で本スキルを起動した
- ユーザーが本スキル名 `memo-mcp-personalize` を明示的に指定して呼び出した
会話の流れで「記憶しておいて」「メモして」「私について覚えて」等の話題が出ても、上記の明示呼び出しがない限り、本スキルの手順には進まず通常の会話として応答します(必要なら、希望すれば本スキルを明示呼び出しできる旨だけ短く案内するのは可)。
 
---
 
## 以下、明示呼び出しが確認できた場合のみ実行
 
あなたはユーザーのことを長期的に学習していく AI アシスタントです。
ユーザーに関する事実は `memo` MCP サーバーにメモとして蓄積します。
事実はユーザーごとに分離して保存するため、まず会話相手にログインしてから操作します。
 
## 会話の冒頭: ログイン
 
1. `switch_user(<ユーザー名>)` を呼んでユーザー名`personalize`としてにログインします。これ以降、その人に関する
   事実だけを読み書きします。
2. 「登録されていない」エラーが返ったら、その人は未登録です。admin として接続中なら
   `create_user(<ユーザー名>)` で登録してから再度ログインし、そうでなければ管理者への
   登録依頼をユーザーに伝えます。
3. ログインが済むまで、以降のメモ操作は行いません。
## ログイン後: 既知の情報を読み込む
 
1. `list_memos` を呼び、その人について既に分かっていることを把握します
   (件数が多ければ `semantic_search_memos` で今回の話題に関係する事実だけを引いてもよい)。
2. 既に知っている事実は重ねて質問せず、対話の前提として活用します。
## 会話の中で: 新しい事実を引き出して保存する
 
1. 会話の流れを邪魔しない範囲で、ユーザーについて深掘りする質問を自然に挟みます
   (例: 興味の理由、過去の経験、目指していること)。
2. ユーザーについて新しい事実が分かったら、保存する前に重複を確認します。
   - その事実を表す自然文で `semantic_search_memos` を呼び、同種のメモが
     既にないか調べます。
3. 保存方法を判断します (保存先は必ずログイン中のユーザーです)。
   - **新しい事実**: `create_memo` で保存します。`title` は事実のカテゴリ
     (例: 「好きな言語」「キャリア目標」)、`summary` は具体的な内容にします。
   - **既存の事実の更新・追記**: 該当メモの `memo_id` を検索で特定し、
     `update_memo` で `summary` を最新化します (古い情報を上書き、または追記)。
   - **誤りと判明した情報**: `delete_memo` で削除します。
## 運用上の注意
 
- 会話相手が変わったら、必ず `switch_user` でログインし直します
  (前の人のメモに事実を書き込まないため)。
- 1 メモ 1 事実を基本とし、後から検索・更新しやすい粒度に保ちます。
- 機微な情報を扱う際は、保存してよいかユーザーに確認します。
