import aiosqlite

DB_PATH = "starzo.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                order_type TEXT NOT NULL,
                amount TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT DEFAULT 'WAITING_PAYMENT',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def create_order(
    telegram_id: int,
    username: str,
    order_type: str,
    amount: str,
    price: float
):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO orders
            (telegram_id, username, order_type, amount, price)
            VALUES (?, ?, ?, ?, ?)
        """, (
            telegram_id,
            username,
            order_type,
            amount,
            price
        ))

        await db.commit()
        return cursor.lastrowid


async def get_user_orders(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, order_type, amount, price, status, created_at
            FROM orders
            WHERE telegram_id = ?
            ORDER BY id DESC
        """, (telegram_id,))

        return await cursor.fetchall()


async def get_pending_orders():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT
                id,
                telegram_id,
                username,
                order_type,
                amount,
                price,
                status,
                created_at
            FROM orders
            WHERE status = 'WAITING_PAYMENT'
            ORDER BY id ASC
        """)

        return await cursor.fetchall()


async def set_order_status(order_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE orders
            SET status = ?
            WHERE id = ?
        """, (status, order_id))

        await db.commit()
