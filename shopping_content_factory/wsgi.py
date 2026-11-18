"""운영용 WSGI 진입점: gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app"""
from app import create_app

app = create_app()
