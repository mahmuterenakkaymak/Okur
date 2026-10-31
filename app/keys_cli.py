"""Worker key management from the terminal: add | list | revoke.

The plaintext key exists only in this process's stdout — the database holds
the SHA-256 hash — so `add` prints it exactly once, with a copy warning,
and no command can ever print it again. `list` shows identities only.

ASSUMPTION: PLAN.md names the file keys_cli.py, so the module path is
`python -m app.keys_cli` (the plan's `app.keys` shorthand has no module).
"""
from __future__ import annotations

import argparse
import sys

from app import auth, db


def _cmd_add(conn, worker: str) -> int:
    worker = worker.strip()
    if not worker:
        print("Hata: çalışan adı boş olamaz.", file=sys.stderr)
        return 1
    key_id, plaintext = auth.create_key(conn, worker)
    print(f"Anahtar #{key_id} oluşturuldu — çalışan: {worker}")
    print()
    print(plaintext)
    print()
    print(
        "UYARI: Bu anahtar yalnızca şimdi gösteriliyor; veritabanında sadece "
        "SHA-256\nhash'i duruyor, bir daha gösterilemeyecek. Şimdi kopyalayıp "
        "cihaza kaydedin."
    )
    return 0


def _cmd_list(conn) -> int:
    rows = conn.execute(
        "SELECT id, worker, created_at, revoked FROM api_keys ORDER BY id"
    ).fetchall()
    if not rows:
        print("Kayıtlı anahtar yok. Oluşturmak için: add <çalışan adı>")
        return 0
    print(f"{'ID':>3}  {'Çalışan':<20}  {'Oluşturulma':<24}  Durum")
    for row in rows:
        durum = "iptal" if row["revoked"] else "aktif"
        print(
            f"{row['id']:>3}  {row['worker']:<20}  {row['created_at']:<24}  {durum}"
        )
    print(f"\n{len(rows)} anahtar. Anahtarların kendisi gösterilmez (yalnızca hash saklanır).")
    return 0


def _cmd_revoke(conn, key_id: int) -> int:
    if auth.revoke_key(conn, key_id):
        print(f"Anahtar #{key_id} iptal edildi; bu anahtarla gelen istekler 401 alır.")
        return 0
    print(f"Hata: #{key_id} kayıtlı değil ya da zaten iptal edilmiş.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    # Windows pipes default to a code page without ş/ğ; keep output intact.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m app.keys_cli",
        description="Çalışan API anahtarlarını yönet (ekle / listele / iptal et).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    parser_add = sub.add_parser("add", help="yeni anahtar oluştur")
    parser_add.add_argument("worker", help="çalışan adı (ör. ayse)")
    sub.add_parser("list", help="anahtarları listele (anahtarlar gösterilmez)")
    parser_revoke = sub.add_parser("revoke", help="anahtarı iptal et")
    parser_revoke.add_argument("key_id", type=int, help="list çıktısındaki ID")
    args = parser.parse_args(argv)

    conn = db.connect()
    try:
        if args.command == "add":
            return _cmd_add(conn, args.worker)
        if args.command == "list":
            return _cmd_list(conn)
        return _cmd_revoke(conn, args.key_id)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
