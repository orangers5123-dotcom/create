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

1. 動画ファイルを読み込む。フレーム単位でスクラブできるプレビューと、
   音声の波形表示が出る。プレビュー下の「▶ 再生」ボタン（またはショート
   カットの `P`）で、音声つきでその場から普通に再生・一時停止もできる
2. セグメントを作る方法は2通り:
   - 手動: スライダーで動画上の位置をスクラブし、波形を見ながら
     「現在位置をIN」「現在位置をOUT」でセグメントの開始・終了を指定
     →「+ セグメント追加」で確定
   - 自動: 「セグメント自動生成」ボタンで、無音区間を検出してその隙間の
     発話区間をまとめてセグメント化（Auto Cutと同じ無音検出エンジンを
     流用。ソフト/標準/ハードの強度を選べる）。あとはテキストが空の
     セグメントが並ぶので、それぞれ🎤で喋るだけでよい
   - 既存の **SRT を読み込んで**続きから編集することもできる
     （「SRTを読み込む」）
3. 各セグメント行の🎤ボタンで録音開始・もう一度押して録音終了。停止すると
   自動でその区間の音声だけをWhisperに渡して文字起こしし、テキスト欄に反映
   （区間の長さ・タイミングはこの時点で確定済みなので、テキストだけが
   後から埋まる形）
4. 開始・終了時刻、テキストはあとから直接編集可能。
   - 「▶」で該当セグメントの開始位置にプレビューをジャンプし、**実際の音声を
     再生**（無音の静止画プレビューだけでは分かりにくいIN/OUTの当たりを耳で
     確認できる）
   - 「✂」で現在のプレビュー位置を境に1つのセグメントを2つに分割
   - 「🔗」で次のセグメントと結合（テキストも連結される）
   - 「✕」で削除（誤操作防止のため確認ダイアログが出る）
5. 書き出し:
   - **SRT**: 字幕ファイルとしてそのまま使える
   - **XML**（FCP7 XML v5）: 読み込んだ動画をそのまま乗せた1本のクリップに、
     セグメントごとの**シーケンスマーカー**（名前・コメントに字幕テキスト）
     を打った状態で書き出す。DaVinci Resolveにインポートすると、タイムライン
     上にマーカーとしてキャプションの位置とテキストが並ぶので、そこから
     字幕やテロップに仕立てやすい

マイク録音・音声再生は [sounddevice](https://python-sounddevice.readthedocs.io/)
（PortAudio）を使用。動画フレームの読み取りはOpenCV
（`opencv-python-headless`）で、1つのデコーダーを開いたまま使い回すことで
スクラブと「▶ 再生」の両方をまかなっている。再生中は壁時計で計算した位置に
毎回シーク（約100msごと）してプレビューを更新する方式なので、動画の
エンコード次第では滑らかさより正確な位置優先でややカクつくことがあるが、
音声自体は途切れず流れ続ける。

### プロジェクトの保存/読み込み

書き出し（SRT/XML）とは別に、作業途中の状態（動画パス＋セグメント一覧）を
JSONとして保存・復元できる。「プロジェクトを保存」でファイルに書き出し、
「プロジェクトを開く」で読み込む。動画ファイルが元の場所から動いていると
プレビューは出せないが、セグメント自体は読み込まれるので「参照...」で
動画を選び直せば続きから作業できる。

### キーボードショートカット

手動モードの画面上でテキスト欄にフォーカスしていない状態なら、以下が使える。

| キー | 動作 |
| --- | --- |
| `P` | 動画の再生/一時停止 |
| `I` | 現在位置をINに設定 |
| `O` | 現在位置をOUTに設定 |
| `Enter` | セグメントを追加 |
| `R` | 一番最後のセグメントの録音を開始/終了 |
| `Space` | 一番最後のセグメントを再生（プレビュー移動＋音声再生） |

`I`/`O`は動画を再生しながら押しても、その時点の再生位置がそのまま使われる
（一時停止してスクラブし直す必要はない）。

### 無音検出でセグメントを自動生成

`davinci_auto_cut`/Auto Cutと同じ無音検出（ffmpegの`silencedetect`）を使って、
発話区間をまとめてセグメント化できる。ソフト（控えめ）/標準/ハードの強度は
Auto Cutと同じプリセット。生成されるのは開始・終了時刻だけで、テキストは
空のまま並ぶので、そのあと各セグメントを🎤で埋めていく想定。既存のセグメント
がある状態で実行すると確認の上で置き換わる。

### セグメントの分割・結合

「✂」で1つのセグメントを現在のプレビュー位置で2つに分割（前半のテキストは
そのまま、後半は空になる）。「🔗」で次のセグメントと結合し、テキストは
スペースでつないで1つになる。

`IN → OUT → Enter → R → (喋る) → R` のように、マウスに触れずキーボードだけで
一連の作業ができる。

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
./bundle_ffmpeg.sh   # ffmpeg/ffprobeを vendor/ffmpeg_bin/ にコピー（初回・更新時のみ）
pip install -r requirements.txt pyinstaller
pyinstaller --name "Create Text" --windowed \
  --collect-all customtkinter \
  --collect-data faster_whisper \
  --collect-all sounddevice \
  --add-binary "vendor/ffmpeg_bin/ffmpeg:ffmpeg_bin" \
  --add-binary "vendor/ffmpeg_bin/ffprobe:ffmpeg_bin" \
  run_create_text.py
```

`--collect-data faster_whisper` は必須: faster-whisperが内部で使う音声区間
検出（VAD）用のonnxモデルファイルは、PyInstallerの依存解析だけでは自動的に
バンドルされず、これを付けないと実機で
`onnxruntime.capi.onnxruntime_pybind11_state.NoSuchFile` エラーになる。
同様に `--collect-all sounddevice` もPortAudioのバイナリを確実に含めるため
に付けている。

`--add-binary` の2行はffmpeg/ffprobeをアプリ本体に同梱するためのもの。これ
により、Finderから起動した際にPATHが見えず`ffmpeg`が見つからないという問題
が原理的に起きなくなる（[`davinci_auto_cut/ffmpeg_locate.py`](../davinci_auto_cut/ffmpeg_locate.py)
が、まず同梱されたバイナリを優先して使う）。`bundle_ffmpeg.sh`を実行して
いない場合や`vendor/ffmpeg_bin/`が無い場合は、この2行を省いてビルドしても
動く（その場合は従来どおりPATH頼みになる）。

手動モードの動画再生に使う`opencv-python-headless`は`pyinstaller-hooks-contrib`
に標準フックがあるため、上記コマンドに追加のフラグは不要（`--collect-all`
などを付けなくても自動的に同梱される）。もし実機で`cv2`関連の
`ModuleNotFoundError`が出た場合は`--collect-all cv2`を追加して再ビルドして
みてほしい。

`dist/Create Text.app` が生成される。アイコンを付ける場合は
[`make_icns.sh`](../make_icns.sh) でPNGから`.icns`を作り、
`--icon path/to/icon.icns` を追加する。

`py2app`は、依存関係が複雑な`faster-whisper`（ctranslate2 / onnxruntime /
tokenizers など）でも Auto Cut と同様の `RecursionError` に当たる可能性が
高いため、Create Text では検証しておらず推奨しない。PyInstallerを使うこと。

`--add-binary`を使わずにビルドした場合は、ffmpeg/ffprobeはバンドルされない
ので、実行するMacには別途インストールしておく必要がある。

## 構成

```
create_text_app/
  subtitles.py          SRT/VTT/TXT書き出し（純粋ロジック、両モード共通）
  transcribe_engine.py  自動モード: faster-whisperのラッパー（音声抽出→文字起こし）
  whisper_model.py       WhisperModelのキャッシュ（モデルサイズごとに使い回す）
  video_player.py         手動モード: OpenCVでの高速フレーム読み取り（スクラブ＋再生）
  frame_extract.py        単発フレーム抜き出し（ffmpegベース、現在GUIでは未使用の単体ユーティリティ）
  mic_recorder.py         手動モード: sounddeviceでマイク録音してWAVに書き出す
  audio_playback.py       手動モード: sounddeviceでセグメントの音声を再生
  manual_transcribe.py    手動モード: 録音した短いWAVクリップ1本を文字起こし
  manual_project.py       手動モード: 動画パス＋セグメント一覧をJSONで保存/読み込み
  waveform.py             手動モード: 音声波形（ピーク値）を計算しスクラブ下に表示
  fcp7_markers.py         手動モード: セグメントをFCP7 XML（シーケンスマーカー）に書き出す
  gui.py                 customtkinter製GUI（自動/手動モードの切り替え・キーボード
                          ショートカット含む）
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

`test_subtitles.py`（`parse_srt`のSRT読み込みを含む）・`test_frame_extract.py`・
`test_fcp7_markers.py`・`test_mic_recorder.py`・`test_manual_transcribe.py`・
`test_whisper_model.py`・`test_audio_playback.py`・`test_manual_project.py`・
`test_waveform.py`・`test_video_player.py`は純粋ロジック/モック済みの
ユニットテスト（`test_frame_extract.py`・`test_waveform.py`・
`test_video_player.py`は実際にffmpegでテスト用の映像を生成して検証、それ以外は
`faster_whisper`/`sounddevice`をフェイクに差し替えてテスト）。`faster-whisper`
による実際の音声認識・モデルダウンロードはネットワークアクセスを伴うため
自動テストの対象外。GUI自体はXvfb上でのヘッドレス起動・スモークテスト
（自動/手動モード双方の一連の操作フロー、キーボードショートカット、
プロジェクト保存/読み込み、セグメント音声再生、無音検出での自動セグメント
生成、波形表示、分割/結合、SRT読み込み、削除確認、**動画の実再生**（再生/
一時停止、再生中のI/OショートカットとスクラブでのAV停止）で確認済み。

## 既知の制限・未検証点

- **実機での文字起こし精度・速度は未検証**: 実際に音声ファイル/マイクを
  渡してモデルをダウンロード→文字起こしまで通しで動かした確認は開発環境の
  制約上できていない。エラーが出たら教えてほしい。
- **再生中のプレビュー更新は位置優先・約100ms間隔**: 音声は途切れず流れるが、
  映像は毎ティックごとにシークして描画する方式のため、GOPが長いエンコードの
  動画では滑らかさよりも正確な位置を優先してややカクつくことがある。
- **手動モードのXML書き出しは「動画1本＋マーカー」形式**: DaVinci Resolveの
  テロップ/タイトルクリップとして直接読み込める形式（ジェネレータークリップ）
  ではなく、あくまでシーケンスマーカーとしてタイミング・テキストを渡す
  軽量な連携。
- **アプリの署名/公証はしていない**: Apple Developer Program（有料）の登録が
  必要なため未対応。現状は`xattr -cr`でGatekeeperの隔離属性を外して起動する
  運用（READMEに記載の手順どおり）。
