import os
import re
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from collections import defaultdict
from datetime import datetime
import json
import logging

# Настройка логирования для Railway
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = '7238405312:AAHnIstQOhuy-76PDdhAJSMnS1Y9oQc-zac'
bot = telebot.TeleBot(TOKEN)

DATA_FILE = 'schedule_bot.json'
user_data = defaultdict(dict)

# Структура для расходов
EXPENSE_CATEGORIES = {
    'car': '🚗 По машині',
    'freelance': '👥 По фрілансам',
    'other': '📦 Інші'
}


def load_user_data(user_id):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
            if str(user_id) not in all_data:
                all_data[str(user_id)] = {
                    'days': [],
                    'total_salary': 0,
                    'total_orders': 0,
                    'expenses': {
                        'car': [],
                        'freelance': [],
                        'other': []
                    },
                    'business_cards': {}  # Добавляем инициализацию
                }
            else:
                # Если данные уже есть, проверяем наличие business_cards
                user_data = all_data[str(user_id)]
                if 'business_cards' not in user_data:
                    user_data['business_cards'] = {}
                if 'expenses' not in user_data:
                    user_data['expenses'] = {
                        'car': [],
                        'freelance': [],
                        'other': []
                    }
            return all_data[str(user_id)]
    return {
        'days': [],
        'total_salary': 0,
        'total_orders': 0,
        'expenses': {
            'car': [],
            'freelance': [],
            'other': []
        },
        'business_cards': {}  # И здесь тоже
    }


def save_user_data(user_id, data):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    else:
        all_data = {}
    all_data[str(user_id)] = data
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)


def update_or_add_day(user_data, date, worked=None, salary=None, orders_count=None):
    """Исправленная функция обновления дней"""
    salary = salary or 0
    orders_count = orders_count or 0

    existing = next((d for d in user_data['days'] if d['date'] == date), None)

    if existing:
        old_worked = existing.get('worked', False)
        old_salary = existing.get('salary', 0)
        old_orders = existing.get('orders_count', 0)

        if worked is not None:
            existing['worked'] = worked
        if salary is not None:
            existing['salary'] = salary
        if orders_count is not None:
            existing['orders_count'] = orders_count

        if worked:
            user_data['total_salary'] = user_data['total_salary'] - old_salary + salary
        else:
            user_data['total_salary'] = user_data['total_salary'] - old_salary

        user_data['total_orders'] = user_data['total_orders'] - old_orders + orders_count

    else:
        new_day = {
            'date': date,
            'worked': worked or False,
            'salary': salary,
            'orders_count': orders_count
        }
        user_data['days'].append(new_day)

        if worked:
            user_data['total_salary'] += salary
        user_data['total_orders'] += orders_count


def parse_schedule(text, user_id):
    """Упрощённый парсинг: время, описание (полное), цена; + спец 'сплачено' с price=0"""
    lines = text.split('\n')
    orders = []
    current_car = None
    total = 0

    for line in lines:
        line = line.strip()

        if 'Рено' in line or 'рено' in line.lower():
            current_car = 'Рено'
            continue

        if current_car != 'Рено':
            continue

        if not line or re.match(r'^(Фіат|Кадді|Хюндай|Сітроен)', line, re.IGNORECASE):
            continue

        time_match = re.search(r'(\d{1,2}\.\d{2})', line)
        if not time_match:
            continue
        time = time_match.group(1)

        price_match = re.search(r'(\d+)грн', line)
        price = int(price_match.group(1)) if price_match else 0

        is_prepaid = 'сплачено' in line.lower() and price == 0

        desc_start = time_match.end()
        desc = line[desc_start:].strip(' ,-')
        if price_match:
            price_start = price_match.start()
            desc = line[desc_start:price_start].strip(' ,-')
            desc = re.sub(r'\s+', ' ', desc)

        if price > 0 or is_prepaid:
            order = {
                'time': time,
                'desc': desc,
                'price': price,
                'payment': 'Сплачено' if is_prepaid else None,
                'given_amount': 0,
                'received': 0 if is_prepaid else 0,
                'tips': 0,
                'tip_people': 0,
                'tips_per': 0,
                'change': 0,
                'other_person': None,
                'is_prepaid': is_prepaid,
                'business_card': None  # Нова змінна для візитки
            }
            orders.append(order)
            if price > 0:
                total += price

    zp_data = load_user_data(user_id)
    today = datetime.now().strftime('%d.%m.%Y')
    update_or_add_day(zp_data, today, worked=True, orders_count=len(orders))
    save_user_data(user_id, zp_data)

    user_data[user_id]['orders'] = orders
    user_data[user_id]['total'] = total
    return orders, total


def get_order_keyboard(user_id):
    """Клавіатура для вибору замовлення"""
    if 'orders' not in user_data[user_id]:
        return None
    orders = user_data[user_id]['orders']
    markup = InlineKeyboardMarkup()
    for i, order in enumerate(orders):
        status = "✅" if order['payment'] else "⭕"
        price_text = 'сплачено' if order['is_prepaid'] else f"{order['price']} грн"
        btn_text = f"{status} {order['time']} - {price_text}"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"order_{i}"))
    markup.add(InlineKeyboardButton("📊 Звіт для директора", callback_data="report_director"))
    markup.add(InlineKeyboardButton("📊 Повний звіт", callback_data="report_full"))
    markup.add(InlineKeyboardButton("💸 Витрати", callback_data="expenses"))
    markup.add(InlineKeyboardButton("🔄 Перепарсити", callback_data="reparse"))
    return markup


def get_payment_keyboard(order_idx):
    """Клавіатура для оплати замовлення"""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Оплата карткою", callback_data=f"pay_card_{order_idx}"))
    markup.add(InlineKeyboardButton("💵 Готівка", callback_data=f"pay_cash_{order_idx}"))
    markup.add(InlineKeyboardButton("💵 Готівка з рештою", callback_data=f"pay_cash_change_{order_idx}"))
    markup.add(InlineKeyboardButton("👥 У іншого", callback_data=f"pay_other_{order_idx}"))
    markup.add(InlineKeyboardButton("⬅️ Назад до замовлень", callback_data="back_orders"))
    return markup


def get_business_card_keyboard(order_idx):
    """Клавіатура для візитки"""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Так, дав візитку", callback_data=f"card_yes_{order_idx}"))
    markup.add(InlineKeyboardButton("❌ Ні, не давав", callback_data=f"card_no_{order_idx}"))
    return markup


def get_expenses_keyboard():
    """Клавіатура для витрат"""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🚗 По машині", callback_data="expense_car"))
    markup.add(InlineKeyboardButton("👥 По фрілансам", callback_data="expense_freelance"))
    markup.add(InlineKeyboardButton("📦 Інші", callback_data="expense_other"))
    markup.add(InlineKeyboardButton("📊 Переглянути витрати", callback_data="view_expenses"))
    markup.add(InlineKeyboardButton("🗑️ Очистити всі витрати", callback_data="clear_all_expenses"))
    markup.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_orders"))
    return markup


@bot.callback_query_handler(func=lambda call: call.data == 'clear_all_expenses')
def clear_all_expenses(call):
    user_id = call.message.chat.id
    zp_data = load_user_data(user_id)

    zp_data['expenses'] = {
        'car': [],
        'freelance': [],
        'other': []
    }

    save_user_data(user_id, zp_data)
    bot.answer_callback_query(call.id, "✅ Всі витрати очищено!")
    send_order_menu(user_id)

@bot.message_handler(commands=['start'])
def start(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("📋 Надіслати розклад"))
    markup.add(KeyboardButton("💸 Витрати"))  # Добавим кнопку расходов в главное меню
    markup.add(KeyboardButton("📊 Звіт для директора"))
    markup.add(KeyboardButton("📊 Повний звіт"))
    bot.send_message(message.chat.id,
                     "🤖 Бот для обліку замовлень Рено\n\n"
                     "📋 Надіслати розклад — парсить замовлення.\n"
                     "💸 Витрати — додати витрати.\n"
                     "📊 Звіт для директора — фінансовий звіт.\n"
                     "📊 Повний звіт — детальний звіт по замовленням.",
                     reply_markup=markup)


@bot.message_handler(func=lambda msg: msg.text == "📋 Надіслати розклад")
def handle_schedule(message):
    bot.send_message(message.chat.id,
                     "📝 Надішли розклад (тільки частина для Рено).")
    bot.register_next_step_handler(message, process_schedule)


def process_schedule(message):
    user_id = message.chat.id
    try:
        orders, total = parse_schedule(message.text, user_id)
        if not orders:
            bot.send_message(user_id, "❌ Не знайшов замовлень для Рено. Перевір формат.")
            return

        preview = f"✅ Розпарсив {len(orders)} замовлень. Загальна сума: {total} грн\n\n"
        for i, order in enumerate(orders, 1):
            price_text = 'сплачено' if order['is_prepaid'] else f"{order['price']} грн"
            preview += f"{i}. {order['time']} - {price_text}\n"
            preview += f"   📝 {order['desc']}\n\n"

        bot.send_message(user_id, preview)
        send_order_menu(user_id)

    except Exception as e:
        bot.send_message(user_id, f"❌ Помилка парсингу: {e}")


def send_order_menu(user_id):
    markup = get_order_keyboard(user_id)
    if markup:
        bot.send_message(user_id, "🎯 Обери замовлення для відмітки оплати:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('order_'))
def handle_order(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "Спочатку надішли розклад!")
        return

    orders = user_data[user_id]['orders']
    order_idx = int(call.data.split('_')[1])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "Замовлення не знайдено!")
        return

    order = orders[order_idx]

    status = f" | ✅ {order['payment']}" if order['payment'] else ""
    tips_text = f" | ☕ +{order['tips']} грн" if order['tips'] > 0 else ""
    change_text = f" | 💰 решта {order['change']} грн" if order['change'] > 0 else ""
    price_text = 'сплачено' if order['is_prepaid'] else f"{order['price']} грн"

    text = (f"🕒 {order['time']}{status}{tips_text}{change_text}\n"
            f"💰 {price_text}\n"
            f"📝 {order['desc']}\n\n"
            f"Відмітити оплату:")

    bot.edit_message_text(text, user_id, call.message.message_id,
                          reply_markup=get_payment_keyboard(order_idx))


@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_card_'))
def pay_card(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "❌ Спочатку надішли розклад!")
        return

    orders = user_data[user_id]['orders']
    order_idx = int(call.data.split('_')[2])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "❌ Замовлення не знайдено!")
        return

    order = orders[order_idx]
    order['payment'] = 'Карта'
    order['received'] = order['price'] if not order['is_prepaid'] else 0
    order['given_amount'] = order['price'] if not order['is_prepaid'] else 0
    order['change'] = 0

    bot.answer_callback_query(call.id, "✅ Оплата карткою відмічена!")

    # Отправляем реквизиты
    requisites = (
        "💳 *РЕКВІЗИТИ ДЛЯ ОПЛАТИ:*\n\n"
        "Отримувач платежу - ГАЖЕВА НАТАЛЯ МИКОЛАЇВНА\n"
        "ЄДРПОУ отримувача - 3360014305\n"
        "Призначення платежу: анімаційна програма"
    )

    iban = "UA763052990000026002004924622"

    # Отправляем реквизиты
    bot.send_message(user_id, requisites, parse_mode='Markdown')

    # Отправляем IBAN отдельным сообщением
    bot.send_message(user_id, f"`{iban}`", parse_mode='Markdown')

    # Питаємо про візитку
    msg = bot.send_message(user_id, "🎴 Дав візитку?", reply_markup=get_business_card_keyboard(order_idx))

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_cash_'))
def pay_cash(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "❌ Спочатку надішли розклад!")
        return

    orders = user_data[user_id]['orders']

    if 'change' in call.data:
        order_idx = int(call.data.split('_')[3])
    else:
        order_idx = int(call.data.split('_')[2])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "❌ Замовлення не знайдено!")
        return

    order = orders[order_idx]

    if 'change' in call.data:
        price_for_msg = order['price'] if not order['is_prepaid'] else 0
        msg = bot.send_message(user_id, f"💵 Введи отриману суму готівкою (ціна {price_for_msg} грн):")
        bot.register_next_step_handler(msg, lambda m: process_cash_payment_with_change(m, user_id, order_idx))
    else:
        price_for_msg = order['price'] if not order['is_prepaid'] else 0
        msg = bot.send_message(user_id, f"💵 Введи отриману суму готівкою (ціна {price_for_msg} грн):")
        bot.register_next_step_handler(msg, lambda m: process_cash_payment(m, user_id, order_idx))


def process_cash_payment(message, user_id, order_idx):
    if 'orders' not in user_data[user_id]:
        return

    orders = user_data[user_id]['orders']
    if order_idx >= len(orders):
        return

    try:
        given_amount = int(message.text)
        order = orders[order_idx]

        order['payment'] = 'Готівка'
        order['given_amount'] = given_amount
        order['received'] = order['price'] if not order['is_prepaid'] else 0
        order['change'] = 0

        if not order['is_prepaid'] and given_amount > order['price']:
            tips = given_amount - order['price']
            order['tips'] = tips
            msg = bot.send_message(user_id, f"☕ Це чай: {tips} грн. Введи кількість людей для поділу:")
            bot.register_next_step_handler(msg, lambda m: process_tip_people(m, user_id, order_idx, tips))
            return
        else:
            bot.send_message(user_id, f"✅ Оплата готівкою: {given_amount} грн")

    except ValueError:
        bot.send_message(user_id, "❌ Помилка! Введи число.")
        return

    # Питаємо про візитку після успішної оплати
    msg = bot.send_message(user_id, "🎴 Дав візитку?", reply_markup=get_business_card_keyboard(order_idx))


@bot.callback_query_handler(func=lambda call: call.data.startswith('card_'))
def handle_business_card(call):
    user_id = call.message.chat.id
    parts = call.data.split('_')
    order_idx = int(parts[2])
    gave_card = parts[1] == 'yes'

    if 'orders' not in user_data[user_id] or order_idx >= len(user_data[user_id]['orders']):
        bot.answer_callback_query(call.id, "❌ Помилка!")
        return

    order = user_data[user_id]['orders'][order_idx]
    order['business_card'] = gave_card

    # Зберігаємо в загальних даних
    zp_data = load_user_data(user_id)

    # Инициализируем business_cards если его нет
    if 'business_cards' not in zp_data:
        zp_data['business_cards'] = {}

    today = datetime.now().strftime('%d.%m.%Y')
    if today not in zp_data['business_cards']:
        zp_data['business_cards'][today] = []

    zp_data['business_cards'][today].append({
        'time': order['time'],
        'gave_card': gave_card
    })
    save_user_data(user_id, zp_data)

    status = "дав" if gave_card else "не давав"
    bot.answer_callback_query(call.id, f"✅ Відмічено: {status} візитку")
    send_order_menu(user_id)


def process_tip_people(message, user_id, order_idx, tips):
    try:
        num_people = int(message.text)
        if num_people <= 0:
            raise ValueError
        orders = user_data[user_id]['orders']
        order = orders[order_idx]
        order['tip_people'] = num_people
        order['tips_per'] = tips // num_people
        bot.send_message(user_id, f"☕ Чай {tips} грн → по {order['tips_per']} грн на {num_people} чол.")
    except ValueError:
        bot.send_message(user_id, "❌ Введи додатне число! Спробуй знову.")
        msg = bot.send_message(user_id, f"Введи кількість людей для поділу чаю {tips} грн:")
        bot.register_next_step_handler(msg, lambda m: process_tip_people(m, user_id, order_idx, tips))
        return

    # Питаємо про візитку після розподілу чаю
    msg = bot.send_message(user_id, "🎴 Дав візитку?", reply_markup=get_business_card_keyboard(order_idx))


def process_cash_payment_with_change(message, user_id, order_idx):
    if 'orders' not in user_data[user_id]:
        return

    orders = user_data[user_id]['orders']
    if order_idx >= len(orders):
        return

    try:
        given_amount = int(message.text)
        order = orders[order_idx]

        if not order['is_prepaid'] and given_amount < order['price']:
            bot.send_message(user_id, f"❌ Сума менша за ціну ({order['price']} грн)!")
            return

        change = given_amount - (order['price'] if not order['is_prepaid'] else 0)

        order['payment'] = 'Готівка (з рештою)'
        order['given_amount'] = given_amount
        order['received'] = order['price'] if not order['is_prepaid'] else 0
        order['change'] = change
        order['tips'] = 0

        bot.send_message(user_id,
                         f"✅ Оплата готівкою: {given_amount} грн\n"
                         f"💰 Вартість: {order['received']} грн\n"
                         f"🪙 Решта: {change} грн\n"
                         f"💸 До віддачі клієнту: {change} грн")

    except ValueError:
        bot.send_message(user_id, "❌ Помилка! Введи число.")
        return

    # Питаємо про візитку
    msg = bot.send_message(user_id, "🎴 Дав візитку?", reply_markup=get_business_card_keyboard(order_idx))


@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_other_'))
def pay_other(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "❌ Спочатку надішли розклад!")
        return

    orders = user_data[user_id]['orders']
    order_idx = int(call.data.split('_')[2])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "❌ Замовлення не знайдено!")
        return

    msg = bot.send_message(user_id, "👥 Введи ім'я людини, у якої розрахунок:")
    bot.register_next_step_handler(msg, lambda m: process_other_payment(m, user_id, order_idx))


def process_other_payment(message, user_id, order_idx):
    if 'orders' not in user_data[user_id]:
        return

    orders = user_data[user_id]['orders']
    if order_idx >= len(orders):
        return

    name = message.text.strip()
    order = orders[order_idx]

    order['payment'] = f'У {name}'
    order['other_person'] = name
    order['received'] = order['price'] if not order['is_prepaid'] else 0
    order['given_amount'] = order['price'] if not order['is_prepaid'] else 0
    order['change'] = 0

    bot.send_message(user_id, f"✅ Відмічено: розрахунок у {name}")
    send_order_menu(user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'back_orders')
def back_to_orders(call):
    user_id = call.message.chat.id
    send_order_menu(user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'expenses')
def show_expenses_menu(call):
    user_id = call.message.chat.id
    bot.edit_message_text("💸 Оберіть категорію витрат:",
                          user_id, call.message.message_id,
                          reply_markup=get_expenses_keyboard())


@bot.callback_query_handler(func=lambda call: call.data.startswith('expense_'))
def handle_expense_category(call):
    user_id = call.message.chat.id
    category = call.data.split('_')[1]

    if category in ['car', 'freelance', 'other']:
        msg = bot.send_message(user_id, f"📝 Введи опис витрати для {EXPENSE_CATEGORIES[category]}:")
        bot.register_next_step_handler(msg, lambda m: process_expense_description(m, user_id, category))


def process_expense_description(message, user_id, category):
    description = message.text.strip()
    msg = bot.send_message(user_id, f"💰 Введи суму витрати (грн):")
    bot.register_next_step_handler(msg, lambda m: process_expense_amount(m, user_id, category, description))


def process_expense_amount(message, user_id, category, description):
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError

        zp_data = load_user_data(user_id)
        today = datetime.now().strftime('%d.%m.%Y')

        expense = {
            'date': today,
            'description': description,
            'amount': amount
        }

        zp_data['expenses'][category].append(expense)
        save_user_data(user_id, zp_data)

        bot.send_message(user_id, f"✅ Витрату додано: {EXPENSE_CATEGORIES[category]} - {description} - {amount} грн")
        send_order_menu(user_id)

    except ValueError:
        bot.send_message(user_id, "❌ Введи додатне число! Спробуй знову.")
        msg = bot.send_message(user_id, f"💰 Введи суму витрати (грн):")
        bot.register_next_step_handler(msg, lambda m: process_expense_amount(m, user_id, category, description))


@bot.callback_query_handler(func=lambda call: call.data == 'view_expenses')
def view_expenses(call):
    user_id = call.message.chat.id
    zp_data = load_user_data(user_id)

    report = "💸 ВИТРАТИ ЗА СЬОГОДНІ:\n\n"
    total_expenses = 0

    for category, expenses in zp_data['expenses'].items():
        category_total = sum(exp['amount'] for exp in expenses)
        total_expenses += category_total

        if category_total > 0:
            report += f"{EXPENSE_CATEGORIES[category]}:\n"
            for exp in expenses:
                report += f"  • {exp['description']}: {exp['amount']} грн\n"
            report += f"  💰 Всього: {category_total} грн\n\n"

    report += f"📊 ЗАГАЛЬНІ ВИТРАТИ: {total_expenses} грн"

    bot.send_message(user_id, report)
    send_order_menu(user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'report_full')
@bot.message_handler(func=lambda msg: msg.text == "📊 Повний звіт")
def show_full_report(message_or_call):
    if isinstance(message_or_call, telebot.types.CallbackQuery):
        user_id = message_or_call.message.chat.id
    else:
        user_id = message_or_call.chat.id

    if 'orders' not in user_data[user_id] or not user_data[user_id]['orders']:
        bot.send_message(user_id, "📭 Немає доданих замовлень")
        return

    orders = user_data[user_id]['orders']
    orders.sort(key=lambda x: x['time'])

    card_total = 0
    cash_total = 0
    tips_total = sum(order['tips'] for order in orders)

    # Реально отримані доходи
    for order in orders:
        if order['payment'] and not order['is_prepaid']:
            pay = order['payment'].lower()
            if 'карт' in pay:
                card_total += order['price']
            elif 'готів' in pay:
                cash_total += order['price']
            elif 'у ' in pay:
                pass  # у іншого — не рахуємо

    # Витрати
    zp_data = load_user_data(user_id)
    total_expenses = 0
    expense_report = ""

    for category, expenses in zp_data['expenses'].items():
        category_total = sum(exp['amount'] for exp in expenses)
        total_expenses += category_total

        if category_total > 0:
            expense_report += f"{EXPENSE_CATEGORIES[category]}:\n"
            grouped = {}
            for exp in expenses:
                grouped.setdefault(exp['description'], 0)
                grouped[exp['description']] += exp['amount']
            for desc, amount in grouped.items():
                expense_report += f"{desc} ({amount})\n"
            expense_report += "\n"

    report = f"📊 ПОВНИЙ ЗВІТ {datetime.now().strftime('%d.%m.%Y')}\n\n"

    # Отримані гроші
    report += "💵 ДОХОДИ:\n"
    for order in orders:
        if order['payment'] and not order['is_prepaid']:
            pay = order['payment'].lower()
            if 'карт' in pay:
                report += f"{order['time']} карта ({order['price']})\n"
            elif 'готів' in pay:
                report += f"{order['time']} готівка ({order['price']})\n"
            elif 'у ' in pay:
                report += f"{order['time']} ({order['price']}) {order['payment']}\n"
    report += "\n"

    # Витрати секція
    if total_expenses > 0:
        report += "💸 ВИТРАТИ:\n" + expense_report

    # Підсумки
    report += "📈 ВСЬОГО:\n"
    report += f"Карта: {card_total} грн\n"
    report += f"Готівка: {cash_total} грн\n"

    if total_expenses > 0:
        report += f"Витрати: {total_expenses} грн\n\n"
        net_cash = cash_total - total_expenses

        clean_cash_line = f"💰 Чиста готівка: {net_cash} грн"
        total_income_line = f"💰 Загальний дохід: {card_total + net_cash} грн"

        separator = "-" * len(total_income_line)

        report += separator + "\n"
        report += clean_cash_line + "\n"
        report += total_income_line
    else:
        total_income_line = f"💰 Загальний дохід: {card_total + cash_total} грн"
        separator = "-" * len(total_income_line)
        report += "\n" + separator + "\n" + total_income_line

    # ЧАЇ ДЕТАЛЬНО
    if tips_total > 0:
        report += "\n\n☕ ЧАЇ:\n"
        for order in orders:
            if order['tips'] > 0:
                time = order['time']
                tips = order['tips']
                per = order['tips_per']
                ppl = order['tip_people']
                report += f"• {time} — {tips} грн (по {per} грн на {ppl} чол)\n"

        report += f"\nВсього чаїв: {tips_total} грн"

    if len(report) > 4000:
        for i in range(0, len(report), 4000):
            bot.send_message(user_id, report[i:i + 4000])
    else:
        bot.send_message(user_id, report)


@bot.callback_query_handler(func=lambda call: call.data == 'report_director')
@bot.message_handler(func=lambda msg: msg.text == "📊 Звіт для директора")
def show_director_report(message_or_call):
    if isinstance(message_or_call, telebot.types.CallbackQuery):
        user_id = message_or_call.message.chat.id
    else:
        user_id = message_or_call.chat.id

    if 'orders' not in user_data[user_id] or not user_data[user_id]['orders']:
        bot.send_message(user_id, "📭 Немає доданих замовлень")
        return

    orders = user_data[user_id]['orders']
    orders.sort(key=lambda x: x['time'])

    zp_data = load_user_data(user_id)

    # Підрахунок доходів - ТОЛЬКО реально полученные деньги
    card_total = 0
    cash_total = 0

    report = f"📊 ЗВІТ {datetime.now().strftime('%d.%m.%Y')}\n\n"

    # Доходи
    report += "💵 ДОХОДИ: \n"
    for order in orders:
        if order['payment'] and not order['is_prepaid']:
            if 'карт' in order['payment'].lower():
                report += f"{order['time']} карта ({order['price']})\n"
                card_total += order['price']  # Карта - полная сумма
            elif 'готів' in order['payment'].lower():
                report += f"{order['time']} готівка ({order['price']})\n"
                cash_total += order['price']  # Наличные - полная сумма
            elif 'у ' in order['payment'].lower():
                # "У другого" - только показываем, но не считаем в итогах
                report += f"{order['time']} ({order['price']}) {order['payment']}\n"
                # НЕ добавляем к cash_total!

    report += "\n"

    # Витрати - группируем по категориям
    report += "💸 ВИТРАТИ:\n"
    total_expenses = 0

    for category, expenses in zp_data['expenses'].items():
        category_total = sum(exp['amount'] for exp in expenses)
        total_expenses += category_total

        if category_total > 0:
            report += f"{EXPENSE_CATEGORIES[category]}:\n"
            # Группируем одинаковые расходы
            expense_groups = {}
            for exp in expenses:
                key = exp['description']
                if key not in expense_groups:
                    expense_groups[key] = 0
                expense_groups[key] += exp['amount']

            for desc, amount in expense_groups.items():
                report += f"{desc} ({amount})\n"
            report += "\n"

    # Підсумки - ПРАВИЛЬНЫЙ расчет
    report += "📈 ВСЬОГО:\n"
    report += f"Карта: {card_total} грн\n"
    report += f"Готівка: {cash_total} грн\n"

    if total_expenses > 0:
        report += f"Витрати: {total_expenses} грн\n\n"
        # Расходы вычитаем ТОЛЬКО из наличных!
        net_cash = cash_total - total_expenses
        report += f"💰 Чиста готівка: {net_cash} грн\n"
        report += f"💰 Загальний дохід: {card_total + net_cash} грн"
    else:
        report += f"\n💰 Загальний дохід: {card_total + cash_total} грн"

    bot.send_message(user_id, report)

@bot.callback_query_handler(func=lambda call: call.data == 'reparse')
def reparse_schedule(call):
    user_id = call.message.chat.id
    bot.send_message(user_id, "Надішли розклад ще раз:")
    bot.register_next_step_handler(call.message, process_schedule)


if __name__ == '__main__':
    print("Бот запущений!")
    bot.polling(none_stop=True)
