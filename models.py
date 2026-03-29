from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

user_pages = db.Table('user_pages',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('page_id', db.Integer, db.ForeignKey('page.id'), primary_key=True)
)

class Page(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    endpoint = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return self.name

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(250), nullable=False)

    def __repr__(self):
        return f"<{self.key}: {self.value}>"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    first_name = db.Column(db.String(150), nullable=False)
    last_name = db.Column(db.String(150), nullable=False)
    site_source = db.Column(db.String(10), nullable=False)
    site_destination = db.Column(db.String(10), nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)
    pages = db.relationship('Page', secondary=user_pages, lazy='subquery',
        backref=db.backref('users', lazy=True))


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_type = db.Column(db.String(50), nullable=False)
    dma_ref = db.Column(db.String(100), nullable=True)
    dma_rev = db.Column(db.String(50), nullable=True)
    option = db.Column(db.String(500), nullable=True, default='-')
    status = db.Column(db.String(20), default='QUEUED')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('jobs', lazy=True))
