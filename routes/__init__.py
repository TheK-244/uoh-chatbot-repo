from routes.admin_routes import register_admin_routes
from routes.auth_routes import register_auth_routes
from routes.chat_routes import register_chat_routes
from routes.request_routes import register_request_routes
from routes.main_routes import register_main_routes


# يسجل كل مجموعات المسارات داخل تطبيق Flask.
def register_all_routes(app):
    register_main_routes(app)
    register_auth_routes(app)
    register_chat_routes(app)
    register_request_routes(app)
    register_admin_routes(app)
