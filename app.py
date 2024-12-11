from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import sqlite3
from datetime import datetime, timedelta
import pytz
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading

SMTP_SERVER = 'smtp.yandex.ru'  # Замените на ваш SMTP-сервер
SMTP_PORT = 465
SMTP_USERNAME = 'ard.vkr@yandex.com'
SMTP_PASSWORD = 'cwtbvrjbmzcjcttc'
#RECIPIENT_EMAILS = ['gorbunov@sibstrin.ru'] # добавлять через, 'gileon13@yandex.ru']
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Замените на ваш секретный ключ

# Функция для создания таблицы с новыми полями для трех температур DS18B20, состояния геркона и уровня воды
def init_db():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS email_recipients (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     email TEXT UNIQUE NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS sensor_data (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 temperature_dht REAL,
                 humidity REAL,
                 temperature_ds18b20_1 REAL,
                 temperature_ds18b20_2 REAL,
                 temperature_ds18b20_3 REAL,
                 reed_state INTEGER,           -- Поле для состояния геркона
                 water_level INTEGER,          -- Поле для уровня воды
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS users (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     username TEXT UNIQUE NOT NULL,
                     password TEXT NOT NULL)''')


    # Добавление пользователя по умолчанию (имя: admin, пароль: password)
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                  ('admin', generate_password_hash('password')))
    except sqlite3.IntegrityError:
        pass  # Если пользователь уже существует

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     notifications_enabled INTEGER DEFAULT 1,
                     min_temp REAL DEFAULT 16,
                     max_temp REAL DEFAULT 23,
                     min_temp_ds18b20_1 REAL DEFAULT 16,
                     max_temp_ds18b20_1 REAL DEFAULT 23,
                     min_temp_ds18b20_2 REAL DEFAULT 16,
                     max_temp_ds18b20_2 REAL DEFAULT 23,
                     min_temp_ds18b20_3 REAL DEFAULT 16,
                     max_temp_ds18b20_3 REAL DEFAULT 23)''')

    # Добавление строки настроек по умолчанию
    c.execute('''INSERT OR IGNORE INTO settings 
                    (id, notifications_enabled, min_temp, max_temp, 
                     min_temp_ds18b20_1, max_temp_ds18b20_1, 
                     min_temp_ds18b20_2, max_temp_ds18b20_2, 
                     min_temp_ds18b20_3, max_temp_ds18b20_3) 
                    VALUES (1, 1, 16, 23, 16, 23, 16, 23, 16, 23)''')

    c.execute('''CREATE TABLE IF NOT EXISTS sent_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')


    conn.commit()
    conn.close()


def get_device_status():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT timestamp FROM sensor_data ORDER BY timestamp DESC LIMIT 1")
    last_entry = c.fetchone()

    # Проверка последнего отправленного уведомления о статусе устройства
    c.execute("SELECT timestamp FROM sent_notifications WHERE id = (SELECT MAX(id) FROM sent_notifications)")
    last_notification = c.fetchone()
    conn.close()

    last_notification_time = datetime.strptime(last_notification[0], '%Y-%m-%d %H:%M:%S') if last_notification else None

    if last_entry:
        last_timestamp = datetime.strptime(last_entry[0], '%Y-%m-%d %H:%M:%S')
        current_time = datetime.now()

        # Определяем статус как подключено, если прошло меньше 60 секунд с последнего обновления
        if (current_time - last_timestamp).total_seconds() <= 60:
            return 'Подключено'

    # Если устройство не подключено
    if last_notification_time is None or (datetime.now() - last_notification_time).total_seconds() > 60:  # Раз в 60 сек
        send_email_in_thread(
            "Device Disconnection Alert",
            "Устройство отключено! Проверить соединение немедленно."
        )

    return 'Не подключено'


# Глобальный счетчик отправленных уведомлений
import time

def can_send_notification():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    # Получаем временные метки сообщений, отправленных за последние 5 мин
    one_minute_ago = datetime.now() - timedelta(minutes=5)
    c.execute('''SELECT timestamp FROM sent_notifications WHERE timestamp > ?''',
              (one_minute_ago.strftime('%Y-%m-%d %H:%M:%S'),))
    recent_notifications = c.fetchall()
    conn.close()

    # Проверяем, что сообщений не больше 3 за последн 5 мин
    if len(recent_notifications) >= 3:
        return False
    return True




def send_email_alert(subject, message):
    # Проверяем, можно ли отправить уведомление
    if not can_send_notification():
        print("Notification frequency limit reached. Email not sent.")
        return  # Лимит частоты уведомлений достигнут

    # Отправляем уведомление
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT email FROM email_recipients")
    recipient_emails = [row[0] for row in c.fetchall()]
    conn.close()

    for email in recipient_emails:
        try:
            msg = MIMEMultipart()
            msg['From'] = SMTP_USERNAME
            msg['To'] = email
            msg['Subject'] = subject
            msg.attach(MIMEText(message, 'plain'))

            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

            print(f"Email sent successfully to {email}!")

            # Записываем время отправки уведомления в базу данных
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("INSERT INTO sent_notifications (timestamp) VALUES (?)",
                      (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Failed to send email to {email}: {e}")






def send_email_in_thread(subject, message):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT notifications_enabled FROM settings WHERE id = 1")
    notifications_enabled = c.fetchone()[0]
    conn.close()

    if notifications_enabled:
        thread = threading.Thread(target=send_email_alert, args=(subject, message))
        thread.start()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Проверка пользователя в базе данных
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[0], password):
            session['username'] = username  # Устанавливаем сессию пользователя
            return redirect(url_for('index'))
        else:
            return 'Неверное имя пользователя или пароль', 401

    return render_template('login.html')


# Маршрут для выхода
@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


# Декоратор для проверки авторизации
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    decorated_function.__name__ = f.__name__
    return decorated_function

@app.route('/data', methods=['POST'])
def receive_data():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data received'}), 400

    # Получение данных из запроса
    temperature_dht = data.get('temperature_dht')
    humidity = data.get('humidity')
    temp_ds18b20_1 = data.get('temperature_ds18b20_1')
    temp_ds18b20_2 = data.get('temperature_ds18b20_2')
    temp_ds18b20_3 = data.get('temperature_ds18b20_3')
    reed_state = data.get('reed_state')  # Состояние геркона
    water_level = data.get('water_level')  # Показания уровня воды

    # Генерация времени с учетом локального часового пояса
    tz = pytz.timezone("Asia/Novosibirsk")  # Замените на ваш часовой пояс
    local_time = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')


    # Подключение к базе данных
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    # Удаление данных старше 7 дней
    seven_days_ago = datetime.now() - timedelta(days=7)
    c.execute("DELETE FROM sensor_data WHERE timestamp < ?", (seven_days_ago.strftime('%Y-%m-%d %H:%M:%S'),))

    c.execute('''SELECT notifications_enabled, min_temp, max_temp, 
                             min_temp_ds18b20_1, max_temp_ds18b20_1, 
                             min_temp_ds18b20_2, max_temp_ds18b20_2, 
                             min_temp_ds18b20_3, max_temp_ds18b20_3 
                      FROM settings WHERE id = 1''')
    settings = c.fetchone()
    notifications_enabled = settings[0]
    min_temp, max_temp = settings[1], settings[2]
    min_temp_ds18b20_1, max_temp_ds18b20_1 = settings[3], settings[4]
    min_temp_ds18b20_2, max_temp_ds18b20_2 = settings[5], settings[6]
    min_temp_ds18b20_3, max_temp_ds18b20_3 = settings[7], settings[8]

    # Сохранение новых данных, включая уровень воды
    c.execute('''INSERT INTO sensor_data (
                 temperature_dht, humidity, temperature_ds18b20_1, 
                 temperature_ds18b20_2, temperature_ds18b20_3, reed_state, water_level, timestamp) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (temperature_dht, humidity, temp_ds18b20_1, temp_ds18b20_2, temp_ds18b20_3, reed_state, water_level, local_time))
    conn.commit()



    conn.close()

    if notifications_enabled:
        # Проверка температуры DHT
        if temperature_dht is not None:
            if temperature_dht <= min_temp or temperature_dht >= max_temp:
                send_email_in_thread(
                    "DHT Temperature Alert",
                    f"Temperature (DHT) is {temperature_dht}°C at {local_time}."
                )

    # Проверка температуры DS18B20 #1
        if temp_ds18b20_1 is not None:
            if temp_ds18b20_1 < min_temp_ds18b20_1 or temp_ds18b20_1 > max_temp_ds18b20_1:
                send_email_in_thread(
                    "DS18B20 #1 Temperature Alert",
                    f"Temperature (DS18B20 #1) is {temp_ds18b20_1}°C at {local_time}."
                )
    # Проверка температуры DS18B20 #2
        if temp_ds18b20_2 is not None:
            if temp_ds18b20_2 < min_temp_ds18b20_2 or temp_ds18b20_2 > max_temp_ds18b20_2:
                send_email_in_thread(
                    "DS18B20 #2 Temperature Alert",
                    f"Temperature (DS18B20 #2) is {temp_ds18b20_2}°C at {local_time}."
                )

                # Проверка температуры DS18B20 #3
        if temp_ds18b20_3 is not None:
            if temp_ds18b20_3 < min_temp_ds18b20_3 or temp_ds18b20_3 > max_temp_ds18b20_3:
                send_email_in_thread(
                    "DS18B20 #3 Temperature Alert",
                    f"Temperature (DS18B20 #3) is {temp_ds18b20_3}°C at {local_time}."
                    )


        if water_level is not None and water_level >= 150:
            send_email_in_thread(
                "Water Level Alert",
                f"Water level is critically high ({water_level}) at {local_time}."
            )

        if reed_state is not None and reed_state == 0:
            send_email_in_thread(
                "Reed Switch Alert",
                f"The reed switch is open at {local_time}. Check the device immediately."
            )



    return jsonify({'status': 'success'}), 200

@app.route('/data', methods=['GET'])
def get_data():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM sensor_data")
    data = c.fetchall()
    conn.close()
    return jsonify(data)


@app.route('/status', methods=['GET'])
def device_status():
    status = get_device_status()
    return jsonify({'device_status': status})

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    if request.method == 'POST':
        # Получение значений из формы
        notifications_enabled = 1 if 'notifications_enabled' in request.form else 0
        min_temp = float(request.form.get('min_temp', 5))
        max_temp = float(request.form.get('max_temp', 35))

        min_temp_ds18b20_1 = float(request.form.get('min_temp_ds18b20_1', 5))
        max_temp_ds18b20_1 = float(request.form.get('max_temp_ds18b20_1', 35))

        min_temp_ds18b20_2 = float(request.form.get('min_temp_ds18b20_2', 5))
        max_temp_ds18b20_2 = float(request.form.get('max_temp_ds18b20_2', 35))

        min_temp_ds18b20_3 = float(request.form.get('min_temp_ds18b20_3', 5))
        max_temp_ds18b20_3 = float(request.form.get('max_temp_ds18b20_3', 35))

        # Сохранение в базу данных
        c.execute('''UPDATE settings 
                     SET notifications_enabled = ?, 
                         min_temp = ?, max_temp = ?, 
                         min_temp_ds18b20_1 = ?, max_temp_ds18b20_1 = ?, 
                         min_temp_ds18b20_2 = ?, max_temp_ds18b20_2 = ?, 
                         min_temp_ds18b20_3 = ?, max_temp_ds18b20_3 = ? 
                     WHERE id = 1''',
                  (notifications_enabled,
                   min_temp, max_temp,
                   min_temp_ds18b20_1, max_temp_ds18b20_1,
                   min_temp_ds18b20_2, max_temp_ds18b20_2,
                   min_temp_ds18b20_3, max_temp_ds18b20_3))
        conn.commit()
        conn.close()
        return redirect(url_for('settings'))

    # Получение текущих настроек из базы данных
    c.execute('''SELECT notifications_enabled, min_temp, max_temp, 
                         min_temp_ds18b20_1, max_temp_ds18b20_1, 
                         min_temp_ds18b20_2, max_temp_ds18b20_2, 
                         min_temp_ds18b20_3, max_temp_ds18b20_3 
                  FROM settings WHERE id = 1''')
    settings = c.fetchone()
    conn.close()

    # Передача настроек в шаблон
    return render_template('settings.html', settings=settings)

@app.route('/settings/add_email', methods=['POST'])
@login_required
def add_email():
    email = request.form.get('email')
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO email_recipients (email) VALUES (?)", (email,))
        conn.commit()
        conn.close()
        return jsonify({'success': 'Email added successfully'}), 200
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Email already exists'}), 400

@app.route('/settings/delete_email', methods=['POST'])
@login_required
def delete_email():
    email = request.form.get('email')
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("DELETE FROM email_recipients WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    return jsonify({'success': 'Email deleted successfully'}), 200

@app.route('/settings/get_emails', methods=['GET'])
@login_required
def get_emails():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT email FROM email_recipients")
    emails = [row[0] for row in c.fetchall()]
    conn.close()
    return jsonify({'emails': emails}), 200







@app.route('/')
@login_required
def index():
    return render_template('index.html')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
