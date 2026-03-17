import os
import socket

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your_secret_key_here')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'database.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PROXY_QUERY = os.environ.get('PROXY_QUERY', 'http://wbel200400203.next.loc:8001/a?b')
    HOST = socket.gethostname()

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'test_database.db')

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    # In production, make sure to set SECRET_KEY and DATABASE_URL in environment

config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
