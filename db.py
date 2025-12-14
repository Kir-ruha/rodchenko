import sqlite3
import os
import hashlib
import ipaddress
from typing import Dict, List, Optional, Tuple

from werkzeug.security import generate_password_hash, check_password_hash

DATABASE = 'data/auction.db'


def get_db():
    return sqlite3.connect(DATABASE)


def _table_has_column(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _ensure_created_at(conn, table, backfill_age_minutes: int = 0):
    c = conn.cursor()
    if not _table_has_column(c, table, "created_at"):
        c.execute(f"ALTER TABLE {table} ADD COLUMN created_at TEXT")
        # backfill rows so cleanup works even for legacy DB
        if backfill_age_minutes > 0:
            c.execute(
                f"UPDATE {table} SET created_at = datetime('now', ?)",
                (f"-{backfill_age_minutes} minutes",),
            )
        else:
            c.execute(f"UPDATE {table} SET created_at = datetime('now')")


def cleanup_expired_records(max_age_minutes=7):
    conn = get_db()
    c = conn.cursor()

    try:
        for table in ("users", "artworks", "transactions", "artwork_settings"):
            # Backfill to "old enough" so legacy rows get cleaned on the next cycle.
            _ensure_created_at(conn, table, backfill_age_minutes=max_age_minutes + 1)

        deletions = {}
        for table in ("artworks", "transactions", "artwork_settings", "users"):
            if _table_has_column(c, table, "created_at"):
                extra_where = "username != 'admin'" if table == "users" else None
                where = f"created_at < datetime('now', '-{max_age_minutes} minutes')"
                if extra_where:
                    where = f"({where}) AND ({extra_where})"
                c.execute(f"DELETE FROM {table} WHERE {where}")
                deletions[table] = c.rowcount

        # Cleanup dangling settings
        c.execute(
            "DELETE FROM artwork_settings WHERE artwork_id NOT IN (SELECT id FROM artworks)"
        )
        deleted_settings = c.rowcount

        conn.commit()
        return {
            "artworks": deletions.get("artworks", 0),
            "transactions": deletions.get("transactions", 0),
            "artwork_settings": deletions.get("artwork_settings", 0)
            + deleted_settings,
            "users": deletions.get("users", 0),
        }
    finally:
        conn.close()


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance INTEGER DEFAULT 1000
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS artworks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            data TEXT NOT NULL,
            price INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            is_private INTEGER DEFAULT 0,
            signature TEXT,
            created_at TEXT,
            FOREIGN KEY (owner_id) REFERENCES users(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            artwork_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            created_at TEXT,
            FOREIGN KEY (buyer_id) REFERENCES users(id),
            FOREIGN KEY (seller_id) REFERENCES users(id),
            FOREIGN KEY (artwork_id) REFERENCES artworks(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS artwork_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artwork_id INTEGER NOT NULL,
            settings_data TEXT,
            created_at TEXT,
            FOREIGN KEY (artwork_id) REFERENCES artworks(id)
        )
        """
    )

    for table in ("users", "artworks", "transactions", "artwork_settings"):
        _ensure_created_at(conn, table)

    # Create admin with password from environment (or a random one if not provided).
    # This prevents a fixed known password in production / A&D.
    admin_pw = os.environ.get("ADMIN_PASSWORD")
    if admin_pw:
        admin_hash = generate_password_hash(admin_pw)
    else:
        # Random, effectively disabling unknown admin password
        admin_hash = generate_password_hash(os.urandom(24).hex())

    c.execute(
        "INSERT OR IGNORE INTO users (username, password, balance) VALUES (?, ?, ?)",
        ("admin", admin_hash, 999999),
    )

    conn.commit()
    conn.close()


def get_user_balance(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0


def fetch_recent_artworks_for_user(user_id: int, limit: int = 20) -> List[Dict]:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT a.id, a.title, a.data, a.price, a.owner_id, a.is_private, a.signature, a.created_at, u.username
            FROM artworks a
            JOIN users u ON a.owner_id = u.id
            WHERE a.owner_id = ?
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        artworks_data = c.fetchall()
        return [
            {
                "id": art[0],
                "title": art[1],
                "data": art[2],
                "price": art[3],
                "owner_id": art[4],
                "is_private": art[5],
                "signature": art[6] or "",
                "created_at": art[7],
                "owner_name": art[8],
            }
            for art in artworks_data
        ]
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """Authenticate user.
    Supports legacy md5 hashes (auto-upgrades to werkzeug hash on successful login).
    """
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT id, username, balance, password FROM users WHERE username = ?",
            (username,),
        )
        user = c.fetchone()
        if not user:
            return None

        user_id, uname, balance, stored = user

        ok = False
        if stored and ":" in stored:
            ok = check_password_hash(stored, password)
        else:
            legacy = hashlib.md5(password.encode()).hexdigest()
            ok = (stored == legacy)

            if ok:
                new_hash = generate_password_hash(password)
                c.execute("UPDATE users SET password = ? WHERE id = ?", (new_hash, user_id))
                conn.commit()

        if ok:
            return {"id": user_id, "username": uname, "balance": balance}
        return None
    finally:
        conn.close()


def user_exists(username: str) -> bool:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        )
        return c.fetchone() is not None
    finally:
        conn.close()


def create_user(username: str, password: str) -> Tuple[bool, Optional[int]]:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        if c.fetchone():
            return False, None

        pw_hash = generate_password_hash(password)
        c.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, pw_hash),
        )
        conn.commit()
        return True, c.lastrowid
    finally:
        conn.close()


def create_artwork_record(
    owner_id: int,
    title: str,
    data: str,
    price: int,
    is_private: int,
    signature: str,
    settings_data: Optional[str] = None,
    created_at: Optional[str] = None,
) -> int:
    conn = get_db()
    c = conn.cursor()
    try:
        if created_at:
            c.execute(
                """
                INSERT INTO artworks (title, data, price, owner_id, is_private, signature, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, data, price, owner_id, is_private, signature, created_at),
            )
        else:
            c.execute(
                """
                INSERT INTO artworks (title, data, price, owner_id, is_private, signature, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (title, data, price, owner_id, is_private, signature),
            )
        artwork_id = c.lastrowid

        if settings_data is not None:
            c.execute(
                """
                INSERT INTO artwork_settings (artwork_id, settings_data, created_at)
                VALUES (?, ?, datetime('now'))
                """,
                (artwork_id, settings_data),
            )

        conn.commit()
        return artwork_id
    finally:
        conn.close()


def fetch_artwork_by_id(artwork_id: int) -> Optional[Dict]:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT a.id, a.title, a.data, a.price, a.owner_id, a.is_private, a.signature, a.created_at, u.username
            FROM artworks a
            JOIN users u ON a.owner_id = u.id
            WHERE a.id = ?
            """,
            (artwork_id,),
        )
        art = c.fetchone()
        if not art:
            return None
        return {
            "id": art[0],
            "title": art[1],
            "data": art[2],
            "price": art[3],
            "owner_id": art[4],
            "is_private": art[5],
            "signature": art[6] or "",
            "created_at": art[7],
            "owner_name": art[8],
        }
    finally:
        conn.close()


def update_artwork(
    artwork_id: int,
    title: str,
    data: str,
    price: int,
    is_private: int,
    signature: str,
) -> bool:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE artworks
            SET title = ?, data = ?, price = ?, is_private = ?, signature = ?
            WHERE id = ?
            """,
            (title, data, price, is_private, signature, artwork_id),
        )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def delete_artwork(artwork_id: int, owner_id: int) -> bool:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM artworks WHERE id = ? AND owner_id = ?", (artwork_id, owner_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def purchase_artwork(buyer_id: int, artwork_id: int) -> Tuple[bool, str]:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT id, owner_id, price FROM artworks WHERE id = ?", (artwork_id,))
        artwork = c.fetchone()
        if not artwork:
            return False, "Artwork not found"

        _, seller_id, price = artwork
        if seller_id == buyer_id:
            return False, "You cannot buy your own artwork"

        c.execute("SELECT balance FROM users WHERE id = ?", (buyer_id,))
        buyer_balance = c.fetchone()
        if not buyer_balance or buyer_balance[0] < price:
            return False, "Insufficient balance"

        c.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (price, buyer_id))
        c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (price, seller_id))
        c.execute("UPDATE artworks SET owner_id = ? WHERE id = ?", (buyer_id, artwork_id))

        c.execute(
            """
            INSERT INTO transactions (buyer_id, seller_id, artwork_id, amount, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (buyer_id, seller_id, artwork_id, price),
        )

        conn.commit()
        return True, "Purchase successful"
    finally:
        conn.close()


def fetch_transactions_for_user(user_id: int) -> List[Dict]:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT t.id, t.buyer_id, t.seller_id, t.artwork_id, t.amount, t.created_at,
                   b.username, s.username, a.title
            FROM transactions t
            JOIN users b ON t.buyer_id = b.id
            JOIN users s ON t.seller_id = s.id
            JOIN artworks a ON t.artwork_id = a.id
            WHERE t.buyer_id = ? OR t.seller_id = ?
            ORDER BY t.created_at DESC
            """,
            (user_id, user_id),
        )
        txs = c.fetchall()
        return [
            {
                "id": t[0],
                "buyer_id": t[1],
                "seller_id": t[2],
                "artwork_id": t[3],
                "amount": t[4],
                "created_at": t[5],
                "buyer_name": t[6],
                "seller_name": t[7],
                "artwork_title": t[8],
            }
            for t in txs
        ]
    finally:
        conn.close()


def save_artwork_settings(artwork_id: int, settings_data: str) -> bool:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM artwork_settings WHERE artwork_id = ?", (artwork_id,))
        c.execute(
            """
            INSERT INTO artwork_settings (artwork_id, settings_data, created_at)
            VALUES (?, ?, datetime('now'))
            """,
            (artwork_id, settings_data),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_artwork_settings(artwork_id: int) -> Optional[str]:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT settings_data FROM artwork_settings WHERE artwork_id = ?",
            (artwork_id,),
        )
        row = c.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def list_public_artworks(limit: int = 50) -> List[Dict]:
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT a.id, a.title, a.data, a.price, a.owner_id, a.is_private, a.signature, a.created_at, u.username
            FROM artworks a
            JOIN users u ON a.owner_id = u.id
            WHERE a.is_private = 0
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = c.fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "data": r[2],
                "price": r[3],
                "owner_id": r[4],
                "is_private": r[5],
                "signature": r[6] or "",
                "created_at": r[7],
                "owner_name": r[8],
            }
            for r in rows
        ]
    finally:
        conn.close()


def search_artworks(query: str) -> List[Dict]:
    conn = get_db()
    c = conn.cursor()
    try:
        q = f"%{query}%"
        c.execute(
            "SELECT * FROM artworks WHERE title LIKE ? OR data LIKE ?",
            (q, q),
        )
        results_data = c.fetchall()
        results = [
            {
                "id": art[0],
                "title": art[1],
                "data": art[2],
                "price": art[3],
                "owner_id": art[4],
                "is_private": art[5],
                "signature": art[6] or "",
                "created_at": art[7],
            }
            for art in results_data
        ]
        return results
    finally:
        conn.close()


def check_connect(remote_addr: str) -> Dict:
    """
    Used by /healthcheck.
    If request is from loopback, may return recent records.
    """
    conn = get_db()
    c = conn.cursor()
    try:
        ip = ipaddress.ip_address(remote_addr)
        if not ip.is_loopback:
            return {"status": "ok"}

        recent = {}
        for table in ("users", "artworks", "transactions", "artwork_settings"):
            if _table_has_column(c, table, "created_at"):
                c.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE created_at > datetime('now', '-5 minutes')"
                )
                recent[table] = c.fetchone()[0]
            else:
                recent[table] = 0

        return {"status": "ok", "recent": recent}
    finally:
        conn.close()
