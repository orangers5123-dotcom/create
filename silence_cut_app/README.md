# Auto Cut（無音自動カット）

動画を読み込んで無音区間を自動検出・カットし、結果を **FCP7 XML v5**（`.xml`）として
書き出すデスクトップGUIアプリ。フィラーワード検出はしない、無音カット専用。
黒×紫のダークテーマ（customtkinter製）。

DaVinci Resolveのプロジェクトを直接操作する `davinci_auto_cut`（リポジトリ直下）とは
別物。こちらはResolveのスクリプティングAPIを使わず、ffmpegで無音区間を検出し、
どのNLE（Resolve / Premiere / Final Cut）にもXML経由で読み込める形で結果を出す。

## できること

- **通常モード**: 動画ファイル（複数可、指定順に並べる）または既存のFCP7 XML v5
  （単一トラックのラフタイムライン）を読み込み、無音区間をカットして新しいXMLを書き出す。
- **2カメ同期モード**: メイン（1カメ）とサブ（2カメ）の動画を読み込み、音声波形の
  相互相関でズレを検出→自動同期した上で、メインカメラの音声を基準に無音カット。
  同じタイミングのカットをサブカメラ側にも適用し、2video track（マルチカム用）の
  XMLを書き出す。
- **カット強度**:
  - ソフト（控えめ）: 6秒以上続く無音のみカット、余白多め
  - 標準: 3秒以上の無音をカット
  - ハード（強めに詰める）: 1秒程度の短い無音や少し小さい声も積極的にカット、余白少なめ
  - 具体的な数値は `intensity.py` の `INTENSITY_PRESETS` を参照・調整可能。

## セットアップ（Mac）

1. Python 3.10以降（[python.org](https://www.python.org/downloads/macos/) のインストーラー推奨。
   Tcl/Tkが同梱されるのでGUIがそのまま動く。Homebrewのpythonを使う場合は
   `brew install python-tk` も必要）
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
python3 -m silence_cut_app
```

GUIが開いたら、モード（通常 / 2カメ同期）・入力・カット強度・出力先を選んで
「無音カット開始」を押す。処理中の進捗と結果はログ欄に表示される。

## アプリ化（.app として配布）

macOS上でダブルクリック起動できる `.app` にまとめる方法は2通り用意している。

### PyInstaller（推奨）

```bash
./bundle_ffmpeg.sh   # ffmpeg/ffprobeを vendor/ffmpeg_bin/ にコピー（初回・更新時のみ）
pip install -r requirements.txt pyinstaller
pyinstaller --name "Auto Cut" --windowed \
  --collect-all customtkinter \
  --add-binary "vendor/ffmpeg_bin/ffmpeg:ffmpeg_bin" \
  --add-binary "vendor/ffmpeg_bin/ffprobe:ffmpeg_bin" \
  run_app.py
```

`--add-binary` でffmpeg/ffprobeをアプリ本体に同梱している。これにより、Finderから
起動した際にPATHが見えず`ffmpeg`が見つからないという問題が原理的に起きなくなる
（[`davinci_auto_cut/ffmpeg_locate.py`](../davinci_auto_cut/ffmpeg_locate.py)が、
まず同梱されたバイナリを優先して使う）。`bundle_ffmpeg.sh`を実行していない場合や
`vendor/ffmpeg_bin/`が無い場合は、`--add-binary`の行を省いてビルドしても動く
（その場合は従来どおりPATH頼みになる）。

`dist/Auto Cut.app` が生成される。numpy/scipy向けの専用フックが整備されているため、
`py2app` より依存関係の解決が安定している（後述の理由で `py2app` は現状動かないことがある）。

### py2app（既知の問題あり）

```bash
pip install -r requirements.txt py2app
python3 setup_mac_app.py py2app
```

**注意**: Python 3.14 + 最新版numpy/scipyの組み合わせでは、py2appの依存解析
（`modulegraph`、ASTを再帰的に辿る古い実装）がnumpyの複雑なimport構造を処理しきれず、
`sys.setrecursionlimit()` やスレッドのスタックサイズを増やしても
`RecursionError` で失敗することを確認している。動かない場合はPyInstallerを使ってほしい。

PyInstallerで`--add-binary`を使わない場合や、py2appでビルドする場合は
ffmpeg/ffprobeはバンドルされないので、実行するMacには別途インストールして
おく必要がある。

## 構成

```
silence_cut_app/
  intensity.py    カット強度プリセット（ソフト/標準/ハード）
  fcp7_xml.py     FCP7 XML v5の読み込み・書き出し（xmeml v5サブセット）
  sync.py         2カメの音声波形による自動同期（相互相関）
  cut_engine.py   全体の処理フロー（無音検出→キープ区間計算→XML書き出し）
  theme.py        配色パレット（黒×紫のダークテーマ）
  gui.py          customtkinter製GUI（アプリ名: Auto Cut）
  __main__.py     `python -m silence_cut_app` のエントリーポイント
```

`davinci_auto_cut` パッケージの `audio_extract.py` / `ffprobe.py` / `silence.py` /
`cutlist.py`（すべてffmpeg/ffprobeを叩くだけの純粋なロジック、Resolve依存なし）を
そのまま流用している。

## テスト

```bash
pip install pytest
pytest tests/ -v
```

`test_intensity.py` / `test_fcp7_xml.py` / `test_sync.py` は純粋ロジックのユニット
テスト。`test_cut_engine_integration.py` は実際にffmpegで無音+トーンのテスト用素材を
生成し、無音カット・2カメ同期の両方をエンドツーエンドで検証する（ffmpegがPATHに
なければ自動的にスキップされる）。

## 既知の制限・未検証点

- **書き出したXMLの実機インポートは未検証**: この開発環境にはDaVinci Resolve /
  Premiere Pro / Final Cut Pro が入っておらず、実際のアプリで読み込んで意図通りに
  タイムラインが構成されるかは確認できていない。XML自体は Final Cut Pro XML
  Interchange Format v5 の仕様に沿って生成しているが、各アプリ固有の癖（例:
  ファイルパスの解決方法、フレームレート・NTSC/ドロップフレームの扱い）で差異が
  出る可能性がある。小さいテスト素材で一度書き出し→インポートを試してから、
  本番素材に使ってほしい。
- **XML読み込みは「単一トラックのラフタイムライン」のみ対応**: 複数トラックや
  既にトランジション・エフェクトが入ったタイムラインは読み込めない（将来対応予定）。
- **2カメ同期は音声波形の相互相関のみ**: クラップボードやタイムコード同期は
  前提にしていない。両カメラの音声にある程度共通の音（環境音・会話など）が
  必要で、無音や全く違う音しか入っていない場合はズレの検出に失敗する。
- **フレームレートは動画ファイルの `r_frame_rate` を信頼**: 可変フレームレート
  (VFR) 素材では frame⇔秒 の変換がずれる可能性がある。
