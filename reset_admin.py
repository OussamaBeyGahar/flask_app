from app import app
from models import db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    admin = User.query.filter_by(username='admin').first()
    if admin:
        admin.password = generate_password_hash('azerty')
        db.session.commit()
        print('Admin password reset successfully')
    else:
        print('Admin user not found')
