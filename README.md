# davinci-auto-cut

DaVinci Resolve用の自動カットツール。無音区間とフィラーワード（「えー」「あの」「um」など）を検出して取り除きます。

- 無音検出: `ffmpeg` の `silencedetect` フィルタ
- フィラーワード検出: Google Cloud Speech-to-Text（単語単位のタイムスタンプ）
- Resolveへの反映: DaVinci Resolve Scripting API（Pythonスクリプト）

## 動作モード

### 1. ファイルモード（推奨・新規タイムライン作成）

ディスク上の動画ファイルを渡すと、無音/フィラーを検出してカットした状態で、新しい（または現在の）タイムラインに順番に並べます。既存のプロジェクトの中身は変更しません。

```bash
python3 -m davinci_auto_cut.run --source-files interview.mp4 --filler-words --apply
```

### 2. タイムラインモード（既存のクリップをカット）

すでにタイムラインに乗っているクリップを対象に、無音/フィラー区間を検出して取り除きます。

```bash
python3 -m davinci_auto_cut.run --track 1 --apply
```

いずれのモードも `--apply` を付けない限り **ドライラン** です。ファイルモードでは検出結果をコンソールに表示するだけ、タイムラインモードではカット予定位置に赤いマーカーを打つだけで、実際の編集は行いません。内容を確認してから `--apply` を付けて再実行してください。

## セットアップ

1. DaVinci Resolve（Studio推奨。無料版でのスクリプティング可否はバージョンにより異なります）をインストールし、`Preferences > System > General` で外部スクリプティングを有効化します。
2. `ffmpeg` / `ffprobe` をインストールし、PATHに通します。
3. フィラーワード検出を使う場合:
   ```bash
   pip install -r requirements.txt
   ```
   Google Cloud のサービスアカウントキーを用意し、
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```
   を設定してください（Speech-to-Text APIが有効なプロジェクトのキー）。
4. Resolveの「Workspace > Scripts」メニューから起動したい場合:
   ```bash
   python3 install.py
   ```
   でランチャースクリプトを登録できます（Resolve再起動後にメニューに表示されます）。外部プロセスとして直接 `python3 -m davinci_auto_cut.run ...` を実行することも可能です。

## 主なオプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--source-files FILE...` | ファイルモードにする。省略時はタイムラインモード | - |
| `--track N` | 対象のビデオトラック番号（タイムラインモード） | `1` |
| `--apply` | 実際に編集を反映する（省略時はドライラン） | 無効 |
| `--no-silence` | 無音検出を無効化 | 有効 |
| `--silence-threshold-db` | 無音とみなす音量しきい値(dB) | `-35.0` |
| `--min-silence-duration` | 無音とみなす最小秒数 | `0.4` |
| `--filler-words` | フィラーワード検出を有効化（Google STT課金が発生します） | 無効 |
| `--language` | Google STTの言語コード | `ja-JP` |
| `--padding` | カット区間の前後に残す秒数（不自然な切れ方を防ぐ） | `0.08` |
| `--min-keep-duration` | これより短い「残す区間」は前後のカットに吸収する | `0.15` |

フィラーワードの単語リストは `davinci_auto_cut/config.py` の `DEFAULT_FILLER_WORDS_JA` / `DEFAULT_FILLER_WORDS_EN` で編集できます。

## 動作確認について（重要）

このツールはBlackmagicの公式スクリプティングAPIドキュメントに沿って実装していますが、**この開発環境にはDaVinci Resolve自体がインストールされておらず、実機での動作確認はできていません。** 特に以下は要注意です:

- `TimelineItem.GetLeftOffset()` をソースのin点として扱っている箇所（`timeline_items.py`）
- `MediaPool.AppendToTimeline()` がタイムラインをどこに作る/追記するかの挙動（`editor.py`, `media_import.py`）
- `Timeline.AddMarker()` のフレーム番号の基準点（`editor.py`）

一方で、カット区間のマージ・パディング処理・フィラーワードのマッチングロジック（`cutlist.py`, `filler_words.py`, `silence.py`のパース部分）は純粋なPythonロジックなので `tests/` でユニットテスト済みです（`pytest` で25件すべてパス）。

**推奨手順**: 本番プロジェクトの複製やテスト用の短い素材で、まずドライランと `--apply` を試し、想定通りに動くか確認してから本番データに使ってください。挙動が違う箇所があれば教えてください、一緒に直しましょう。

## テスト実行

```bash
pip install pytest
pytest tests/ -v
```

## 構成

```
davinci_auto_cut/
  config.py          設定(AutoCutConfig)
  resolve_connect.py Resolveへの接続
  timeline_items.py  タイムラインクリップの読み取り
  audio_extract.py   ffmpegによる音声抽出
  silence.py         無音検出(ffmpeg silencedetect)
  google_stt.py       Google Cloud Speech-to-Textでのフィラー検出
  filler_words.py    フィラーワード辞書とマッチング(純粋ロジック)
  ffprobe.py         動画の長さ/フレームレート取得
  cutlist.py         カット区間→残す区間の計算(純粋ロジック)
  editor.py           既存タイムラインクリップへのマーカー付与/カット適用
  media_import.py    ファイルのインポート+タイムライン構築
  run.py              エントリーポイント
install.py            Resolveの Scripts メニューへの登録
tests/                 純粋ロジックのユニットテスト
```
