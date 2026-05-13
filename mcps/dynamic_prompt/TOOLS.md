# MCP ツール一覧

dynamic_prompt が公開している 12 個の MCP ツールと、それらの呼び出し順・依存関係をまとめる。引数の細かい仕様は変わりやすいので、ここではツールの**役割**と**他ツールとの関係**だけを扱う。実際のシグネチャは [tools.py](src/dynamic_prompt/tools.py) の docstring を参照すること。

## カテゴリ別早見表

| カテゴリ | ツール |
|---------|--------|
| セッション初期化 | `determine_language`, `get_instruction` |
| 語彙管理 | `get_words`, `save_words`, `answer_words` |
| 選択式クイズ | `send_quiz`, `get_quiz_results` |
| 自由回答クイズ | `send_free_quiz`, `get_unscored_quizzes`, `score_free_answers`, `get_quiz_results` |
| 話題管理 | `get_past_topics`, `save_story_topic` |

## 全体の依存関係

```
                     ┌────────────────────────┐
                     │  get_instruction(init) │  ← どの言語を学ぶか AI に判断させる
                     └───────────┬────────────┘
                                 │
                     ┌───────────▼────────────┐
                     │   determine_language   │  ← セッションに対象言語を設定
                     └───────────┬────────────┘
                                 │ (これ以降のツールはすべて言語設定が前提)
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
  ┌───────▼──────┐      ┌────────▼────────┐    ┌────────▼────────┐
  │  語彙ループ   │      │   クイズループ    │    │   話題ループ     │
  └──────────────┘      └─────────────────┘    └─────────────────┘
```

`determine_language` で言語をセットしないと、語彙・クイズ・話題系のツールはすべてエラーになる (`session.lang_is_set` チェック)。

---

## セッション初期化

### `get_instruction(name)`

YAML テンプレート ([instructions.yaml](src/dynamic_prompt/prompts/instructions.yaml)) で定義された指示文を取得して AI に渡す。`init` / `general` などの instruction 名を引数に取る。

- **役割**: AI に「今このセッションで何をすべきか」をユーザー設定 (母語など) や言語プロファイル (教え方ガイドなど) と一緒に渡す。
- **依存**: `requires_language: true` の指示は `determine_language` 後でないと取得できない (例外メッセージで案内される)。
- **典型呼び出し順**: 会話冒頭で `get_instruction("init")` → AI が言語を判定して `determine_language` → 必要に応じて `get_instruction("general")` などをその都度取得。

### `determine_language(language)`

セッションの学習対象言語を設定する。言語コード (`en`)・正式名 (`English`)・別名 (`英語`) のいずれでも受け付ける。

- **役割**: 以降のツールすべてが参照する「現在の対象言語」を確定する。
- **依存**: なし (最初に呼ぶべきツール)。
- **未登録言語**: `languages/` に YAML がない言語を渡すと `_default.yaml` のプロファイルにフォールバックする (動作はするが教え方ガイドは汎用)。

---

## 語彙管理

```
        save_words ──┐
                     ▼
                  unknown_words DB
                  (状態: new / needs practice / review)
                     ▲
        get_words ───┤      ← 復習対象の単語を取り出す
                     │
        answer_words ┘      ← 正誤を反映して状態遷移
```

### `save_words(words, context)`

会話で出てきた未知語を DB に登録する。既存単語は重複登録されず context だけ上書きされ、状態 (`status`) は維持される。

- **役割**: 語彙ループの入口。
- **典型シーン**: AI がユーザーの発言/物語で「ユーザーが知らなさそうな単語」を検出したとき。

### `get_words()`

復習対象の単語をランダムに取得する。返却件数は [app_config.yaml](src/dynamic_prompt/prompts/app_config.yaml) の `vocab_get_limit`。

- **役割**: クイズ・復習のネタを AI に供給する。
- **絞り込みルール**: `new` と `needs practice` は常に対象。`review` は `reviewed_at` から `memory_test_period_hours` ([user_config.yaml](src/dynamic_prompt/prompts/user_config.yaml)) 経過した単語のみ対象 (= 一度正解した単語は時間を置いて再出題)。
- **連携先**: ここで得た単語を AI が `send_quiz` / `send_free_quiz` のネタにする。

### `answer_words(correct, incorrect)`

クイズや会話の中で確認した単語の正誤を DB に反映する。状態遷移はツール内で自動。

- **役割**: 語彙ループの出口。忘却曲線を回す心臓部。
- **状態遷移**: `new` で正解 → 削除 / `new` で誤答 → `needs practice` / `needs practice` で正解 → `review` (隠す) / `review` で正解 → 削除。詳細は [CLAUDE.md の Word status levels](CLAUDE.md#word-status-levels)。
- **連携元**: 選択式クイズの結果 (`get_quiz_results`) や、AI とのフリーチャット中の口頭確認から呼ばれることを想定。

---

## 選択式クイズ (Multiple Choice)

```
  send_quiz ──> [DB + SSE で送出] ──> ブラウザで回答 ──> [Web server が即時採点]
                                                              │
                                              get_quiz_results ◀ (AI が結果を確認)
                                                              │
                                                      answer_words へ連携
```

### `send_quiz(title, questions)`

選択式クイズをブラウザに送信する。選択肢の順序はツール内でシャッフルされ、AI 側は「正解を先頭に置く」だけでよい。

- **役割**: 選択式クイズの出口。DB 保存と SSE プッシュを同時に行う。
- **採点**: ブラウザで回答送信した瞬間に Web サーバーが正誤判定して DB に書き込む (AI の介在不要)。
- **次に呼ぶべきツール**: ユーザーが回答した後 `get_quiz_results`。

### `get_quiz_results(limit)`

直近の採点済みクイズの結果を取得する。選択式・自由回答どちらも返ってくる (自由回答は AI が採点したものに限る)。

- **役割**: AI が「ユーザーが何を間違えたか」を把握するための窓口。
- **連携先**: ここで得た正誤情報を `answer_words` に流して語彙ループの状態遷移につなげる。

---

## 自由回答クイズ (Free Answer)

選択式と違い、AI 自身が後から採点する 2 段階フロー。

```
  send_free_quiz ─> [DB + SSE で送出] ─> ブラウザでテキスト回答 ─> [DB に未採点で保存]
                                                                          │
                                                  get_unscored_quizzes ◀──┘
                                                          │
                                              (AI が model_answer と比較して採点)
                                                          │
                                                  score_free_answers
                                                          │
                                                  get_quiz_results
                                                          │
                                                  answer_words へ連携
```

### `send_free_quiz(title, questions)`

自由回答クイズをブラウザに送信する。各問は `model_answer` (模範解答) をセットで持ち、後の採点時に AI が参照する。

- **役割**: 自由回答ループの入口。
- **重要**: 送信した直後は採点されない。**必ず後で** `get_unscored_quizzes` → `score_free_answers` を呼ぶこと (ツールの返却メッセージにも次手順が書かれている)。

### `get_unscored_quizzes(limit)`

ユーザーが提出済みで AI 採点がまだのセッションを返す。

- **役割**: AI が「自分が採点すべき宿題」を引き取るための窓口。
- **返却内容**: 問題文 + 模範解答 + ユーザーの回答テキスト。これらを AI が比較して採点を判断する。

### `score_free_answers(session_id, scores)`

AI が下した正誤判定を DB に書き込む。

- **役割**: 自由回答ループの締め。書き込み後は `get_quiz_results` で結果が見えるようになり、選択式と同じ流れで `answer_words` に繋げられる。

---

## 話題管理 (Story Topics)

AI が物語生成タスク (instructions.yaml の story 系指示) で同じ話題を繰り返さないようにするための補助ツール。AI 自身がこの 2 つを「前後でペアで呼ぶ」運用。

```
  get_past_topics  ──>  (AI が新しい話題を選ぶ)  ──>  物語生成  ──>  save_story_topic
```

### `get_past_topics(limit)`

過去に使った話題を新しい順に取得する。

- **役割**: 物語生成**前**に呼んで、話題の重複を AI に避けさせる。

### `save_story_topic(topic, summary)`

今回採用した話題を記録する。

- **役割**: 物語生成**後**に呼ぶ。次回以降の `get_past_topics` で表示される。

---

## 典型的なフルセッション

語彙学習を一通り回すときの呼び出し順の例:

```
1. get_instruction("init")              ← 会話冒頭で AI が初期指示を取得
2. determine_language("French")         ← 学習言語を確定
3. get_instruction("general")           ← (必要なら) 一般的な進行指示を取得
   ─── ここから自由会話・物語生成など ───
4. save_words("pomme, lire", ...)       ← 出てきた未知語を保存
5. get_past_topics(20)                  ← (物語を作るなら) 過去話題を取得
6. (AI が物語を生成)
7. save_story_topic("weekend picnic")   ← 話題を記録
8. get_words()                          ← 復習対象の単語を取得
9. send_quiz(...) または send_free_quiz(...)
   ─── ユーザーがブラウザで回答 ───
10. (自由回答の場合) get_unscored_quizzes → score_free_answers
11. get_quiz_results(5)                 ← 結果を AI が確認
12. answer_words(correct=..., incorrect=...)  ← 状態遷移を反映
```

この一連の流れはツールが直接強制しているわけではなく、`get_instruction` で返される指示文 ([instructions.yaml](src/dynamic_prompt/prompts/instructions.yaml)) が AI に守らせる前提になっている。
