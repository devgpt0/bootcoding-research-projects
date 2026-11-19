from sqlalchemy import Column, Integer, String
from database import Base

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer,primary_key=True, index=True)
    name = Column(String, index=True)
    phone_number = Column(String, index=True)
