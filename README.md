# hatena-atompub-cli

はてなブログへの記事投稿と、はてなフォトライフへの画像アップロードをコマンドラインから行う CLI です。
はてな公式の AtomPub API（ブログ）とフォトライフ AtomAPI を使い、認証は WSSE です。依存は **Python 標準ライブラリのみ** で、追加パッケージのインストールは不要です。

## できること

- 記事の一覧表示・投稿（下書き／公開）・更新・削除
- 投稿形式はプレーンテキスト / HTML / Markdown に対応
- **画像付き投稿**: 画像をはてなフォトライフへアップロードし、本文へ自動で埋め込んでから投稿できます
  - はてなブログの AtomPub 単体では画像を送れないため、管理画面でフォトライフへ手作業アップロード→記法をコピペ、という手順になりがちです。この CLI はフォトライフ AtomAPI を併用して、その往復をなくします
- 画像単体のアップロード（画像 URL と `[f:id:...:image]` 記法を出力）

作者自身がはてなブログの定期投稿で日常的に使っているツールの一般化版です。

## 動作環境

- Python 3.11 以上（設定ファイルの読み込みに標準ライブラリ `tomllib` を使用）
- はてなブログのアカウント（AtomPub が使えるブログ）

## セットアップ

### 1. APIキーを取得する

はてなブログの管理画面で確認できます。

1. 対象ブログの管理画面を開く
2. 「設定」→「詳細設定」
3. 「AtomPub」欄にある **APIキー** を控える

### 2. APIキーをファイルに保存する

APIキーをリポジトリや設定ファイルに直書きしないよう、キー専用ファイルに分けます。

```bash
mkdir -p ~/.config/hatena-cli
printf '%s' 'ここにAPIキー' > ~/.config/hatena-cli/api_key.txt
chmod 600 ~/.config/hatena-cli/api_key.txt
```

### 3. 設定ファイルを作る

```bash
cp config.example.toml ~/.config/hatena-cli/config.toml
```

`~/.config/hatena-cli/config.toml` を編集します。

```toml
hatena_id = "your-hatena-id"          # あなたのはてなID
blog_id = "your-blog.hatenablog.com"  # ブログのドメイン
api_key_file = "~/.config/hatena-cli/api_key.txt"
```

環境変数でも上書きできます（環境変数が優先）。

| 環境変数 | 内容 |
|---|---|
| `HATENA_CONFIG` | 設定ファイルのパス |
| `HATENA_ID` | はてなID |
| `HATENA_BLOG_ID` | ブログのドメイン |
| `HATENA_API_KEY` | APIキーそのもの（ファイルより優先） |
| `HATENA_API_KEY_FILE` | APIキーファイルのパス |

## 使い方

```bash
# 記事一覧
python3 hatena.py list

# 下書き投稿（プレーンテキスト）
python3 hatena.py draft "タイトル" body.txt

# 公開投稿（プレーンテキスト / HTML / Markdown）
python3 hatena.py post     "タイトル" body.txt
python3 hatena.py posthtml "タイトル" body.html
python3 hatena.py postmd   "タイトル" body.md

# 記事の更新（--type は html / text / markdown、既定は html）
python3 hatena.py update <entry_id> "タイトル" body.html

# 記事の削除
python3 hatena.py delete <entry_id>

# 画像だけをフォトライフへアップロード
python3 hatena.py upload photo.jpg
python3 hatena.py upload photo.jpg --folder "Blog Images" --title "説明文"
```

投稿に成功すると、記事の URL と `entry_id`（更新・削除に使う ID）が出力されます。

### 画像付き投稿

`--image` を付けると、投稿前に画像をフォトライフへアップロードし、本文へ埋め込みます。

```bash
python3 hatena.py posthtml "旅行記" body.html --image photo1.jpg --image photo2.png
```

本文ファイル内に `{{image:ファイル名}}` というプレースホルダを書いておくと、その位置に画像が入ります。

```html
<p>現地に着きました。</p>
{{image:photo1.jpg}}
<p>駅前の様子です。</p>
```

- HTML 形式では `<img src="...">` に置換されます
- それ以外の形式では `[f:id:あなたのはてなID:xxxxxxxx:image]` 記法に置換されます
- プレースホルダが無い画像は、本文の末尾に自動で追加されます

対応画像形式は JPEG / PNG / GIF です。

## セキュリティ上の注意

- **APIキーは絶対にリポジトリへコミットしないでください。** このリポジトリの `.gitignore` には `config.toml` と `api_key.txt` を入れてありますが、各自の環境でも十分に注意してください
- APIキーファイルのパーミッションは `600`（自分だけ読み取り可）を推奨します
- APIキーが漏れた場合は、はてなブログの詳細設定から再発行してください

## 仕様メモ

- ブログ側: [はてなブログAtomPub](https://developer.hatena.ne.jp/ja/documents/blog/apis/atom)（WSSE 認証）
- 画像側: [はてなフォトライフAtomAPI](https://developer.hatena.ne.jp/ja/documents/fotolife/apis/atom) の PostURI（`https://f.hatena.ne.jp/atom/post`）へ、画像を Base64 化して Atom エントリで POST します。レスポンスの `hatena:imageurl` と `hatena:syntax` を使って本文へ埋め込みます
- フォトライフ側のフォルダは `--folder` で指定できます（存在しないフォルダは自動作成されます）

## ライセンス

MIT License（[LICENSE](LICENSE) 参照）

---

## 作者について

このツールは「デジタル地下室」が、自分のブログ運用で実際に困ったことを解消するために作ったものです。同じ困りごとの解説や、作った過程は note に書いています。

- note（デジタル地下室）: https://note.com/sumaho_lab
- X: https://x.com/dgtl_chika
- GitHub: https://github.com/dgtlchika

不具合報告・要望は Issue へどうぞ。確認して対応します。
