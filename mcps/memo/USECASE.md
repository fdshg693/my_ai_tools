# 考えられるユースケース

`memo` MCP サーバーは「タイトル + 概要」からなる単純なメモを蓄積・検索するためのツール群を提供する。
これを AI のシステムプロンプトに組み込むことで、過去の会話を踏まえた継続的な対話や、ユーザーについての長期的な学習が可能になる。

> **このファイルについて**: USECASE.md は入口 (索引) です。詳細はトピックごとに [usecase/](./usecase/) に分割してあり、
> 下記からたどります。各ユースケースを実際のスキルに落とし込んだ例は [sample_skills/](./sample_skills/) にあります
> (細かい点は、ユースケースに応じて調整すること)。新しいトピックは `usecase/` に新規ファイルとして追加し、ここから参照を張ること。

メモは**接続ユーザーごとに完全に分離**されているため、人ごとに別ユーザーを割り当て、
**会話の冒頭で対象ユーザーにログイン (`switch_user`) してから**メモを読み書きするのが安全な使い方になる
([usecase/login.md](./usecase/login.md) 参照)。

さらに各メモは 1 つの**カテゴリ**に属する。カテゴリは**ユーザーごとに管理する独立した存在**で、
メモは自分が登録済みのカテゴリにだけ紐づけられる (新規ユーザーは `OTHERS` のみ。`create_category` で追加)。
カテゴリで「仕事」「私用」などの文脈を分けておき、検索・一覧時にカテゴリを指定すると**同一カテゴリの
メモだけ**に絞り込める。`switch_user` はログイン時にその人の登録済みカテゴリ一覧も返すので、メモ作成時の
カテゴリ選びや以降の絞り込みの手掛かりになる ([usecase/category.md](./usecase/category.md) 参照)。

## ドキュメント索引

共通の前段:

- [usecase/tools.md](./usecase/tools.md) — ツール早見表と検索ツールの使い分け
- [usecase/login.md](./usecase/login.md) — 会話開始時のログイン (どのユースケースでも先頭に置く前段)
- [usecase/category.md](./usecase/category.md) — カテゴリの活用

ユースケース別のシステムプロンプト例:

- [usecase/01-knowledge-exploration.md](./usecase/01-knowledge-exploration.md) — ユースケース 1: 知識探索
- [usecase/02-self-learning.md](./usecase/02-self-learning.md) — ユースケース 2: AI に自分について学習させる

スキルとして落とし込んだ例:

- [sample_skills/memo-mcp-personalize/SKILL.md](./sample_skills/memo-mcp-personalize/SKILL.md) — ユーザー明示呼び出し専用。積極的に深掘りして事実を蓄積する (ユースケース 2 に対応)
- [sample_skills/memo-mcp-ambient/SKILL.md](./sample_skills/memo-mcp-ambient/SKILL.md) — 自動起動を許可する裏方版。深掘りせず、自然に判明した事実だけを静かに記録する
