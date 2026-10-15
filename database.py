import aiosqlite

DB_NAME = "starzo.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                order_type TEXT NOT NULL,
                amount TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'WAITING_PAYMENT',
                crypto_invoice_id TEXT,
                crypto_invoice_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Import existing customers into the broadcast audience without changing orders.
        await db.execute("""
            INSERT OR IGNORE INTO users (telegram_id, username, first_seen, last_seen)
            SELECT telegram_id, username, MIN(created_at), MAX(created_at)
            FROM orders GROUP BY telegram_id
        """)
        await db.commit()


async def register_user(telegram_id: int, username: str | None, first_name: str | None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, username, first_name, first_seen, last_seen)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_seen = CURRENT_TIMESTAMP
        """, (int(telegram_id), username, first_name))
        await db.commit()


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT telegram_id FROM users ORDER BY telegram_id")
        rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]


async def create_order(telegram_id: int, username: str, order_type: str, amount: str, price: float) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            INSERT INTO orders (telegram_id, username, order_type, amount, price, status)
            VALUES (?, ?, ?, ?, ?, 'WAITING_PAYMENT')
        """, (int(telegram_id), username, order_type, str(amount), float(price)))
        await db.commit()
        return int(cursor.lastrowid)


async def set_crypto_invoice(order_id: int, invoice_id: str, invoice_url: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE orders SET crypto_invoice_id = ?, crypto_invoice_url = ? WHERE id = ?",
            (str(invoice_id), invoice_url, int(order_id)),
        )
        await db.commit()


async def get_order(order_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT id, telegram_id, username, order_type, amount, price, status,
                   crypto_invoice_id, crypto_invoice_url, created_at
            FROM orders WHERE id = ?
        """, (int(order_id),))
        return await cursor.fetchone()


async def get_user_orders(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT id, order_type, amount, price, status, created_at
            FROM orders WHERE telegram_id = ? ORDER BY id DESC
        """, (int(telegram_id),))
        return await cursor.fetchall()


async def get_waiting_payment_orders():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT id, telegram_id, username, order_type, amount, price, status,
                   crypto_invoice_id, crypto_invoice_url, created_at
            FROM orders WHERE status = 'WAITING_PAYMENT' ORDER BY id ASC
        """)
        return await cursor.fetchall()


async def get_pending_admin_orders():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT id, telegram_id, username, order_type, amount, price, status,
                   crypto_invoice_id, crypto_invoice_url, created_at
            FROM orders WHERE status = 'PROCESSING' ORDER BY id ASC
        """)
        return await cursor.fetchall()


async def set_order_status(order_id: int, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, int(order_id)))
        await db.commit()
