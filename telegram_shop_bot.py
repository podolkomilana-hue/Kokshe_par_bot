"""
Telegram E‑commerce Bot (minimal, ready-to-run)

Features implemented in this single-file example:
- /start — welcome
- /catalog — list products (with pagination)
- View product details with inline buttons
- Add to cart, view cart (/cart), remove item
- Checkout (creates an "order" stored in SQLite; payment integration left as TODO)
- Admin commands: /admin_add (add product interactively), /admin_list_orders

Requirements:
- Python 3.10+
- python-telegram-bot>=20.0

Setup:
1. pip install python-telegram-bot==20.5
2. Set environment variable BOT_TOKEN with your bot token.
   e.g. export BOT_TOKEN="123456:ABC-..."
3. Run: python telegram_shop_bot.py

This is a simple reference implementation. Customize product images, payments, hosting (webhook), and security for production.
"""

import os
import logging
import sqlite3
from typing import List, Dict, Any
from telegram import __version__ as ptb_version
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# ------- Configuration -------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = set()  # put your Telegram user id(s) here or fill from env
if os.environ.get("ADMIN_ID"):
    try:
        ADMIN_IDS.add(int(os.environ.get("ADMIN_ID")))
    except:
        pass

DB_PATH = "shop.db"
PAGE_SIZE = 6

# ------- Logging -------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------- Database helpers -------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            price INTEGER NOT NULL,
            image TEXT
        );

        CREATE TABLE IF NOT EXISTS carts (
            user_id INTEGER,
            product_id INTEGER,
            qty INTEGER,
            PRIMARY KEY (user_id, product_id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            items TEXT, -- json: [{product_id, qty, price}],
            total INTEGER,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()


def db_get_products(page: int = 0) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, title, description, price, image FROM products ORDER BY id DESC LIMIT ? OFFSET ?", (PAGE_SIZE, PAGE_SIZE * page))
    rows = cur.fetchall()
    conn.close()
    return [dict(id=r[0], title=r[1], description=r[2], price=r[3], image=r[4]) for r in rows]


def db_get_product(pid: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, title, description, price, image FROM products WHERE id = ?", (pid,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return dict(id=r[0], title=r[1], description=r[2], price=r[3], image=r[4])


def db_add_product(title, description, price, image=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO products (title, description, price, image) VALUES (?, ?, ?, ?)", (title, description, price, image))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def db_add_to_cart(user_id: int, product_id: int, qty: int = 1):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT qty FROM carts WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    r = cur.fetchone()
    if r:
        cur.execute("UPDATE carts SET qty = qty + ? WHERE user_id = ? AND product_id = ?", (qty, user_id, product_id))
    else:
        cur.execute("INSERT INTO carts (user_id, product_id, qty) VALUES (?, ?, ?)", (user_id, product_id, qty))
    conn.commit()
    conn.close()


def db_get_cart(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT product_id, qty FROM carts WHERE user_id = ?", (user_id,))
    rows = cur.fetchall()
    conn.close()
    items = []
    total = 0
    for pid, qty in rows:
        p = db_get_product(pid)
        if not p:
            continue
        items.append({"product": p, "qty": qty})
        total += p['price'] * qty
    return items, total


def db_clear_cart(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM carts WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def db_create_order(user_id: int, items: List[Dict[str, Any]], total: int):
    import json
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (user_id, items, total) VALUES (?, ?, ?)", (user_id, json.dumps(items), total))
    conn.commit()
    oid = cur.lastrowid
    conn.close()
    return oid


def db_list_orders():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, items, total, status, created_at FROM orders ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

# ------- Bot handlers -------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = f"Привет, {user.first_name}! Добро пожаловать в магазин. Команды: /catalog, /cart"
    await update.message.reply_text(text)


async def catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = 0
    if context.args:
        try:
            page = int(context.args[0])
        except:
            page = 0
    products = db_get_products(page)
    if not products:
        await update.message.reply_text("Каталог пуст или нет товаров на этой странице.")
        return
    for p in products:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Посмотреть", callback_data=f"view_{p['id']}")]])
        text = f"*{p['title']}*\n{p['description'] or ''}\nЦена: {p['price']}"
        # try to send as photo if image url provided
        try:
            if p.get('image'):
                await update.message.reply_photo(photo=p['image'], caption=text, parse_mode='Markdown', reply_markup=kb)
            else:
                await update.message.reply_text(text, parse_mode='Markdown', reply_markup=kb)
        except Exception as e:
            logger.warning("Failed to send image: %s", e)
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=kb)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user_id = q.from_user.id
    if data.startswith('view_'):
        pid = int(data.split('_', 1)[1])
        p = db_get_product(pid)
        if not p:
            await q.edit_message_text('Товар не найден')
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('Добавить в корзину', callback_data=f'add_{pid}_1')],
            [InlineKeyboardButton('Назад к каталогу', callback_data='back_0')]
        ])
        text = f"*{p['title']}*\n{p['description'] or ''}\nЦена: {p['price']}"
        try:
            if p.get('image'):
                await q.message.reply_photo(photo=p['image'], caption=text, parse_mode='Markdown', reply_markup=kb)
            else:
                await q.message.reply_text(text, parse_mode='Markdown', reply_markup=kb)
        except Exception:
            await q.message.reply_text(text, parse_mode='Markdown', reply_markup=kb)
    elif data.startswith('add_'):
        # add_{pid}_{qty}
        _, pid_s, qty_s = data.split('_')
        pid = int(pid_s); qty = int(qty_s)
        db_add_to_cart(user_id, pid, qty)
        await q.answer(text='Добавлено в корзину', show_alert=False)
    elif data == 'back_0':
        # resend /catalog
        await catalog(update, context)
    elif data.startswith('remove_'):
        # remove_{pid}
        pid = int(data.split('_',1)[1])
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM carts WHERE user_id = ? AND product_id = ?", (user_id, pid))
        conn.commit(); conn.close()
        await q.answer('Удалено')
    else:
        await q.answer()


async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    items, total = db_get_cart(user.id)
    if not items:
        await update.message.reply_text('Ваша корзина пуста. Используйте /catalog чтобы добавить товары.')
        return
    lines = []
    kb_rows = []
    for it in items:
        p = it['product']
        qty = it['qty']
        lines.append(f"{p['title']} x{qty} — {p['price'] * qty}")
        kb_rows.append([InlineKeyboardButton(f"Удалить {p['title']}", callback_data=f"remove_{p['id']}")])
    lines.append(f"\nИтого: {total}")
    kb_rows.append([InlineKeyboardButton('Оформить заказ', callback_data='checkout_0')])
    await update.message.reply_text('\n'.join(lines), reply_markup=InlineKeyboardMarkup(kb_rows))


async def checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    items, total = db_get_cart(user.id)
    if not items:
        await q.edit_message_text('Корзина пуста')
        return
    # prepare order payload
    payload_items = []
    for it in items:
        payload_items.append({'product_id': it['product']['id'], 'title': it['product']['title'], 'qty': it['qty'], 'price': it['product']['price']})
    oid = db_create_order(user.id, payload_items, total)
    db_clear_cart(user.id)
    await q.edit_message_text(f'Заказ #{oid} создан. Сумма: {total}. Спасибо!')


# Admin commands
async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text('Доступ только для админов')
        return
    await update.message.reply_text('Отправьте данные товара в формате: Название | Описание | Цена | image_url(опционально)')
    context.user_data['admin_adding'] = True


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if context.user_data.get('admin_adding') and user.id in ADMIN_IDS:
        txt = update.message.text
        parts = [p.strip() for p in txt.split('|')]
        if len(parts) < 3:
            await update.message.reply_text('Неверный формат. Нужно: Название | Описание | Цена | image_url(опционально)')
            return
        title, desc, price = parts[0], parts[1], parts[2]
        image = parts[3] if len(parts) > 3 else None
        try:
            price_i = int(price)
        except:
            await update.message.reply_text('Цена должна быть целым числом (в копейках/тг/что вы используете)')
            return
        pid = db_add_product(title, desc, price_i, image)
        context.user_data['admin_adding'] = False
        await update.message.reply_text(f'Товар добавлен с id={pid}')
        return
    # fallback message
    await update.message.reply_text('Неизвестная команда. /catalog, /cart')


async def admin_list_orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text('Доступ только для админов')
        return
    rows = db_list_orders()
    if not rows:
        await update.message.reply_text('Заказов нет')
        return
    lines = []
    for r in rows[:20]:
        lines.append(f"#{r[0]} user:{r[1]} total:{r[3]} status:{r[4]} at:{r[5]}")
    await update.message.reply_text('\n'.join(lines))


# ------- Main -------
async def main():
    if not BOT_TOKEN:
        raise RuntimeError('Please set BOT_TOKEN environment variable')
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('catalog', catalog))
    app.add_handler(CommandHandler('cart', view_cart))
    app.add_handler(CommandHandler('admin_add', admin_add_start))
    app.add_handler(CommandHandler('admin_list_orders', admin_list_orders_cmd))

    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(CallbackQueryHandler(checkout_callback, pattern='^checkout_'))

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))

    logger.info('Bot starting (python-telegram-bot %s)', ptb_version)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    # run until Ctrl+C
    await app.wait_until_closed()


if __name__ == '__main__':
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print('Bot stopped')
