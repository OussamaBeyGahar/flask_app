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
    PY_CHECK_BAT_CONTRACT = os.environ.get('PY_CHECK_BAT_CONTRACT', r'\\nasbobcat\bobcat\projects\check_BAT_contract\check_BAT_contract.py')
    PREPROCESSING_REPORT = os.environ.get('PREPROCESSING_REPORT', r'\\nasbobcat\bobcat\data\PREPROCESSING\REPORT')
    SHARE_SPOOL = os.environ.get('SHARE_SPOOL', r'\\nasbobcat\bobcat\data\Spool')
    EXPORT_TOOL_DB = os.environ.get('EXPORT_TOOL_DB', r'c:\projects\ExportTool\database\export_tools.db')
    SHARE_STANDARD_WORKING = os.environ.get('SHARE_STANDARD_WORKING', r'\\nasbobcat\bobcat\data\PBS_CRL.working')
    SHARE_ALTERNATE_WORKING = os.environ.get('SHARE_ALTERNATE_WORKING', r'\\nasbobcat\bobcat\data\AlternateWorking')
    PROXY_PATH_FOR_PICKLE_1 = os.environ.get('PROXY_PATH_FOR_PICKLE_1', r'\\nasbobcat\bobcat\data')
    PROXY_PATH_FOR_PICKLE_2 = os.environ.get('PROXY_PATH_FOR_PICKLE_2', r'\\nasbobcat\bobcat\data')
    SHARE_DELTA = os.environ.get('SHARE_DELTA', r'\\nasbobcat\bobcat\data\Delta')
    SHARE_TCRA_OUT = os.environ.get('SHARE_TCRA_OUT', r'\\nasbobcat\bobcat\data\TCRA_OUT')
    SHARE_DELTA_TCRA_OUT = os.environ.get('SHARE_DELTA_TCRA_OUT', r'\\nasbobcat\bobcat\data\DeltaTCRA_OUT')
    SHARE_DELTA_TCRA_DMA_OUT = os.environ.get('SHARE_DELTA_TCRA_DMA_OUT', r'\\nasbobcat\bobcat\data\DeltaTCRA_DMA_OUT')
    PY_DELTA_4_INDUS = os.environ.get('PY_DELTA_4_INDUS', r'\\nasbobcat\bobcat\projects\delta_4_indus\delta_4_indus.py')
    SHARE_DELTA_TCRA_ENG_OUT = os.environ.get('SHARE_DELTA_TCRA_ENG_OUT', r'\\nasbobcat\bobcat\data\DeltaTCRA_ENG_OUT')
    EXE_DELTATCENG = os.environ.get('EXE_DELTATCENG', r'\\nasbobcat\bobcat\projects\deltatceng\deltatceng.exe')

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
