from getpass import getpass
from werkzeug.security import generate_password_hash

print("Create admin SQL")
name = input("Name: ").strip() or "Admin"
email = input("Email: ").strip().lower()
password = getpass("Password: ")

if not email or not password:
    raise SystemExit("Email and password are required.")

password_hash = generate_password_hash(password)
print("\nRun this SQL in phpMyAdmin/MySQL after schema_update.sql:\n")
print(
    "INSERT INTO users (name, email, password_hash, is_admin) "
    f"VALUES ('{name.replace("'", "''")}', '{email.replace("'", "''")}', '{password_hash}', 1);"
)
