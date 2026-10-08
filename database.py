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

        await db.commit()


async def create_order(
    telegram_id: int,
    username: str,
    order_type: str,
    amount: str,
    price: float,
):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            INSERT INTO orders (
                telegram_id,
                username,
                order_type,
                amount,
                price,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_id,
                username,
                order_type,
                amount,
                price,
                "WAITING_PAYMENT",
            ),
        )

        await db.commit()

        return cursor.lastrowid


async def set_crypto_invoice(
    order_id: int,
    invoice_id: str,
    invoice_url: str,
):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            UPDATE orders
            SET crypto_invoice_id = ?,
                crypto_invoice_url = ?
            WHERE id = ?
            """,
            (
                invoice_id,
                invoice_url,
                order_id,
            ),
        )

        await db.commit()


async def get_order(order_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT
                id,
                telegram_id,
                username,
                order_type,
                amount,
                price,
                status,
                crypto_invoice_id,
                crypto_invoice_url,
                created_at
            FROM orders
            WHERE id = ?
            """,
            (order_id,),
        )

        return await cursor.fetchone()


async def get_user_orders(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT
                id,
                order_type,
                amount,
                price,
                status,
                created_at
            FROM orders
            WHERE telegram_id = ?
            ORDER BY id DESC
            """,
            (telegram_id,),
        )

        return await cursor.fetchall()


async def get_waiting_payment_orders():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT
                id,
                telegram_id,
                username,
                order_type,
                amount,
                price,
                status,
                crypto_invoice_id,
                crypto_invoice_url,
                created_at
            FROM orders
            WHERE status = 'WAITING_PAYMENT'
              AND crypto_invoice_id IS NOT NULL
              AND crypto_invoice_id != ''
            ORDER BY id ASC
            """
        )

        return await cursor.fetchall()


async def get_pending_admin_orders():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT
                id,
                telegram_id,
                username,
                order_type,
                amount,
                price,
                status,
                crypto_invoice_id,
                crypto_invoice_url,
                created_at
            FROM orders
            WHERE status = 'PROCESSING'
            ORDER BY id ASC
            """
        )

        return await cursor.fetchall()


async def set_order_status(
    order_id: int,
    status: str,
):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            UPDATE orders
            SET status = ?
            WHERE id = ?
            """,
            (
                status,
                order_id,
            ),
        )

        await db.commit()
