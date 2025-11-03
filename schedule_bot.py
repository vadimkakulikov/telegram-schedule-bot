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

TOKEN = '8407963467:AAFBO8GOYiXQOuSFgSJw3_94j0A94c2TdxI'
bot = telebot.TeleBot(TOKEN)

# Остальной код БЕЗ ИЗМЕНЕНИЙ - вставь сюда весь твой текущий код начиная с:
DATA_FILE = 'schedule_bot.json'
user_data = defaultdict(dict)


def load_user_data(user_id):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
            if str(user_id) not in all_data:
                all_data[str(user_id)] = {'days': [], 'total_salary': 0, 'total_orders': 0}
            return all_data[str(user_id)]
    return {'days': [], 'total_salary': 0, 'total_orders': 0}


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
    # Защита от None значений
    salary = salary or 0
    orders_count = orders_count or 0

    existing = next((d for d in user_data['days'] if d['date'] == date), None)

    if existing:
        # Сохраняем старые значения для пересчета
        old_worked = existing.get('worked', False)
        old_salary = existing.get('salary', 0)
        old_orders = existing.get('orders_count', 0)

        # Обновляем поля
        if worked is not None:
            existing['worked'] = worked
        if salary is not None:
            existing['salary'] = salary
        if orders_count is not None:
            existing['orders_count'] = orders_count

        # Пересчитываем итоги
        if worked:  # Если работал
            user_data['total_salary'] = user_data['total_salary'] - old_salary + salary
        else:  # Если не работал
            user_data['total_salary'] = user_data['total_salary'] - old_salary

        user_data['total_orders'] = user_data['total_orders'] - old_orders + orders_count

    else:
        # Создаем новый день
        new_day = {
            'date': date,
            'worked': worked or False,
            'salary': salary,
            'orders_count': orders_count
        }
        user_data['days'].append(new_day)

        # Добавляем к итогам только если работал
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

        # Определяем машину
        if 'Рено' in line or 'рено' in line.lower():
            current_car = 'Рено'
            continue

        if current_car != 'Рено':
            continue

        if not line or re.match(r'^(Фіат|Кадді|Хюндай|Сітроен)', line, re.IGNORECASE):
            continue

        # Парсим время
        time_match = re.search(r'(\d{1,2}\.\d{2})', line)
        if not time_match:
            continue
        time = time_match.group(1)

        # Парсим цену
        price_match = re.search(r'(\d+)грн', line)
        price = int(price_match.group(1)) if price_match else 0

        # Спец: если 'сплачено' и нет цены
        is_prepaid = 'сплачено' in line.lower() and price == 0

        # Описание: всё после времени, до цены (полное)
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
                'is_prepaid': is_prepaid
            }
            orders.append(order)
            if price > 0:
                total += price

    # Обновляем ЗП-дни: добавляем orders_count для сегодня
    zp_data = load_user_data(user_id)
    today = datetime.now().strftime('%d.%m.%Y')
    update_or_add_day(zp_data, today, worked=True, orders_count=len(orders))
    save_user_data(user_id, zp_data)

    user_data[user_id]['orders'] = orders  # Локальное для заказов
    user_data[user_id]['total'] = total
    return orders, total


def get_order_keyboard(user_id):
    """Клавиатура для выбора заказа"""
    if 'orders' not in user_data[user_id]:
        return None
    orders = user_data[user_id]['orders']
    markup = InlineKeyboardMarkup()
    for i, order in enumerate(orders):
        status = "✅" if order['payment'] else "⭕"
        price_text = 'сплачено' if order['is_prepaid'] else f"{order['price']} грн"
        btn_text = f"{status} {order['time']} - {price_text}"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"order_{i}"))
    markup.add(InlineKeyboardButton("📊 Показать отчёт", callback_data="report_text"))
    markup.add(InlineKeyboardButton("🔄 Перепарсить", callback_data="reparse"))
    return markup


def get_payment_keyboard(order_idx):
    """Клавиатура для оплаты заказа"""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Оплата на карту", callback_data=f"pay_card_{order_idx}"))
    markup.add(InlineKeyboardButton("💵 Наличные", callback_data=f"pay_cash_{order_idx}"))
    markup.add(InlineKeyboardButton("💵 Наличные со сдачей", callback_data=f"pay_cash_change_{order_idx}"))
    markup.add(InlineKeyboardButton("👥 У другого", callback_data=f"pay_other_{order_idx}"))
    markup.add(InlineKeyboardButton("⬅️ Назад к заказам", callback_data="back_orders"))
    return markup


@bot.message_handler(commands=['start'])
def start(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("📋 Скинь расписание"))
    markup.add(KeyboardButton("🟢 Отметиться на смену"))
    markup.add(KeyboardButton("🔴 Смены нет"))
    markup.add(KeyboardButton("💰 Добавить день ЗП"))
    markup.add(KeyboardButton("📊 Отчёт по ЗП"))
    markup.add(KeyboardButton("📊 Показать отчёт"))
    bot.send_message(message.chat.id,
                     "🤖 Бот для учёта заказов Рено\n\n"
                     "📋 Скинь расписание — парсит заказы.\n"
                     "🟢/🔴 — отметка смены (с ЗП).\n"
                     "💰 Добавить день ЗП — для прошлого дня.\n"
                     "📊 Отчёт по ЗП — сумма за период + заказы.\n"
                     "📊 Показать отчёт — по заказам дня.",
                     reply_markup=markup)


@bot.message_handler(func=lambda msg: msg.text == "📋 Скинь расписание")
def handle_schedule(message):
    bot.send_message(message.chat.id,
                     "📝 Отправь расписание (только Рено часть).")
    bot.register_next_step_handler(message, process_schedule)


@bot.message_handler(func=lambda msg: msg.text == "🟢 Отметиться на смену")
def mark_work_on(message):
    user_id = message.chat.id
    zp_data = load_user_data(user_id)
    today = datetime.now().strftime('%d.%m.%Y')
    update_or_add_day(zp_data, today, worked=True)
    save_user_data(user_id, zp_data)
    msg = bot.send_message(user_id, "💰 Введи твою ЗП за смену (грн):")
    bot.register_next_step_handler(msg, process_salary)


def process_salary(message):
    user_id = message.chat.id
    try:
        salary = int(message.text)
        zp_data = load_user_data(user_id)
        today = datetime.now().strftime('%d.%m.%Y')
        update_or_add_day(zp_data, today, salary=salary)
        save_user_data(user_id, zp_data)
        bot.send_message(user_id, f"✅ Отмечено: работаешь сегодня! ЗП: {salary} грн.")
    except ValueError:
        bot.send_message(user_id, "❌ Введи число! Заново.")
        msg = bot.send_message(user_id, "💰 Введи твою ЗП за смену (грн):")
        bot.register_next_step_handler(msg, process_salary)


@bot.message_handler(func=lambda msg: msg.text == "🔴 Смены нет")
def mark_work_off(message):
    user_id = message.chat.id
    zp_data = load_user_data(user_id)
    today = datetime.now().strftime('%d.%m.%Y')
    update_or_add_day(zp_data, today, worked=False, salary=0)
    save_user_data(user_id, zp_data)
    bot.send_message(user_id, "❌ Отмечено: смены нет сегодня.")


@bot.message_handler(func=lambda msg: msg.text == "💰 Добавить день ЗП")
def add_zp_day(message):
    user_id = message.chat.id
    msg = bot.send_message(user_id, "📅 Введи дату (ДД.ММ.ГГГГ):")
    bot.register_next_step_handler(msg, process_add_date)


def process_add_date(message):
    user_id = message.chat.id
    date = message.text.strip()
    if not re.match(r'\d{2}\.\d{2}\.\d{4}', date):
        bot.send_message(user_id, "❌ Неверный формат! ДД.ММ.ГГГГ. Заново.")
        msg = bot.send_message(user_id, "📅 Введи дату (ДД.ММ.ГГГГ):")
        bot.register_next_step_handler(msg, process_add_date)
        return
    zp_data = load_user_data(user_id)
    update_or_add_day(zp_data, date)
    save_user_data(user_id, zp_data)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🟢 Да, работал", callback_data=f"zp_worked_yes_{date}"))
    markup.add(InlineKeyboardButton("🔴 Нет", callback_data=f"zp_worked_no_{date}"))
    bot.send_message(user_id, f"📅 День {date}: Работал?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('zp_worked_'))
def handle_zp_worked(call):
    user_id = call.message.chat.id
    parts = call.data.split('_')
    date = parts[3]  # zp_worked_yes_01.01.2024
    worked = parts[2] == 'yes'
    bot.answer_callback_query(call.id, f"Отмечено: {'работал' if worked else 'не работал'}")
    if worked:
        msg = bot.send_message(user_id, f"💰 ЗП за {date} (грн):")
        bot.register_next_step_handler(msg, lambda m: process_zp_salary(m, user_id, date))
    else:
        zp_data = load_user_data(user_id)
        update_or_add_day(zp_data, date, worked=False, salary=0)
        save_user_data(user_id, zp_data)
        bot.send_message(user_id, f"✅ День {date}: Не работал, ЗП: 0 грн.")


def process_zp_salary(message, user_id, date):
    try:
        salary = int(message.text)
        zp_data = load_user_data(user_id)
        update_or_add_day(zp_data, date, salary=salary)
        save_user_data(user_id, zp_data)
        bot.send_message(user_id, f"✅ День {date}: ЗП {salary} грн.")
    except ValueError:
        bot.send_message(user_id, "❌ Введи число! Заново.")
        msg = bot.send_message(user_id, f"💰 ЗП за {date} (грн):")
        bot.register_next_step_handler(msg, lambda m: process_zp_salary(m, user_id, date))


@bot.message_handler(func=lambda msg: msg.text == "📊 Отчёт по ЗП")
def zp_report(message):
    user_id = message.chat.id
    zp_data = load_user_data(user_id)

    # Сортируем дни по дате
    days = sorted(zp_data['days'], key=lambda d: datetime.strptime(d['date'], '%d.%m.%Y'))

    report = f"📊 ОТЧЁТ ПО ЗП (все дни)\n\n"
    report += f"💰 Суммарная ЗП: {zp_data['total_salary']} грн\n"
    report += f"📦 Общее заказов: {zp_data['total_orders']}\n\n"

    for day in days:
        status = '🟢 ДА' if day['worked'] else '🔴 НЕТ'
        salary_str = f"{day['salary']} грн" if day['worked'] and day['salary'] > 0 else '0 грн'
        orders_str = f"{day['orders_count']} заказов" if day['orders_count'] > 0 else '0 заказов'
        report += f"{day['date']}: {status} | ЗП: {salary_str} | {orders_str}\n"

    if len(report) > 4000:
        parts = [report[i:i + 4000] for i in range(0, len(report), 4000)]
        for part in parts:
            bot.send_message(user_id, part)
    else:
        bot.send_message(user_id, report)


def process_schedule(message):
    user_id = message.chat.id
    try:
        orders, total = parse_schedule(message.text, user_id)
        if not orders:
            bot.send_message(user_id, "❌ Не нашёл заказы для Рено. Проверь формат.")
            return

        # Показываем что распарсили (полное desc)
        preview = f"✅ Распарсил {len(orders)} заказов. Общая сумма: {total} грн\n\n"
        for i, order in enumerate(orders, 1):
            price_text = 'сплачено' if order['is_prepaid'] else f"{order['price']} грн"
            preview += f"{i}. {order['time']} - {price_text}\n"
            preview += f"   📝 {order['desc']}\n\n"

        bot.send_message(user_id, preview)
        send_order_menu(user_id)

    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка парсинга: {e}")


def send_order_menu(user_id):
    markup = get_order_keyboard(user_id)
    if markup:
        bot.send_message(user_id, "🎯 Выбери заказ для отметки оплаты:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('order_'))
def handle_order(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "Сначала скинь расписание!")
        return

    orders = user_data[user_id]['orders']
    order_idx = int(call.data.split('_')[1])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "Заказ не найден!")
        return

    order = orders[order_idx]

    status = f" | ✅ {order['payment']}" if order['payment'] else ""
    tips_text = f" | ☕ +{order['tips']} грн" if order['tips'] > 0 else ""
    change_text = f" | 💰 сдача {order['change']} грн" if order['change'] > 0 else ""
    price_text = 'сплачено' if order['is_prepaid'] else f"{order['price']} грн"

    text = (f"🕒 {order['time']}{status}{tips_text}{change_text}\n"
            f"💰 {price_text}\n"
            f"📝 {order['desc']}\n\n"
            f"Отметить оплату:")

    bot.edit_message_text(text, user_id, call.message.message_id,
                          reply_markup=get_payment_keyboard(order_idx))


@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_card_'))
def pay_card(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "❌ Сначала скинь расписание!")
        return

    orders = user_data[user_id]['orders']
    order_idx = int(call.data.split('_')[2])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "❌ Заказ не найден!")
        return

    order = orders[order_idx]
    order['payment'] = 'Карта'
    order['received'] = order['price'] if not order['is_prepaid'] else 0
    order['given_amount'] = order['price'] if not order['is_prepaid'] else 0
    order['change'] = 0

    bot.answer_callback_query(call.id, "✅ Оплата картой отмечена!")
    send_order_menu(user_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_cash_'))
def pay_cash(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "❌ Сначала скинь расписание!")
        return

    orders = user_data[user_id]['orders']

    if 'change' in call.data:
        order_idx = int(call.data.split('_')[3])
    else:
        order_idx = int(call.data.split('_')[2])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "❌ Заказ не найден!")
        return

    order = orders[order_idx]

    if 'change' in call.data:
        price_for_msg = order['price'] if not order['is_prepaid'] else 0
        msg = bot.send_message(user_id, f"💵 Введи полученную сумму наличными (цена {price_for_msg} грн):")
        bot.register_next_step_handler(msg, lambda m: process_cash_payment_with_change(m, user_id, order_idx))
    else:
        price_for_msg = order['price'] if not order['is_prepaid'] else 0
        msg = bot.send_message(user_id, f"💵 Введи полученную сумму наличными (цена {price_for_msg} грн):")
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

        order['payment'] = 'Наличные'
        order['given_amount'] = given_amount
        order['received'] = order['price'] if not order['is_prepaid'] else 0
        order['change'] = 0

        if not order['is_prepaid'] and given_amount > order['price']:
            tips = given_amount - order['price']
            order['tips'] = tips
            msg = bot.send_message(user_id, f"☕ Это чай: {tips} грн. Введи количество людей для деления:")
            bot.register_next_step_handler(msg, lambda m: process_tip_people(m, user_id, order_idx, tips))
            return
        else:
            bot.send_message(user_id, f"✅ Оплата наличными: {given_amount} грн")

    except ValueError:
        bot.send_message(user_id, "❌ Ошибка! Введи число.")
        return

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
        bot.send_message(user_id, f"☕ Чай {tips} грн → по {order['tips_per']} грн на {num_people} чел.")
    except ValueError:
        bot.send_message(user_id, "❌ Введи положительное число! Заново.")
        msg = bot.send_message(user_id, f"Введи количество людей для деления чая {tips} грн:")
        bot.register_next_step_handler(msg, lambda m: process_tip_people(m, user_id, order_idx, tips))
        return
    send_order_menu(user_id)


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
            bot.send_message(user_id, f"❌ Сумма меньше цены ({order['price']} грн)!")
            return

        change = given_amount - (order['price'] if not order['is_prepaid'] else 0)

        order['payment'] = 'Наличные (со сдачей)'
        order['given_amount'] = given_amount
        order['received'] = order['price'] if not order['is_prepaid'] else 0
        order['change'] = change
        order['tips'] = 0

        bot.send_message(user_id,
                         f"✅ Оплата наличными: {given_amount} грн\n"
                         f"💰 Стоимость: {order['received']} грн\n"
                         f"🪙 Сдача: {change} грн\n"
                         f"💸 К отдаче клиенту: {change} грн")

    except ValueError:
        bot.send_message(user_id, "❌ Ошибка! Введи число.")
        return

    send_order_menu(user_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_other_'))
def pay_other(call):
    user_id = call.message.chat.id
    if 'orders' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "❌ Сначала скинь расписание!")
        return

    orders = user_data[user_id]['orders']
    order_idx = int(call.data.split('_')[2])

    if order_idx >= len(orders):
        bot.answer_callback_query(call.id, "❌ Заказ не найден!")
        return

    msg = bot.send_message(user_id, "👥 Введи имя человека, у которого расчёт:")
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

    bot.send_message(user_id, f"✅ Отмечено: расчёт у {name}")
    send_order_menu(user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'back_orders')
def back_to_orders(call):
    user_id = call.message.chat.id
    send_order_menu(user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'report_text')
@bot.message_handler(func=lambda msg: msg.text == "📊 Показать отчёт")
def show_report(message_or_call):
    if isinstance(message_or_call, telebot.types.CallbackQuery):
        user_id = message_or_call.message.chat.id
    else:
        user_id = message_or_call.chat.id

    if 'orders' not in user_data[user_id] or not user_data[user_id]['orders']:
        bot.send_message(user_id, "📭 Нет добавленных заказов")
        return

    orders = user_data[user_id]['orders']
    orders.sort(key=lambda x: x['time'])

    total_price = sum(order['price'] for order in orders if not order['is_prepaid'])
    total_received = sum(order['received'] for order in orders)
    total_tips = sum(order['tips'] for order in orders)
    prepaid_count = sum(1 for order in orders if order['is_prepaid'])

    # Получаем данные о сегодняшней смене
    zp_data = load_user_data(user_id)
    today = datetime.now().strftime('%d.%m.%Y')
    today_data = next((d for d in zp_data['days'] if d['date'] == today), None)
    work_today = today_data['worked'] if today_data else False
    salary = today_data['salary'] if today_data else 0

    # Формируем отчёт
    report = f"📊 ОТЧЁТ ЗА {today}\n\n"
    report += f"💰 Общая сумма: {total_price} грн ({prepaid_count} сплачено заранее)\n"
    report += f"✅ Получено: {total_received} грн\n"
    report += f"☕ Чаевые: {total_tips} грн\n\n"

    for order in orders:
        status = "✅" if order['payment'] else "❌"
        if order['is_prepaid']:
            payment_info = order['payment'] or 'Сплачено'
            report += f"📍 {order['time']} | Сплачено {status}\n"
            report += f"   💰 {payment_info}\n"
        else:
            payment_info = order['payment'] or 'Не оплачен'
            report += f"📍 {order['time']} | {order['price']} грн {status}\n"
            report += f"   💰 {payment_info}\n"

            if order['given_amount'] > 0 and order['payment'] and 'налич' in order['payment'].lower():
                dali = order['given_amount']
                report += f"   💵 Дали: {dali} грн | Оплата: {order['price']} грн"
                if order['change'] > 0:
                    report += f" | Сдача: {order['change']} грн"
                report += "\n"

        if order['tips'] > 0:
            report += f"   ☕ Чай: {order['tips']} грн ({order['tips_per']} грн/чел на {order['tip_people']} чел)\n"

        report += f"   📝 {order['desc']}\n\n"

    if total_tips > 0:
        report += "\n📈 ДЕТАЛИ ПО ЧАЕВЫМ:\n"
        for order in orders:
            if order['tips'] > 0:
                report += f"• {order['time']}: {order['tips']} грн = по {order['tips_per']} грн на {order['tip_people']} чел\n"

    # Раздел с твоей сменой
    report += "\n" + "=" * 30 + "\n"
    if work_today:
        report += f"🟢 Твоя смена: ДА | ЗП: {salary} грн\n"
    else:
        report += "🔴 Твоя смена: НЕТ\n"

    if len(report) > 4000:
        parts = [report[i:i + 4000] for i in range(0, len(report), 4000)]
        for part in parts:
            bot.send_message(user_id, part)
    else:
        bot.send_message(user_id, report)


@bot.callback_query_handler(func=lambda call: call.data == 'reparse')
def reparse_schedule(call):
    user_id = call.message.chat.id
    bot.send_message(user_id, "Скинь расписание ещё раз:")
    bot.register_next_step_handler(call.message, process_schedule)


if __name__ == '__main__':
    print("Бот запущен!")
    bot.polling(none_stop=True)