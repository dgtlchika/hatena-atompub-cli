#!/usr/bin/env python3
"""hatena-atompub-cli: はてなブログ AtomPub 投稿 CLI (WSSE 認証)

はてなブログへの記事投稿・更新・削除と、はてなフォトライフへの
画像アップロードをコマンドラインから行います。依存は Python 標準
ライブラリのみです。

Usage:
  hatena.py list
  hatena.py draft    <title> <body_file> [--image FILE ...]
  hatena.py post     <title> <body_file> [--image FILE ...]
  hatena.py posthtml <title> <body_file> [--image FILE ...]
  hatena.py postmd   <title> <body_file> [--image FILE ...]
  hatena.py update   <entry_id> <title> <body_file> [--type html|text|markdown] [--image FILE ...]
  hatena.py delete   <entry_id>
  hatena.py upload   <image_file> [--folder NAME] [--title TITLE]

設定は ~/.config/hatena-cli/config.toml から読みます
(リポジトリ内の config.example.toml を参照)。
環境変数 HATENA_CONFIG / HATENA_ID / HATENA_BLOG_ID / HATENA_API_KEY /
HATENA_API_KEY_FILE でも上書きできます。
API キーがコマンドライン引数や出力に現れることはありません。

画像付き投稿:
  post 系コマンドに --image を付けると、画像をはてなフォトライフへ
  アップロードしてから投稿します。本文ファイル内に
  {{image:ファイル名}} というプレースホルダがある箇所へ画像が
  埋め込まれ、プレースホルダが無い画像は本文の末尾に追加されます。
  HTML 形式では <img> タグ、それ以外では [f:id:...:image] 記法で
  埋め込まれます。
"""
import argparse
import base64
import hashlib
import mimetypes
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

FOTOLIFE_POST_URI = "https://f.hatena.ne.jp/atom/post"
DEFAULT_CONFIG_PATH = Path("~/.config/hatena-cli/config.toml").expanduser()
DEFAULT_KEY_PATH = Path("~/.config/hatena-cli/api_key.txt").expanduser()

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, hatena_id: str, blog_id: str, api_key: str):
        self.hatena_id = hatena_id
        self.blog_id = blog_id
        self.api_key = api_key

    @property
    def blog_base(self) -> str:
        return f"https://blog.hatena.ne.jp/{self.hatena_id}/{self.blog_id}/atom"


def load_config(config_path: str | None = None) -> Config:
    path = Path(
        config_path
        or os.environ.get("HATENA_CONFIG")
        or DEFAULT_CONFIG_PATH
    ).expanduser()
    file_cfg: dict = {}
    if path.exists():
        with path.open("rb") as fh:
            file_cfg = tomllib.load(fh)

    hatena_id = os.environ.get("HATENA_ID") or file_cfg.get("hatena_id")
    blog_id = os.environ.get("HATENA_BLOG_ID") or file_cfg.get("blog_id")

    api_key = os.environ.get("HATENA_API_KEY")
    if not api_key:
        key_path = Path(
            os.environ.get("HATENA_API_KEY_FILE")
            or file_cfg.get("api_key_file")
            or DEFAULT_KEY_PATH
        ).expanduser()
        if key_path.exists():
            api_key = key_path.read_text(encoding="utf-8").strip()

    missing = []
    if not hatena_id:
        missing.append("hatena_id")
    if not blog_id:
        missing.append("blog_id")
    if not api_key:
        missing.append("api_key (HATENA_API_KEY or api_key_file)")
    if missing:
        raise ConfigError(
            "設定が不足しています: "
            + ", ".join(missing)
            + "\n~/.config/hatena-cli/config.toml を用意するか、環境変数で指定してください"
            "（config.example.toml 参照）。"
        )
    return Config(hatena_id=str(hatena_id), blog_id=str(blog_id), api_key=api_key)


def wsse_headers(cfg: Config) -> dict:
    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + cfg.api_key.encode()).digest()
    ).decode()
    wsse = (
        f'UsernameToken Username="{cfg.hatena_id}", PasswordDigest="{digest}", '
        f'Nonce="{base64.b64encode(nonce).decode()}", Created="{created}"'
    )
    return {"X-WSSE": wsse, "Authorization": 'WSSE profile="UsernameToken"'}


def http_request(req: urllib.request.Request) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"error: HTTP {exc.code}\n{body[:500]}", file=sys.stderr)
        raise SystemExit(1) from exc


# ---------------------------------------------------------------- blog entries

def list_entries(cfg: Config) -> int:
    req = urllib.request.Request(f"{cfg.blog_base}/entry", headers=wsse_headers(cfg))
    _, _, body = http_request(req)
    root = ET.fromstring(body)
    entries = root.findall("atom:entry", ATOM_NS)
    print(f"entries: {len(entries)}")
    for entry in entries:
        title = entry.findtext("atom:title", default="", namespaces=ATOM_NS)
        print(f"- {title}")
    return 0


def build_entry_xml(title: str, content: str, draft: bool, content_type: str) -> bytes:
    draft_xml = (
        "<app:control><app:draft>yes</app:draft></app:control>" if draft else ""
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<entry xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:app="http://www.w3.org/2007/app">'
        f"<title>{escape(title)}</title>"
        f'<content type="{content_type}">{escape(content)}</content>'
        f"{draft_xml}"
        "</entry>"
    ).encode("utf-8")


def print_entry_result(status: int, body: bytes) -> None:
    print(f"status: {status}")
    root = ET.fromstring(body)
    for link in root.findall("atom:link", ATOM_NS):
        rel = link.get("rel")
        href = link.get("href") or ""
        if rel == "alternate":
            print(f"url: {href}")
        elif rel == "edit":
            print(f"entry_id: {href.rstrip('/').rsplit('/', 1)[-1]}")


def post_entry(
    cfg: Config,
    title: str,
    body_file: str,
    draft: bool,
    content_type: str,
    image_files: list[str],
) -> int:
    content = Path(body_file).read_text(encoding="utf-8")
    content = embed_images(cfg, content, image_files, content_type)
    entry_xml = build_entry_xml(title, content, draft, content_type)
    headers = wsse_headers(cfg)
    headers["Content-Type"] = "application/atom+xml;type=entry"
    req = urllib.request.Request(
        f"{cfg.blog_base}/entry", data=entry_xml, headers=headers, method="POST"
    )
    status, _, body = http_request(req)
    print_entry_result(status, body)
    return 0


def update_entry(
    cfg: Config,
    entry_id: str,
    title: str,
    body_file: str,
    content_type: str,
    image_files: list[str],
) -> int:
    content = Path(body_file).read_text(encoding="utf-8")
    content = embed_images(cfg, content, image_files, content_type)
    entry_xml = build_entry_xml(title, content, False, content_type)
    headers = wsse_headers(cfg)
    headers["Content-Type"] = "application/atom+xml;type=entry"
    req = urllib.request.Request(
        f"{cfg.blog_base}/entry/{entry_id}", data=entry_xml, headers=headers, method="PUT"
    )
    status, _, _ = http_request(req)
    print(f"status: {status}")
    return 0


def delete_entry(cfg: Config, entry_id: str) -> int:
    req = urllib.request.Request(
        f"{cfg.blog_base}/entry/{entry_id}", headers=wsse_headers(cfg), method="DELETE"
    )
    status, _, _ = http_request(req)
    print(f"status: {status}")
    return 0


# ---------------------------------------------------------------- fotolife

def detect_image_type(data: bytes, filename: str) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    guessed, _ = mimetypes.guess_type(filename)
    if guessed in ("image/jpeg", "image/png", "image/gif"):
        return guessed
    raise ValueError(f"対応していない画像形式です: {filename} (jpeg/png/gif のみ対応)")


def upload_image(
    cfg: Config, image_file: str, folder: str | None = None, title: str | None = None
) -> dict:
    """はてなフォトライフ AtomAPI (PostURI) へ画像をアップロードする。

    公式仕様: https://developer.hatena.ne.jp/ja/documents/fotolife/apis/atom
    戻り値: {"imageurl": ..., "syntax": "[f:id:...:image]", "edit_uri": ...}
    """
    path = Path(image_file)
    data = path.read_bytes()
    mime = detect_image_type(data, path.name)
    b64 = base64.b64encode(data).decode()
    subject_xml = (
        f"<dc:subject>{escape(folder)}</dc:subject>" if folder else ""
    )
    entry_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<entry xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<title>{escape(title or path.name)}</title>"
        f'<content mode="base64" type="{mime}">{b64}</content>'
        f"{subject_xml}"
        "</entry>"
    ).encode("utf-8")
    headers = wsse_headers(cfg)
    headers["Content-Type"] = "application/atom+xml"
    req = urllib.request.Request(
        FOTOLIFE_POST_URI, data=entry_xml, headers=headers, method="POST"
    )
    status, resp_headers, body = http_request(req)
    text = body.decode("utf-8", errors="replace")
    url_match = re.search(r"<hatena:imageurl>([^<]+)</hatena:imageurl>", text)
    syntax_match = re.search(r"<hatena:syntax>([^<]+)</hatena:syntax>", text)
    if status != 201 or not url_match or not syntax_match:
        print(f"error: フォトライフの応答を解釈できませんでした (status {status})", file=sys.stderr)
        print(text[:500], file=sys.stderr)
        raise SystemExit(1)
    return {
        "imageurl": url_match.group(1),
        "syntax": f"[{syntax_match.group(1)}]",
        "edit_uri": resp_headers.get("Location", ""),
    }


def embed_images(
    cfg: Config, content: str, image_files: list[str], content_type: str
) -> str:
    for image_file in image_files:
        result = upload_image(cfg, image_file)
        name = Path(image_file).name
        if content_type == "text/html":
            replacement = f'<img src="{result["imageurl"]}" alt="{escape(name, quote=True)}">'
        else:
            replacement = result["syntax"]
        placeholder = "{{image:" + name + "}}"
        if placeholder in content:
            content = content.replace(placeholder, replacement)
        else:
            if content_type == "text/html":
                content += f"\n<p>{replacement}</p>\n"
            else:
                content += f"\n{replacement}\n"
            print(f"note: {name} のプレースホルダが無いため末尾に追加しました", file=sys.stderr)
        print(f"uploaded: {name} -> {result['imageurl']}", file=sys.stderr)
    return content


def cmd_upload(cfg: Config, image_file: str, folder: str | None, title: str | None) -> int:
    result = upload_image(cfg, image_file, folder=folder, title=title)
    print(f"imageurl: {result['imageurl']}")
    print(f"syntax: {result['syntax']}")
    if result["edit_uri"]:
        print(f"edit_uri: {result['edit_uri']}")
    return 0


# ---------------------------------------------------------------- CLI

CONTENT_TYPES = {"text": "text/plain", "html": "text/html", "markdown": "text/x-markdown"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hatena.py",
        description="はてなブログ AtomPub 投稿 CLI (WSSE 認証)",
    )
    parser.add_argument("--config", help="設定ファイルのパス (既定: ~/.config/hatena-cli/config.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="記事一覧を表示")

    for name, ctype, draft in (
        ("draft", "text/plain", True),
        ("post", "text/plain", False),
        ("posthtml", "text/html", False),
        ("postmd", "text/x-markdown", False),
    ):
        p = sub.add_parser(name, help=f"記事を投稿 ({name})")
        p.add_argument("title")
        p.add_argument("body_file")
        p.add_argument("--image", action="append", default=[], metavar="FILE",
                       help="本文に埋め込む画像 (複数指定可)")
        p.set_defaults(content_type=ctype, draft=draft)

    p_update = sub.add_parser("update", help="記事を更新")
    p_update.add_argument("entry_id")
    p_update.add_argument("title")
    p_update.add_argument("body_file")
    p_update.add_argument("--type", choices=list(CONTENT_TYPES), default="html",
                          dest="type_name")
    p_update.add_argument("--image", action="append", default=[], metavar="FILE")

    p_delete = sub.add_parser("delete", help="記事を削除")
    p_delete.add_argument("entry_id")

    p_upload = sub.add_parser("upload", help="はてなフォトライフへ画像をアップロード")
    p_upload.add_argument("image_file")
    p_upload.add_argument("--folder", help="アップロード先フォルダ名")
    p_upload.add_argument("--title", help="写真のタイトル")

    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "list":
        return list_entries(cfg)
    if args.command in ("draft", "post", "posthtml", "postmd"):
        return post_entry(cfg, args.title, args.body_file, args.draft,
                          args.content_type, args.image)
    if args.command == "update":
        return update_entry(cfg, args.entry_id, args.title, args.body_file,
                            CONTENT_TYPES[args.type_name], args.image)
    if args.command == "delete":
        return delete_entry(cfg, args.entry_id)
    if args.command == "upload":
        return cmd_upload(cfg, args.image_file, args.folder, args.title)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
