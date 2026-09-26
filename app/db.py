"""Real database connection, using your Supabase Postgres URL.
Every route imports get_db() from here instead of the TODO comments
that were in the original scaffold.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
 
DATABASE_URL = os.getenv("DATABASE_URL")
 
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to your .env locally, or to "
        "your Render environment variables in production. It should look "
        "like: postgresql://postgres:[password]@[host]:5432/postgres "
        "(copy this from Supabase: Project Settings > Database > Connection string)"
    )
 
# Supabase requires SSL; this handles it automatically for the postgresql:// scheme.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
 
 
def get_db():
    """FastAPI dependency - yields a DB session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
 
