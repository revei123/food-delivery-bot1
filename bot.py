import asyncio
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8294794426:AAGHNZ6_VnpXhHpK_wyjef-rfUCfRYH2kF8"
ADMINS = [878503862]  # Ваш ID

# Настройки доставки и скидок
MIN_ORDER_AMOUNT = 20
FREE_DELIVERY_AMOUNT = 200
DELIVERY_COST = 5
DISCOUNT_PERCENT = 10
RESTAURANT_PHONE = "+375 (29) 123-45-67"

# Временные интервалы доставки
DELIVERY_TIME_SLOTS = [
    "Как можно скорее",
    "12:00 - 14:00",
    "14:00 - 16:00", 
    "16:00 - 18:00",
    "18:00 - 20:00",
    "20:00 - 22:00"
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== СОСТОЯНИЯ FSM ==========
class OrderStates(StatesGroup):
    waiting_for_address = State()
    waiting_for_time = State()
    waiting_for_payment = State()
    confirming_order = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_dish_name = State()
    waiting_for_dish_description = State()
    waiting_for_dish_ingredients = State()
    waiting_for_dish_price = State()
    waiting_for_dish_category = State()

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_path="food_bot.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Инициализация базы данных"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            # Таблица категорий
            cur.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )''')
            
            # Таблица блюд
            cur.execute('''
            CREATE TABLE IF NOT EXISTS dishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT NOT NULL,
                description TEXT,
                ingredients TEXT,
                price INTEGER NOT NULL,
                photo_id TEXT,
                available BOOLEAN DEFAULT 1,
                FOREIGN KEY (category_id) REFERENCES categories (id)
            )''')
            
            # Таблица корзин
            cur.execute('''
            CREATE TABLE IF NOT EXISTS carts (
                user_id INTEGER PRIMARY KEY,
                cart_data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Таблица заказов
            cur.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                order_data TEXT,
                total_amount INTEGER,
                delivery_address TEXT,
                delivery_time TEXT,
                payment_method TEXT,
                status TEXT DEFAULT 'новый',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')

            # Таблица пользователей
            cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Проверяем, нужно ли заполнять данные
            cur.execute("SELECT COUNT(*) FROM categories")
            count = cur.fetchone()[0]
            if count == 0:
                self._seed_data(cur)
                logger.info("База данных заполнена начальными данными")
            else:
                logger.info("База данных уже содержит данные")
                
            # Проверяем и добавляем столбец available если его нет
            try:
                cur.execute("SELECT available FROM dishes LIMIT 1")
            except sqlite3.OperationalError:
                logger.info("Добавляем столбец available в таблицу dishes")
                cur.execute("ALTER TABLE dishes ADD COLUMN available BOOLEAN DEFAULT 1")
                
            # Проверяем и добавляем столбец payment_method если его нет
            try:
                cur.execute("SELECT payment_method FROM orders LIMIT 1")
            except sqlite3.OperationalError:
                logger.info("Добавляем столбец payment_method в таблицу orders")
                cur.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'наличными'")
                
            conn.commit()
            conn.close()
            logger.info("База данных инициализирована")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")

    def _seed_data(self, cur):
        """Заполнение начальными данными"""
        # Категории
        categories = [
            (1, "🥙 Шаурма"),
            (2, "🍔 Бургеры"),
            (3, "🍕 Закрытая пицца"),
            (4, "🔥 Шаурма на углях")
        ]
        cur.executemany("INSERT INTO categories (id, name) VALUES (?, ?)", categories)
        
        # Блюда
        dishes = [
            (1, "По-Питерски", "Классическая шаурма с курицей", "Куриное филе, капуста, морковь, огурец, кетчуп, майонез, лаваш", 140),
            (1, "Пшеничная", "С пшеничным лавашем", "Курица, овощи, сырный соус, пшеничный лаваш", 130),
            (1, "Сырная", "С двойным сыром", "Курица, сыр, томаты, салат, чесночный соус", 150),
            (2, "Бургер Кинг", "Большой и сытный", "Котлета из говядины, сыр, салат, томат, булочка", 180),
            (2, "Чизбургер", "С двойным сыром", "Говяжья котлета, сыр, огурец, кетчуп, булочка", 160),
            (3, "Классическая", "Классическая закрытая пицца", "Ветчина, сыр, томатный соус, тесто", 120),
            (3, "Куриная", "С курицей и грибами", "Курица, сыр, шампиньоны, соус, тесто", 130),
            (4, "Классическая", "Классическая на углях", "Курица на углях, овощи, чесночный соус", 140),
        ]
        
        for dish in dishes:
            cur.execute('''
            INSERT INTO dishes (category_id, name, description, ingredients, price, available)
            VALUES (?, ?, ?, ?, ?, 1)
            ''', dish)

    def get_categories(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM categories")
        categories = cur.fetchall()
        conn.close()
        return categories

    def get_dishes_by_category(self, category_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, name, price FROM dishes WHERE category_id = ? AND available = 1", (category_id,))
        dishes = cur.fetchall()
        conn.close()
        return dishes

    def get_dish_details(self, dish_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, category_id, name, description, ingredients, price, photo_id FROM dishes WHERE id = ?", (dish_id,))
        dish = cur.fetchone()
        conn.close()
        return dish

    def get_cart(self, user_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT cart_data FROM carts WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        if result and result[0]:
            return json.loads(result[0])
        return {"items": [], "total": 0}

    def update_cart(self, user_id: int, cart_data: Dict):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cart_json = json.dumps(cart_data)
        cur.execute('''
        INSERT OR REPLACE INTO carts (user_id, cart_data, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, cart_json))
        conn.commit()
        conn.close()

    def add_to_cart(self, user_id: int, dish_id: int, dish_name: str, price: int):
        cart = self.get_cart(user_id)
        for item in cart["items"]:
            if item["dish_id"] == dish_id:
                item["quantity"] += 1
                item["total"] = item["quantity"] * price
                break
        else:
            cart["items"].append({
                "dish_id": dish_id,
                "name": dish_name,
                "price": price,
                "quantity": 1,
                "total": price
            })
        cart["total"] = sum(item["total"] for item in cart["items"])
        self.update_cart(user_id, cart)
        return cart

    def update_cart_quantity(self, user_id: int, dish_id: int, change: int):
        cart = self.get_cart(user_id)
        for item in cart["items"]:
            if item["dish_id"] == dish_id:
                item["quantity"] += change
                if item["quantity"] <= 0:
                    cart["items"] = [i for i in cart["items"] if i["dish_id"] != dish_id]
                else:
                    item["total"] = item["quantity"] * item["price"]
                break
        
        cart["total"] = sum(item["total"] for item in cart["items"])
        self.update_cart(user_id, cart)
        return cart

    def remove_from_cart(self, user_id: int, dish_id: int):
        cart = self.get_cart(user_id)
        cart["items"] = [item for item in cart["items"] if item["dish_id"] != dish_id]
        cart["total"] = sum(item["total"] for item in cart["items"])
        self.update_cart(user_id, cart)
        return cart

    def clear_cart(self, user_id: int):
        self.update_cart(user_id, {"items": [], "total": 0})

    def create_order(self, user_id: int, user_name: str, order_data: Dict, address: str, delivery_time: str, payment_method: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        order_json = json.dumps(order_data)
        total_amount = order_data.get("total", 0)
        
        cur.execute('''
        INSERT INTO orders (user_id, user_name, order_data, total_amount, delivery_address, delivery_time, payment_method)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_name, order_json, total_amount, address, delivery_time, payment_method))
        order_id = cur.lastrowid
        conn.commit()
        conn.close()
        return order_id

    def get_orders(self, limit=10):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,))
        orders = cur.fetchall()
        conn.close()
        return orders

    def get_order_by_id(self, order_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        order = cur.fetchone()
        conn.close()
        return order

    def update_order_status(self, order_id: int, status: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        conn.commit()
        conn.close()

    def add_user(self, user_id: int, username: str, full_name: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('''
        INSERT OR REPLACE INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ''', (user_id, username, full_name))
        conn.commit()
        conn.close()

    def get_users_count(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        conn.close()
        return count

    def get_all_users(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return users

    def add_dish(self, category_id: int, name: str, description: str, ingredients: str, price: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('''
        INSERT INTO dishes (category_id, name, description, ingredients, price, available)
        VALUES (?, ?, ?, ?, ?, 1)
        ''', (category_id, name, description, ingredients, price))
        dish_id = cur.lastrowid
        conn.commit()
        conn.close()
        return dish_id

    def toggle_dish_availability(self, dish_id: int):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT available FROM dishes WHERE id = ?", (dish_id,))
        result = cur.fetchone()
        if result:
            new_status = not result[0]
            cur.execute("UPDATE dishes SET available = ? WHERE id = ?", (new_status, dish_id))
            conn.commit()
        conn.close()
        return new_status if result else None

# Создаем базу
db = Database()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def format_dish_details(dish_data):
    dish_id, category_id, name, description, ingredients, price, photo_id = dish_data
    text = f"""
🍽 <b>{name}</b>

📝 {description}

🧂 Состав: {ingredients}

💵 Цена: <b>{price} руб.</b>
"""
    return text.strip()

def calculate_delivery_cost(total_amount):
    return 0 if total_amount >= FREE_DELIVERY_AMOUNT else DELIVERY_COST

def calculate_discount(total_amount):
    discount_amount = (total_amount * DISCOUNT_PERCENT) / 100
    return discount_amount

def format_cart_text(cart):
    if not cart["items"]:
        return "🛒 Ваша корзина пуста"
    
    cart_text = "🛒 <b>Ваша корзина:</b>\n\n"
    total = cart["total"]
    
    for item in cart["items"]:
        cart_text += f"• {item['name']} - {item['quantity']} шт. × {item['price']} руб. = {item['total']} руб.\n"
    
    delivery_cost = calculate_delivery_cost(total)
    discount_amount = calculate_discount(total)
    final_total = total - discount_amount + delivery_cost
    
    cart_text += f"\n📦 Доставка: {delivery_cost} руб."
    cart_text += f"\n🎁 Скидка ({DISCOUNT_PERCENT}%): -{discount_amount:.0f} руб."
    cart_text += f"\n💵 <b>Итого: {final_total:.0f} руб.</b>"
    
    return cart_text

def format_order_confirmation(cart, address, delivery_time, payment_method):
    total = cart["total"]
    delivery_cost = calculate_delivery_cost(total)
    discount_amount = calculate_discount(total)
    final_total = total - discount_amount + delivery_cost
    
    text = f"""
✅ <b>Подтверждение заказа</b>

<b>Ваш заказ:</b>
"""
    for item in cart["items"]:
        text += f"• {item['name']} - {item['quantity']} шт. × {item['price']} руб.\n"
    
    text += f"""
<b>Детали доставки:</b>
📍 Адрес: {address}
⏰ Время: {delivery_time}
💳 Оплата: {payment_method}

<b>Итоговая сумма:</b>
Сумма заказа: {total} руб.
Доставка: {delivery_cost} руб.
Скидка: -{discount_amount:.0f} руб.
<b>Итого к оплате: {final_total:.0f} руб.</b>
"""
    return text

def format_order_for_admin(order):
    order_id, user_id, user_name, order_data, total_amount, address, delivery_time, payment_method, status, created_at = order
    
    try:
        order_details = json.loads(order_data)
    except:
        order_details = {"items": [], "total": 0}
    
    text = f"""
📦 <b>Заказ №{order_id}</b>

👤 <b>Клиент:</b> {user_name} (ID: {user_id})
📍 <b>Адрес:</b> {address}
⏰ <b>Время доставки:</b> {delivery_time}
💳 <b>Оплата:</b> {payment_method}
📊 <b>Статус:</b> {status}
🕐 <b>Создан:</b> {created_at}

<b>Состав заказа:</b>
"""
    for item in order_details.get("items", []):
        text += f"• {item['name']} - {item['quantity']} шт. × {item['price']} руб. = {item['total']} руб.\n"
    
    delivery_cost = calculate_delivery_cost(order_details.get("total", 0))
    discount_amount = calculate_discount(order_details.get("total", 0))
    final_total = order_details.get("total", 0) - discount_amount + delivery_cost
    
    text += f"""
💵 <b>Сумма заказа:</b> {order_details.get('total', 0)} руб.
🚚 <b>Доставка:</b> {delivery_cost} руб.
🎁 <b>Скидка:</b> -{discount_amount:.0f} руб.
💰 <b>Итого к оплате:</b> {final_total:.0f} руб.
"""
    return text

# ========== ФУНКЦИИ УВЕДОМЛЕНИЙ ==========
async def send_admin_notification(order_id, user_name, address, delivery_time, payment_method, total_amount, cart):
    """Функция для отправки уведомлений админам в ЛИЧНЫЕ сообщения"""
    try:
        logger.info(f"🔄 Начинаем отправку уведомления для заказа #{order_id}")
        
        notification_text = f"""
🆕 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>

👤 <b>Клиент:</b> {user_name}
📍 <b>Адрес:</b> {address}
⏰ <b>Время доставки:</b> {delivery_time}
💳 <b>Способ оплаты:</b> {payment_method}
💰 <b>Сумма к оплате:</b> {total_amount:.0f} руб.

<b>Состав заказа:</b>
"""
        
        for item in cart.get("items", []):
            notification_text += f"• {item['name']} - {item['quantity']} шт. × {item['price']} руб.\n"
        
        delivery_cost = calculate_delivery_cost(cart["total"])
        discount_amount = calculate_discount(cart["total"])
        
        notification_text += f"\n💵 Сумма заказа: {cart['total']} руб."
        notification_text += f"\n🚚 Доставка: {delivery_cost} руб."
        notification_text += f"\n🎁 Скидка: -{discount_amount:.0f} руб."
        notification_text += f"\n<b>💰 Итого: {total_amount:.0f} руб.</b>"
        
        logger.info(f"📨 Текст уведомления подготовлен для {len(ADMINS)} админов: {ADMINS}")
        
        # Отправляем уведомления всем админам в ЛИЧНЫЕ сообщения
        success_count = 0
        for admin_id in ADMINS:
            try:
                logger.info(f"📤 Попытка отправки ЛИЧНОГО уведомления админу {admin_id}")
                await bot.send_message(
                    admin_id,  # Это ваш ЛИЧНЫЙ ID - сообщение придет в личный чат с ботом
                    notification_text,
                    parse_mode="HTML"
                )
                success_count += 1
                logger.info(f"✅ ЛИЧНОЕ уведомление успешно отправлено админу {admin_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки ЛИЧНОГО уведомления админу {admin_id}: {e}")
        
        logger.info(f"📊 Итог рассылки: {success_count}/{len(ADMINS)} успешно")
        return success_count > 0
        
    except Exception as e:
        logger.error(f"💥 Критическая ошибка в send_admin_notification: {e}")
        return False

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Меню"), KeyboardButton(text="🛒 Корзина")],
            [KeyboardButton(text="📞 Контакты"), KeyboardButton(text="ℹ️ О нас")]
        ],
        resize_keyboard=True
    )

def categories_markup(categories):
    buttons = []
    for cat_id, cat_name in categories:
        buttons.append([InlineKeyboardButton(
            text=f"{cat_name}",
            callback_data=f"category_{cat_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def dishes_markup(dishes, category_id):
    buttons = []
    for dish_id, dish_name, price in dishes:
        buttons.append([InlineKeyboardButton(
            text=f"{dish_name} - {price} руб.",
            callback_data=f"dish_{dish_id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def dish_detail_markup(dish_id, category_id):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить в корзину", callback_data=f"add_to_cart_{dish_id}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_dishes_{category_id}"))
    return builder.as_markup()

def cart_markup(cart_items):
    builder = InlineKeyboardBuilder()
    
    for item in cart_items:
        builder.add(InlineKeyboardButton(text=f"➖ {item['name']}", callback_data=f"decrease_{item['dish_id']}"))
        builder.add(InlineKeyboardButton(text=f"{item['quantity']} шт.", callback_data="ignore"))
        builder.add(InlineKeyboardButton(text=f"➕ {item['name']}", callback_data=f"increase_{item['dish_id']}"))
        builder.add(InlineKeyboardButton(text=f"❌ Удалить", callback_data=f"remove_from_cart_{item['dish_id']}"))
    
    builder.add(InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout"))
    builder.add(InlineKeyboardButton(text="📋 Продолжить покупки", callback_data="continue_shopping"))
    builder.add(InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart"))
    
    builder.adjust(2, 2)
    return builder.as_markup()

def delivery_time_markup():
    builder = InlineKeyboardBuilder()
    for time_slot in DELIVERY_TIME_SLOTS:
        builder.add(InlineKeyboardButton(text=time_slot, callback_data=f"time_{time_slot}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад к адресу", callback_data="back_to_address"))
    builder.adjust(1)
    return builder.as_markup()

def payment_method_markup():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="💵 Наличными курьеру", callback_data="payment_cash"))
    builder.add(InlineKeyboardButton(text="💳 Картой курьеру", callback_data="payment_card"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад ко времени", callback_data="back_to_time"))
    builder.adjust(1)
    return builder.as_markup()

def confirm_order_markup():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Подтвердить заказ", callback_data="confirm_order"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_order"))
    return builder.as_markup()

def admin_menu_markup():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="📦 Заказы", callback_data="admin_orders"))
    builder.add(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
    builder.add(InlineKeyboardButton(text="🍽 Добавить блюдо", callback_data="admin_add_dish"))
    builder.add(InlineKeyboardButton(text="📝 Управление меню", callback_data="admin_manage_menu"))
    builder.adjust(2)
    return builder.as_markup()

def orders_markup(orders):
    builder = InlineKeyboardBuilder()
    for order in orders:
        order_id, _, _, _, _, _, _, _, status, _ = order
        builder.add(InlineKeyboardButton(
            text=f"Заказ #{order_id} - {status}", 
            callback_data=f"admin_order_{order_id}"
        ))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
    builder.adjust(1)
    return builder.as_markup()

def order_actions_markup(order_id):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ В работе", callback_data=f"order_status_{order_id}_в работе"))
    builder.add(InlineKeyboardButton(text="🚚 В доставке", callback_data=f"order_status_{order_id}_в доставке"))
    builder.add(InlineKeyboardButton(text="✅ Выполнен", callback_data=f"order_status_{order_id}_выполнен"))
    builder.add(InlineKeyboardButton(text="❌ Отменен", callback_data=f"order_status_{order_id}_отменен"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад к заказам", callback_data="admin_orders"))
    builder.adjust(2)
    return builder.as_markup()

def categories_markup_for_admin():
    categories = db.get_categories()
    builder = InlineKeyboardBuilder()
    for cat_id, cat_name in categories:
        builder.add(InlineKeyboardButton(text=cat_name, callback_data=f"admin_category_{cat_id}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
    builder.adjust(2)
    return builder.as_markup()

def dishes_admin_markup(dishes):
    builder = InlineKeyboardBuilder()
    for dish_id, dish_name, price in dishes:
        builder.add(InlineKeyboardButton(
            text=f"{dish_name} - {price} руб.", 
            callback_data=f"admin_dish_{dish_id}"
        ))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_menu"))
    builder.adjust(1)
    return builder.as_markup()

def dish_admin_actions_markup(dish_id):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔄 Изменить доступность", callback_data=f"admin_toggle_dish_{dish_id}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_menu"))
    builder.adjust(1)
    return builder.as_markup()

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Сохраняем пользователя в БД
    db.add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )
    
    await message.answer(
        "🍔 Добро пожаловать в <b>Голубка Шаурма Delivery</b>!\n\n"
        "🚀 Быстрая доставка по Минску\n"
        "🎁 Постоянная скидка 10% на все заказы!\n"
        "💳 Оплата наличными или картой курьеру\n"
        "🕐 Работаем: 10:00-23:00\n\n"
        "Выберите действие:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора"""
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer("⛔ У вас нет доступа к панели администратора")
        return
    
    await message.answer(
        "👑 <b>Панель администратора</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_menu_markup(),
        parse_mode="HTML"
    )

@dp.message(Command("debug_admin"))
async def debug_admin(message: Message):
    """Диагностика админ-прав"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    is_admin = user_id in ADMINS
    
    await message.answer(
        f"🔍 <b>Диагностика админ-прав:</b>\n"
        f"👤 Ваш ID: {user_id}\n"
        f"💬 ID этого чата: {chat_id}\n"
        f"👑 Админ: {'✅ Да' if is_admin else '❌ Нет'}\n"
        f"📋 Список админов: {ADMINS}\n\n"
        f"📍 <b>Важно:</b> Уведомления приходят в ЛИЧНЫЕ сообщения админам\n"
        f"📢 Этот чат - {'ГРУППА' if chat_id < 0 else 'ЛИЧНЫЙ ЧАТ'}\n\n"
        f"Используйте /test_private чтобы проверить личные уведомления",
        parse_mode="HTML"
    )

@dp.message(Command("test_private"))
async def test_private_notification(message: Message):
    """Тест отправки уведомления в личные сообщения"""
    user_id = message.from_user.id
    
    if user_id not in ADMINS:
        await message.answer("⛔ У вас нет доступа к этой команде")
        return
    
    # Отправляем тестовое сообщение в ЛИЧНЫЙ чат
    try:
        await bot.send_message(
            user_id,  # Отправляем в личный чат того, кто вызвал команду
            "🔔 <b>ТЕСТ ЛИЧНОГО УВЕДОМЛЕНИЯ</b>\n\n"
            "Это сообщение должно прийти вам в ЛИЧНЫЕ сообщения с ботом!\n"
            "Если вы видите это сообщение здесь, в группе - что-то не так.",
            parse_mode="HTML"
        )
        await message.answer("✅ Тестовое личное сообщение отправлено! Проверьте свои ЛИЧНЫЕ сообщения с ботом.")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки личного сообщения: {e}")

@dp.message(Command("force_notify"))
async def force_notify(message: Message):
    """Принудительная отправка уведомления"""
    if message.from_user.id not in ADMINS:
        return
    
    test_cart = {
        "items": [
            {"name": "Тестовый товар", "quantity": 2, "price": 100, "total": 200}
        ],
        "total": 200
    }
    
    await send_admin_notification(
        order_id=888,
        user_name="Тестовый пользователь", 
        address="Тестовый адрес",
        delivery_time="Как можно скорее",
        payment_method="наличными",
        total_amount=185,
        cart=test_cart
    )
    
    await message.answer("✅ Принудительное уведомление отправлено!")

@dp.message(F.text == "📋 Меню")
async def show_categories(message: types.Message):
    categories = db.get_categories()
    await message.answer("🍽 Выберите категорию:", reply_markup=categories_markup(categories))

@dp.message(F.text == "🛒 Корзина")
async def show_cart(message: types.Message):
    user_id = message.from_user.id
    cart = db.get_cart(user_id)
    cart_text = format_cart_text(cart)
    
    if not cart["items"]:
        await message.answer(cart_text)
    else:
        await message.answer(cart_text, reply_markup=cart_markup(cart["items"]), parse_mode="HTML")

# ========== ОБРАБОТЧИКИ АДМИНКИ ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    users_count = db.get_users_count()
    orders = db.get_orders(100)  # Последние 100 заказов для статистики
    
    total_orders = len(orders)
    total_revenue = sum(order[4] for order in orders)
    new_orders = len([order for order in orders if order[8] == 'новый'])
    
    stats_text = f"""
📊 <b>Статистика бота</b>

👥 Пользователей: {users_count}
📦 Всего заказов: {total_orders}
🆕 Новых заказов: {new_orders}
💰 Общая выручка: {total_revenue} руб.

<b>Последние заказы по статусам:</b>
"""
    
    status_counts = {}
    for order in orders[:10]:  # Последние 10 заказов
        status = order[8]
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in status_counts.items():
        stats_text += f"• {status}: {count}\n"
    
    await callback.message.edit_text(stats_text, reply_markup=admin_menu_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    orders = db.get_orders(10)  # Последние 10 заказов
    if not orders:
        await callback.message.edit_text("📦 Заказов пока нет", reply_markup=admin_menu_markup())
        return
    
    orders_text = "📦 <b>Последние заказы:</b>\n\n"
    for order in orders:
        order_id, _, user_name, _, total_amount, _, _, _, status, created_at = order
        orders_text += f"#{order_id} - {user_name} - {total_amount} руб. - {status}\n"
    
    await callback.message.edit_text(orders_text, reply_markup=orders_markup(orders), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_order_"))
async def admin_order_detail(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    order_id = int(callback.data.split("_")[2])
    order = db.get_order_by_id(order_id)
    
    if not order:
        await callback.answer("Заказ не найден")
        return
    
    order_text = format_order_for_admin(order)
    await callback.message.edit_text(order_text, reply_markup=order_actions_markup(order_id), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("order_status_"))
async def change_order_status(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    data = callback.data.split("_")
    order_id = int(data[2])
    new_status = data[3]
    
    db.update_order_status(order_id, new_status)
    
    await callback.answer(f"Статус заказа #{order_id} изменен на '{new_status}'")
    
    # Обновляем сообщение с деталями заказа
    order = db.get_order_by_id(order_id)
    order_text = format_order_for_admin(order)
    await callback.message.edit_text(order_text, reply_markup=order_actions_markup(order_id), parse_mode="HTML")

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    await callback.message.edit_text(
        "📢 <b>Рассылка сообщений</b>\n\n"
        "Отправьте сообщение для рассылки всем пользователям:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещен")
        return
    
    users = db.get_all_users()
    success_count = 0
    fail_count = 0
    
    await message.answer(f"🔄 Начинаю рассылку для {len(users)} пользователей...")
    
    for user_id in users:
        try:
            await bot.send_message(user_id, message.text, parse_mode="HTML")
            success_count += 1
            await asyncio.sleep(0.1)  # Чтобы не превысить лимиты Telegram
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            fail_count += 1
    
    await message.answer(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Не удалось: {fail_count}",
        parse_mode="HTML",
        reply_markup=admin_menu_markup()
    )
    await state.clear()

@dp.callback_query(F.data == "admin_add_dish")
async def admin_add_dish_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    await callback.message.edit_text(
        "🍽 <b>Добавление нового блюда</b>\n\n"
        "Введите название блюда:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_dish_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_dish_name)
async def admin_add_dish_name(message: Message, state: FSMContext):
    await state.update_data(dish_name=message.text)
    await message.answer("Введите описание блюда:")
    await state.set_state(AdminStates.waiting_for_dish_description)

@dp.message(AdminStates.waiting_for_dish_description)
async def admin_add_dish_description(message: Message, state: FSMContext):
    await state.update_data(dish_description=message.text)
    await message.answer("Введите состав блюда (ингредиенты):")
    await state.set_state(AdminStates.waiting_for_dish_ingredients)

@dp.message(AdminStates.waiting_for_dish_ingredients)
async def admin_add_dish_ingredients(message: Message, state: FSMContext):
    await state.update_data(dish_ingredients=message.text)
    await message.answer("Введите цену блюда (только число):")
    await state.set_state(AdminStates.waiting_for_dish_price)

@dp.message(AdminStates.waiting_for_dish_price)
async def admin_add_dish_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
        await state.update_data(dish_price=price)
        
        await message.answer(
            "Выберите категорию для блюда:",
            reply_markup=categories_markup_for_admin()
        )
        await state.set_state(AdminStates.waiting_for_dish_category)
    except ValueError:
        await message.answer("Пожалуйста, введите корректную цену (только число):")

@dp.callback_query(F.data.startswith("admin_category_"), AdminStates.waiting_for_dish_category)
async def admin_add_dish_final(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    
    dish_id = db.add_dish(
        category_id,
        data['dish_name'],
        data['dish_description'],
        data['dish_ingredients'],
        data['dish_price']
    )
    
    await callback.message.edit_text(
        f"✅ <b>Блюдо успешно добавлено!</b>\n\n"
        f"🍽 <b>Название:</b> {data['dish_name']}\n"
        f"📝 <b>Описание:</b> {data['dish_description']}\n"
        f"🧂 <b>Состав:</b> {data['dish_ingredients']}\n"
        f"💵 <b>Цена:</b> {data['dish_price']} руб.\n"
        f"📁 <b>ID блюда:</b> {dish_id}",
        parse_mode="HTML",
        reply_markup=admin_menu_markup()
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "admin_manage_menu")
async def admin_manage_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    await callback.message.edit_text(
        "🍽 <b>Управление меню</b>\n\n"
        "Выберите категорию:",
        reply_markup=categories_markup_for_admin(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_category_"))
async def admin_category_dishes(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    category_id = int(callback.data.split("_")[2])
    dishes = db.get_dishes_by_category(category_id)
    
    if not dishes:
        await callback.message.edit_text(
            "В этой категории пока нет блюд",
            reply_markup=categories_markup_for_admin()
        )
        return
    
    category_names = {1: "🥙 Шаурма", 2: "🍔 Бургеры", 3: "🍕 Пицца", 4: "🔥 Шаурма на углях"}
    category_name = category_names.get(category_id, "Категория")
    
    await callback.message.edit_text(
        f"🍽 <b>{category_name}</b>\n\n"
        "Выберите блюдо для управления:",
        reply_markup=dishes_admin_markup(dishes),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_dish_"))
async def admin_dish_detail(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    dish_id = int(callback.data.split("_")[2])
    dish_data = db.get_dish_details(dish_id)
    
    if not dish_data:
        await callback.answer("Блюдо не найдено")
        return
    
    dish_text = format_dish_details(dish_data)
    
    await callback.message.edit_text(
        dish_text,
        reply_markup=dish_admin_actions_markup(dish_id),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_toggle_dish_"))
async def admin_toggle_dish(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    dish_id = int(callback.data.split("_")[3])
    new_status = db.toggle_dish_availability(dish_id)
    
    if new_status is not None:
        status_text = "доступно" if new_status else "недоступно"
        await callback.answer(f"Блюдо теперь {status_text}")
        
        # Обновляем сообщение
        dish_data = db.get_dish_details(dish_id)
        dish_text = format_dish_details(dish_data)
        await callback.message.edit_text(
            dish_text,
            reply_markup=dish_admin_actions_markup(dish_id),
            parse_mode="HTML"
        )
    else:
        await callback.answer("Ошибка изменения статуса блюда")

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Доступ запрещен")
        return
    
    await callback.message.edit_text(
        "👑 <b>Панель администратора</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_menu_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

# ========== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ==========
@dp.callback_query(F.data.startswith('category_'))
async def show_dishes(callback: CallbackQuery):
    category_id = int(callback.data.split('_')[1])
    dishes = db.get_dishes_by_category(category_id)
    category_names = {1: "🥙 Шаурма", 2: "🍔 Бургеры", 3: "🍕 Пицца", 4: "🔥 Шаурма на углях"}
    category_name = category_names.get(category_id, "Категория")
    
    try:
        await callback.message.edit_text(
            f"{category_name}\nВыберите блюдо:",
            reply_markup=dishes_markup(dishes, category_id)
        )
    except:
        await callback.message.answer(
            f"{category_name}\nВыберите блюдо:",
            reply_markup=dishes_markup(dishes, category_id)
        )

@dp.callback_query(F.data.startswith('dish_'))
async def show_dish_details(callback: CallbackQuery):
    dish_id = int(callback.data.split('_')[1])
    dish_data = db.get_dish_details(dish_id)
    
    if not dish_data:
        await callback.answer("Блюдо не найдено")
        return
    
    dish_text = format_dish_details(dish_data)
    category_id = dish_data[1]
    
    if dish_data[6]:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=dish_data[6],
                caption=dish_text,
                reply_markup=dish_detail_markup(dish_id, category_id),
                parse_mode="HTML"
            )
        except Exception as e:
            await callback.message.answer(
                dish_text,
                reply_markup=dish_detail_markup(dish_id, category_id),
                parse_mode="HTML"
            )
    else:
        try:
            await callback.message.edit_text(
                dish_text,
                reply_markup=dish_detail_markup(dish_id, category_id),
                parse_mode="HTML"
            )
        except:
            await callback.message.answer(
                dish_text,
                reply_markup=dish_detail_markup(dish_id, category_id),
                parse_mode="HTML"
            )
    
    await callback.answer()

@dp.callback_query(F.data.startswith('add_to_cart_'))
async def add_to_cart(callback: CallbackQuery):
    dish_id = int(callback.data.split('_')[3])
    dish_data = db.get_dish_details(dish_id)
    
    if not dish_data:
        await callback.answer("Блюдо не найдено")
        return
    
    user_id = callback.from_user.id
    dish_name = dish_data[2]
    price = dish_data[5]
    
    db.add_to_cart(user_id, dish_id, dish_name, price)
    await callback.answer(f"✅ {dish_name} добавлен в корзину!")

@dp.callback_query(F.data.startswith('remove_from_cart_'))
async def remove_from_cart(callback: CallbackQuery):
    dish_id = int(callback.data.split('_')[3])
    user_id = callback.from_user.id
    cart = db.remove_from_cart(user_id, dish_id)
    cart_text = format_cart_text(cart)
    try:
        await callback.message.edit_text(cart_text, reply_markup=cart_markup(cart["items"]), parse_mode="HTML")
    except:
        await callback.message.answer(cart_text, reply_markup=cart_markup(cart["items"]), parse_mode="HTML")
    await callback.answer("Товар удален из корзины")

@dp.callback_query(F.data.startswith('increase_'))
async def increase_quantity(callback: CallbackQuery):
    dish_id = int(callback.data.split('_')[1])
    user_id = callback.from_user.id
    cart = db.update_cart_quantity(user_id, dish_id, 1)
    cart_text = format_cart_text(cart)
    try:
        await callback.message.edit_text(cart_text, reply_markup=cart_markup(cart["items"]), parse_mode="HTML")
    except:
        await callback.message.answer(cart_text, reply_markup=cart_markup(cart["items"]), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith('decrease_'))
async def decrease_quantity(callback: CallbackQuery):
    dish_id = int(callback.data.split('_')[1])
    user_id = callback.from_user.id
    cart = db.update_cart_quantity(user_id, dish_id, -1)
    cart_text = format_cart_text(cart)
    try:
        await callback.message.edit_text(cart_text, reply_markup=cart_markup(cart["items"]), parse_mode="HTML")
    except:
        await callback.message.answer(cart_text, reply_markup=cart_markup(cart["items"]), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == 'clear_cart')
async def clear_cart_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    db.clear_cart(user_id)
    try:
        await callback.message.edit_text("🛒 Ваша корзина очищена")
    except:
        await callback.message.answer("🛒 Ваша корзина очищена")
    await callback.answer("Корзина очищена")

@dp.callback_query(F.data == 'back_to_categories')
async def back_to_categories(callback: CallbackQuery):
    categories = db.get_categories()
    try:
        await callback.message.edit_text("🍽 Выберите категорию:", reply_markup=categories_markup(categories))
    except:
        await callback.message.answer("🍽 Выберите категорию:", reply_markup=categories_markup(categories))

@dp.callback_query(F.data.startswith('back_to_dishes_'))
async def back_to_dishes(callback: CallbackQuery):
    category_id = int(callback.data.split('_')[3])
    dishes = db.get_dishes_by_category(category_id)
    category_names = {1: "🥙 Шаурма", 2: "🍔 Бургеры", 3: "🍕 Пицца", 4: "🔥 Шаурма на углях"}
    category_name = category_names.get(category_id, "Категория")
    try:
        await callback.message.delete()
    except:
        pass
    await callback.message.answer(f"{category_name}\nВыберите блюдо:", reply_markup=dishes_markup(dishes, category_id))

@dp.callback_query(F.data == 'continue_shopping')
async def continue_shopping(callback: CallbackQuery):
    categories = db.get_categories()
    try:
        await callback.message.edit_text("🍽 Выберите категорию:", reply_markup=categories_markup(categories))
    except:
        await callback.message.answer("🍽 Выберите категорию:", reply_markup=categories_markup(categories))

@dp.callback_query(F.data == 'checkout')
async def start_checkout(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cart = db.get_cart(user_id)
    if not cart["items"]:
        await callback.answer("❌ Корзина пуста")
        return
    await callback.message.edit_text(
        "📍 <b>Введите адрес доставки:</b>\n\nУкажите улицу, дом, квартиру и любые дополнительные подробности для курьера.",
        parse_mode="HTML"
    )
    await state.set_state(OrderStates.waiting_for_address)
    await state.update_data(cart=cart)
    await callback.answer()

@dp.message(OrderStates.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    address = message.text.strip()
    await state.update_data(address=address)
    await message.answer("⏰ <b>Выберите время доставки:</b>", reply_markup=delivery_time_markup(), parse_mode="HTML")
    await state.set_state(OrderStates.waiting_for_time)

@dp.callback_query(F.data.startswith('time_'), OrderStates.waiting_for_time)
async def process_time(callback: CallbackQuery, state: FSMContext):
    delivery_time = callback.data.replace('time_', '')
    await state.update_data(delivery_time=delivery_time)
    await callback.message.edit_text("💳 <b>Выберите способ оплаты:</b>", reply_markup=payment_method_markup(), parse_mode="HTML")
    await state.set_state(OrderStates.waiting_for_payment)
    await callback.answer()

@dp.callback_query(F.data.startswith('payment_'), OrderStates.waiting_for_payment)
async def process_payment(callback: CallbackQuery, state: FSMContext):
    payment_method = "наличными" if callback.data == "payment_cash" else "картой"
    await state.update_data(payment_method=payment_method)
    data = await state.get_data()
    cart = data['cart']
    address = data['address']
    delivery_time = data['delivery_time']
    confirmation_text = format_order_confirmation(cart, address, delivery_time, payment_method)
    await callback.message.edit_text(confirmation_text, reply_markup=confirm_order_markup(), parse_mode="HTML")
    await state.set_state(OrderStates.confirming_order)
    await callback.answer()

@dp.callback_query(F.data == 'back_to_address', OrderStates.waiting_for_time)
async def back_to_address(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📍 <b>Введите адрес доставки:</b>\n\nУкажите улицу, дом, квартиру и любые дополнительные подробности для курьера.",
        parse_mode="HTML"
    )
    await state.set_state(OrderStates.waiting_for_address)
    await callback.answer()

@dp.callback_query(F.data == 'back_to_time', OrderStates.waiting_for_payment)
async def back_to_time(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("⏰ <b>Выберите время доставки:</b>", reply_markup=delivery_time_markup(), parse_mode="HTML")
    await state.set_state(OrderStates.waiting_for_time)
    await callback.answer()

@dp.callback_query(F.data == 'confirm_order', OrderStates.confirming_order)
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        cart = data['cart']
        address = data['address']
        delivery_time = data['delivery_time']
        payment_method = data['payment_method']
        user_id = callback.from_user.id
        user_name = callback.from_user.full_name
        
        logger.info(f"Подтверждение заказа от пользователя {user_id} ({user_name})")
        
        discount_amount = calculate_discount(cart['total'])
        delivery_cost = calculate_delivery_cost(cart['total'])
        final_total = cart['total'] - discount_amount + delivery_cost
        
        order_id = db.create_order(user_id, user_name, cart, address, delivery_time, payment_method)
        logger.info(f"Создан заказ #{order_id} на сумму {final_total} руб.")
        
        db.clear_cart(user_id)
        
        await callback.message.edit_text(
            f"🎉 <b>Заказ #{order_id} успешно оформлен!</b>\n\n"
            f"📍 <b>Адрес доставки:</b> {address}\n"
            f"⏰ <b>Время доставки:</b> {delivery_time}\n"
            f"💳 <b>Способ оплаты:</b> {payment_method}\n"
            f"💰 <b>Сумма к оплате:</b> {final_total:.0f} руб.\n\n"
            f"📞 Если у вас есть вопросы, звоните: {RESTAURANT_PHONE}\n\n"
            f"Спасибо за заказ! Приятного аппетита! 🍔",
            parse_mode="HTML"
        )
        
        await send_admin_notification(
            order_id=order_id,
            user_name=user_name,
            address=address,
            delivery_time=delivery_time,
            payment_method=payment_method,
            total_amount=final_total,
            cart=cart
        )
        
        await state.clear()
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при подтверждении заказа: {e}")
        await callback.answer("❌ Произошла ошибка при оформлении заказа")

@dp.callback_query(F.data == 'cancel_order', OrderStates.confirming_order)
async def cancel_order(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Заказ отменен.\n\nВы можете продолжить покупки или оформить заказ позже.")
    await callback.answer()

@dp.message(F.text == "📞 Контакты")
async def show_contacts(message: Message):
    await message.answer(
        f"📞 <b>Контакты Голубка Шаурма</b>\n\n"
        f"☎️ Телефон: {RESTAURANT_PHONE}\n"
        f"🕐 Время работы: 10:00-23:00\n"
        f"🚗 Доставка: {DELIVERY_COST} руб. (бесплатно от {FREE_DELIVERY_AMOUNT} руб.)\n"
        f"💳 Оплата: наличными или картой курьеру\n"
        f"🎁 Скидка: {DISCOUNT_PERCENT}% на все заказы!",
        parse_mode="HTML"
    )

@dp.message(F.text == "ℹ️ О нас")
async def show_about(message: Message):
    await message.answer(
        "🍔 <b>Голубка Шаурма Delivery</b>\n\n"
        "Мы готовим самую вкусную шаурму в Минске!\n\n"
        "✨ Почему выбирают нас:\n"
        "• Свежие ингредиенты\n"
        "• Быстрая доставка\n"
        "• Приятные цены\n"
        "• Постоянные акции и скидки\n"
        "• Удобная оплата (наличными или картой)\n\n"
        "Заказывайте с удовольствием! 🥙",
        parse_mode="HTML"
    )

@dp.message(Command("test_notification"))
async def test_notification(message: Message):
    """Тестовая команда для проверки уведомлений"""
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    
    logger.info(f"Запрос test_notification от {user_id} ({user_name})")
    
    if user_id not in ADMINS:
        await message.answer("⛔ У вас нет доступа к этой команде")
        logger.warning(f"Попытка доступа к админ-команде от не-админа: {user_id}")
        return
    
    test_cart = {
        "items": [
            {"name": "Тестовый товар 1", "quantity": 2, "price": 100, "total": 200},
            {"name": "Тестовый товар 2", "quantity": 1, "price": 150, "total": 150}
        ],
        "total": 350
    }
    
    delivery_cost = calculate_delivery_cost(test_cart["total"])
    discount_amount = calculate_discount(test_cart["total"])
    final_total = test_cart["total"] - discount_amount + delivery_cost
    
    await message.answer("🔄 Отправка тестового уведомления...")
    
    success = await send_admin_notification(
        order_id=999,
        user_name="Тестовый пользователь",
        address="Тестовый адрес, д. 1, кв. 1",
        delivery_time="Как можно скорее",
        payment_method="наличными",
        total_amount=final_total,
        cart=test_cart
    )
    
    if success:
        await message.answer("✅ Тестовое уведомление отправлено! Проверьте свои ЛИЧНЫЕ сообщения с ботом.")
    else:
        await message.answer("❌ Не удалось отправить тестовое уведомление. Проверьте логи.")

# ========== ЗАПУСК ==========
async def main():
    logger.info("Запуск бота Голубка Шаурма Delivery...")
    
    try:
        bot_info = await bot.get_me()
        logger.info(f"Бот @{bot_info.username} успешно подключен")
        logger.info(f"ID админов: {ADMINS}")
        logger.info(f"Администратор: @yanovskay_tatsiana")
    except Exception as e:
        logger.error(f"Ошибка подключения бота: {e}")
        return
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")

# Это очень важно для PythonAnywhere!
if __name__ == "__main__":
    asyncio.run(main())
