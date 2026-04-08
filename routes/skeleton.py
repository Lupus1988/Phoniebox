from flask import Blueprint

from .library import register_library_routes
from .player import player_bp

ui_bp = Blueprint("ui", __name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")


def register_blueprints(app):
    app.register_blueprint(player_bp)
    register_library_routes(app)
