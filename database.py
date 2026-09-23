from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import yaml

Base = declarative_base()

class Article(Base):
    __tablename__ = 'articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), unique=True, nullable=False)
    source = Column(String(50), nullable=False)
    published_date = Column(DateTime)
    summary = Column(Text)
    full_text = Column(Text)
    relevance_score = Column(Float, default=0.0)
    read_status = Column(Boolean, default=False)
    tags = Column(String(500))
    area = Column(String(40))           # exactly one; see classifier.AREAS
    importance = Column(Float)          # None when only keyword-scored
    why = Column(Text)                  # one-line editorial justification
    first_seen = Column(DateTime)       # when WE first stored it, not when published
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db(db_path="articles.db"):
    engine = create_engine(f'sqlite:///{db_path}')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def load_config():
    with open('config.yaml', 'r') as f:
        return yaml.safe_load(f)
