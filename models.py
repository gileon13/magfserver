import smtplib

def check_smtp_ssl_connection(host, port, username=None, password=None):
    try:
        with smtplib.SMTP_SSL(host, port, timeout=10) as server:
            print(f"Соединение с {host}:{port} через SSL установлено.")

            # Если требуется аутентификация
            if username and password:
                server.login(username, password)
                print("Аутентификация успешна.")
    except smtplib.SMTPAuthenticationError:
        print("Ошибка аутентификации. Проверьте логин и пароль.")
    except smtplib.SMTPConnectError:
        print(f"Не удалось подключиться к серверу {host}:{port}.")
    except smtplib.SMTPException as e:
        print(f"Ошибка SMTP: {e}")
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
# Проверяем соединение
host = 'smtp.yandex.ru'
port = 465
username = 'ard.vkr@yandex.com'
password = 'cwtbvrjbmzcjcttc'

check_smtp_ssl_connection(host, port, username, password)
