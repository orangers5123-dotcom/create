# Create Text（自動文字起こし）

動画・音声ファイルを読み込んでローカルで文字起こしし、Vrewのように
テキストの一覧を見ながら修正できるデスクトップGUIアプリ。動画プレビューは
なし（あくまで字幕テキストの修正をしやすくすることが目的）。黒×紫のダーク
テーマ（Auto Cutと共通、customtkinter製）。

音声認識は [faster-whisper](https://github.com/SYSTRAN/faster-whisper) による
ローカルWhisperを使用。クラウドAPIには一切送信しない。モデルの重みは初回の
み Hugging Face Hub からダウンロードされ（要ネット接続）、以降はオフラインで
動く。

## できること

- 動画・音声ファイルを読み込んで文字起こし
- 言語: 自動検出 / 日本語 / English
- モデルサイズ: `tiny` / `base` / `small` / `medium` / `large-v3`
  （精度と速度のトレードオフ。数値が大きいほど高精度だが遅い・メモリを食う）
- 文字起こし結果をセグメント単位（開始〜終了時刻＋テキスト）の一覧で表示。
  各行のテキストはその場で編集可能。「✕」ボタンでその行を削除（書き出しから除外）
- 書き出し: **SRT**（字幕ファイル、必須）、TXT（タイムスタンプなしのプレーン
  テキスト）、VTT（Web字幕）

Vrewとの違い: 動画プレビューや「テキストを消すと動画もカットされる」機能は
ない（別アプリの Auto Cut がその役割）。あくまで文字起こし結果の確認・修正・
書き出しに特化している。

## セットアップ（Mac）

1. Python 3.10以降（python.org のインストーラー推奨。Homebrewのpythonを使う
   場合は `brew install python-tk` も必要）
2. ffmpeg / ffprobe をインストールしてPATHに通す:
   ```bash
   brew install ffmpeg
   ```
3. 依存パッケージをインストール:
   ```bash
   pip install -r requirements.txt
   ```

## 起動

```bash
python3 -m create_text_app
```

ファイルを選んで、言語・モデルサイズを選び、「文字起こし開始」を押す。
初回はモデルのダウンロードが走るので少し時間がかかる。完了すると結果が
一覧表示され、各行をクリックして修正できる。修正後、SRT/TXT/VTTのいずれか
のボタンで書き出す。

## アプリ化（.app として配布）

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --name "Create Text" --windowed --collect-all customtkinter run_create_text.py
```

`dist/Create Text.app` が生成される。アイコンを付ける場合は
[`make_icns.sh`](../make_icns.sh) でPNGから`.icns`を作り、
`--icon path/to/icon.icns` を追加する。

`py2app`は、依存関係が複雑な`faster-whisper`（ctranslate2 / onnxruntime /
tokenizers など）でも Auto Cut と同様の `RecursionError` に当たる可能性が
高いため、Create Text では検証しておらず推奨しない。PyInstallerを使うこと。

ffmpeg/ffprobeはバンドルされないので、実行するMacには別途インストールして
おく必要がある。

## 構成

```
create_text_app/
  subtitles.py         SRT/VTT/TXT書き出し（純粋ロジック）
  transcribe_engine.py faster-whisperのラッパー（音声抽出→文字起こし）
  gui.py                customtkinter製GUI
  __main__.py           `python -m create_text_app` のエントリーポイント
```

`davinci_auto_cut.audio_extract` / `davinci_auto_cut.ffprobe`
（ffmpeg/ffprobeを叩くだけの純粋なロジック）と `silence_cut_app.theme`
（配色パレット）を流用している。

## テスト

```bash
pip install pytest
pytest tests/ -v
```

`test_subtitles.py` はSRT/VTT/TXT書き出しの純粋ロジックのユニットテスト。
`faster-whisper`によるモデルダウンロード・実際の文字起こしはネットワーク
アクセスとモデルダウンロードを伴うため自動テストの対象外（この開発環境では
Hugging Face Hubへのアクセスが組織のネットワークポリシーでブロックされて
おり、確認できていない）。`faster_whisper.WhisperModel` / `model.transcribe()`
のAPI呼び出し自体はインストール済みライブラリのシグネチャと突き合わせて
確認済み。実際にMac上でモデルをダウンロードして文字起こしが動くかは、
お手元で試してみてほしい。

## 既知の制限・未検証点

- **実機での文字起こし精度・速度は未検証**: 上記の理由により、実際に音声
  ファイルを渡してモデルをダウンロード→文字起こしまで通しで動かした確認は
  できていない。エラーが出たら教えてほしい。
- **動画プレビューなし**: セグメントの時刻はWhisperの検出結果をそのまま
  表示するのみで、タイムコードの手動編集や動画との同期再生はできない。
- **セグメントの分割・結合はできない**: 1行の削除はできるが、2行を1つに
  まとめたり、1行を2つに分割したりする機能はまだない。
