# davinci_mcp — Claude Code × DaVinci Resolve

Claude Code から DaVinci Resolve を直接操作するための MCP サーバーです。
Resolve の公式 Scripting API を使い、既存の `davinci_auto_cut`（無音・フィラーカット）
もツールとして呼び出せます。

```
あなた ──会話──> Claude Code ──MCP(stdio)──> davinci_mcp ──Scripting API──> DaVinci Resolve
```

## できること（ツール一覧）

| ツール | 内容 |
|---|---|
| `get_status` | Resolveのバージョン、開いているページ・プロジェクト・タイムライン |
| `open_page` | ページ切替（media / cut / edit / fusion / color / fairlight / deliver） |
| `list_timelines` / `set_current_timeline` / `create_timeline` | タイムラインの一覧・切替・新規作成 |
| `get_timeline_items` | 現在のタイムライン上のクリップ一覧（開始秒・長さ・ファイルパス） |
| `add_marker` / `get_markers` / `delete_markers` | マーカーの追加・一覧・削除（秒指定） |
| `list_media_pool` / `import_media` / `append_to_timeline` | メディアプールの一覧・読み込み・タイムラインへの追加 |
| `auto_cut` | 無音（＋フィラーワード）カット。`apply` を付けない限りドライラン |
| `list_render_presets` / `render` / `render_status` | プリセットを指定して書き出し・進捗確認 |

## セットアップ（Mac）

> Claude Code は **Resolve と同じMac上で** 動かす必要があります（claude.ai の
> クラウドセッションからはあなたのMacのResolveに届きません）。

1. **Resolve側**: `DaVinci Resolve > 環境設定 > システム > 一般 > 外部スクリプトに使用`
   を「ローカル」にします（無料版はバージョンによって外部スクリプト非対応のことがあります。
   Studio 推奨）。
2. **Python側**（3.10以上）: リポジトリ直下で
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install "mcp>=1.2"        # auto_cut も使うなら pip install -r requirements.txt
   brew install ffmpeg           # auto_cut を使う場合
   ```
3. **Claude Code に登録**: リポジトリ直下に `.mcp.json` が同梱されているので、
   venv を有効にした状態でリポジトリ直下から `claude` を起動するだけです。初回は
   「davinci-resolve サーバーを使いますか？」と聞かれるので許可してください。

   別のフォルダから使いたい場合は、絶対パスでユーザー設定に登録します:
   ```bash
   claude mcp add davinci-resolve --scope user \
     -e PYTHONPATH=/path/to/create \
     -- /path/to/create/.venv/bin/python -m davinci_mcp
   ```
4. Resolve でプロジェクトを開いた状態で、Claude Code 内で `/mcp` を実行し
   `davinci-resolve` が connected になっていれば完了です。

## 使い方の例

Claude Code にそのまま日本語で頼めます:

- 「Resolveの状態を教えて」
- 「今のタイムラインのV1クリップ一覧を出して」
- 「30秒と1分15秒に青いマーカーを打って。名前はそれぞれ『OP』『本編』」
- 「~/Movies/interview.mp4 の無音をカットして。まずドライランで結果を見せて」
- 「今のタイムラインを YouTube 1080p プリセットで ~/Movies/out に書き出して」

`auto_cut` はまずドライラン（ファイルモードは結果レポートのみ、タイムラインモードは
カット予定位置に赤マーカー）で実行し、確認してから適用するようにサーバー側から
Claude に指示しています。

## トラブルシューティング

- **`Could not import DaVinciResolveScript`**: Resolve が起動しているか、外部スクリプトが
  「ローカル」になっているか確認してください。標準以外の場所にインストールしている場合は
  `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` 環境変数を設定します
  （`.mcp.json` の `"env"` に書けます）。
- **`/mcp` で failed になる**: そのターミナルの `python3` に `mcp` が入っているか確認
  （`python3 -c "import mcp"`）。venv を使うなら `.mcp.json` の `command` を
  `.venv/bin/python` にしても構いません。
- **`No project is currently open`**: Resolve でプロジェクトを開いてから再実行してください。

## 動作確認について

`davinci_auto_cut` と同様、この開発環境には Resolve が無いため実機では未検証です。
`tests/test_davinci_mcp_tools.py` で偽の Resolve オブジェクトを使った各ツールの
ロジックを、`tests/test_davinci_mcp_server.py` で実際に MCP サーバーを起動して
クライアントから接続・ツール一覧取得・エラー応答ができることを確認しています。
まずは複製したテスト用プロジェクトで試してください。
