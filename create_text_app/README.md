# Create Text（自動文字起こし／手動音声入力）

動画・音声ファイルを読み込んでローカルで文字起こしできるデスクトップGUI
アプリ。黒×紫のダークテーマ（Auto Cutと共通、customtkinter製）。上部の
トグルで2つのモードを切り替えられる。

音声認識は [faster-whisper](https://github.com/SYSTRAN/faster-whisper) による
ローカルWhisperを使用。クラウドAPIには一切送信しない。モデルの重みは初回の
み Hugging Face Hub からダウンロードされ（要ネット接続）、以降はオフラインで
動く。

## 自動文字起こしモード

- 動画・音声ファイルを読み込んで、ファイル全体を一括で文字起こし
- 言語: 自動検出 / 日本語 / English
- モデルサイズ: `tiny` / `base` / `small` / `medium` / `large-v3`
  （精度と速度のトレードオフ。数値が大きいほど高精度だが遅い・メモリを食う）
- 文字起こし結果をセグメント単位（開始〜終了時刻＋テキスト）の一覧で表示。
  各行のテキストはその場で編集可能。「✕」ボタンでその行を削除（書き出しから除外）
- 書き出し: **SRT**（字幕ファイル、必須）、TXT（タイムスタンプなしのプレーン
  テキスト）、VTT（Web字幕）
- 動画プレビューはなし（あくまで字幕テキストの修正をしやすくすることが目的、
  重くならないように）

## 手動（音声入力）モード

Whisperによる自動書き起こしの代わりに、動画を見ながらユーザー自身がマイクに
喋って字幕を作るモード。セグメントの長さを自動任せにせず、好きな長さ・
タイミングで区切りたい場合向け。

1. 動画ファイルを読み込む（プレビュー用に、フレーム単位でスクラブできる
   簡易プレビューが表示される。リアルタイム再生ではなく、スクラブ位置の
   静止フレームを都度取得する方式）
2. スライダーで動画上の位置をスクラブし、「現在位置をIN」「現在位置をOUT」
   でセグメントの開始・終了を指定 →「+ セグメント追加」で確定
3. 各セグメント行の🎤ボタンで録音開始・もう一度押して録音終了。停止すると
   自動でその区間の音声だけをWhisperに渡して文字起こしし、テキスト欄に反映
   （区間の長さ・タイミングはこの時点で確定済みなので、テキストだけが
   後から埋まる形）
4. 開始・終了時刻、テキストはあとから直接編集可能。「▶」で該当セグメントの
   開始位置にプレビューをジャンプ、「✕」で削除
5. 書き出し:
   - **SRT**: 字幕ファイルとしてそのまま使える
   - **XML**（FCP7 XML v5）: 読み込んだ動画をそのまま乗せた1本のクリップに、
     セグメントごとの**シーケンスマーカー**（名前・コメントに字幕テキスト）
     を打った状態で書き出す。DaVinci Resolveにインポートすると、タイムライン
     上にマーカーとしてキャプションの位置とテキストが並ぶので、そこから
     字幕やテロップに仕立てやすい

マイク録音は [sounddevice](https://python-sounddevice.readthedocs.io/)
（PortAudio）を使用。動画プレビューのフレーム取得はffmpegで都度1枚抜き出す
方式なので、動画自体の再生・音声再生はできない（あくまで位置確認用）。

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
   （手動モードのマイク録音に使う `sounddevice` はPyPIのwheelにPortAudioが
   同梱されているので、追加のシステムインストールは不要）

## 起動

```bash
python3 -m create_text_app
```

上部のトグルで「自動文字起こし」「手動（音声入力）」を切り替える。

## アプリ化（.app として配布）

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --name "Create Text" --windowed \
  --collect-all customtkinter \
  --collect-data faster_whisper \
  --collect-all sounddevice \
  run_create_text.py
```

`--collect-data faster_whisper` は必須: faster-whisperが内部で使う音声区間
検出（VAD）用のonnxモデルファイルは、PyInstallerの依存解析だけでは自動的に
バンドルされず、これを付けないと実機で
`onnxruntime.capi.onnxruntime_pybind11_state.NoSuchFile` エラーになる。
同様に `--collect-all sounddevice` もPortAudioのバイナリを確実に含めるため
に付けている。

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
  subtitles.py          SRT/VTT/TXT書き出し（純粋ロジック、両モード共通）
  transcribe_engine.py  自動モード: faster-whisperのラッパー（音声抽出→文字起こし）
  whisper_model.py       WhisperModelのキャッシュ（モデルサイズごとに使い回す）
  frame_extract.py       手動モード: ffmpegで指定時刻のフレームを1枚抜き出す
  mic_recorder.py         手動モード: sounddeviceでマイク録音してWAVに書き出す
  manual_transcribe.py    手動モード: 録音した短いWAVクリップ1本を文字起こし
  fcp7_markers.py         手動モード: セグメントをFCP7 XML（シーケンスマーカー）に書き出す
  gui.py                 customtkinter製GUI（自動/手動モードの切り替え含む）
  __main__.py             `python -m create_text_app` のエントリーポイント
```

`davinci_auto_cut.audio_extract` / `davinci_auto_cut.ffprobe` /
`davinci_auto_cut.ffmpeg_locate`（ffmpeg/ffprobeを叩くだけの純粋なロジック）、
`silence_cut_app.theme`（配色パレット）、
`silence_cut_app.fcp7_xml`（FCP7 XMLの共通ヘルパー）を流用している。

## テスト

```bash
pip install pytest
pytest tests/ -v
```

`test_subtitles.py`・`test_frame_extract.py`・`test_fcp7_markers.py`・
`test_mic_recorder.py`・`test_manual_transcribe.py`・`test_whisper_model.py`
は純粋ロジック/モック済みのユニットテスト（`test_frame_extract.py`は実際に
ffmpegでテスト用の映像を生成して検証、それ以外は`faster_whisper`/
`sounddevice`をフェイクに差し替えてテスト）。`faster-whisper`による実際の
音声認識・モデルダウンロードはネットワークアクセスを伴うため自動テストの
対象外。GUI自体はXvfb上でのヘッドレス起動・スモークテスト（自動/手動モード
双方の一連の操作フロー）で確認済み。

## 既知の制限・未検証点

- **実機での文字起こし精度・速度は未検証**: 実際に音声ファイル/マイクを
  渡してモデルをダウンロード→文字起こしまで通しで動かした確認は開発環境の
  制約上できていない。エラーが出たら教えてほしい。
- **動画プレビューは静止フレームのみ**: リアルタイム再生・音声再生はできず、
  スクラブ位置の1フレームを都度ffmpegで抜き出して表示するだけ。
- **セグメントの分割・結合はできない**: 1行の削除はできるが、2行を1つに
  まとめたり、1行を2つに分割したりする機能はまだない。
- **手動モードのXML書き出しは「動画1本＋マーカー」形式**: DaVinci Resolveの
  テロップ/タイトルクリップとして直接読み込める形式（ジェネレータークリップ）
  ではなく、あくまでシーケンスマーカーとしてタイミング・テキストを渡す
  軽量な連携。
