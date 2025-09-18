
# helper to initialize DB and create a demo admin user
from utils import init_db, create_user
init_db()
ok, msg = create_user("admin", "admin123", "Administrator")
print("Created admin:", ok, msg)
