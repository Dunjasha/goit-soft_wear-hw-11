from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import date, datetime, timedelta
from sqlalchemy import Column, Integer, String, Date, select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import IntegrityError


DATABASE_URL = "postgresql+asyncpg://user:57449@localhost:5432/contacts_db"

engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

app = FastAPI()


class ContactModel(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, unique=True, nullable=False)
    birthday = Column(Date, nullable=False)
    additional_data = Column(String, nullable=True)


class Contact(BaseModel):
    first_name: str = Field(..., example="Іван")
    last_name: str = Field(..., example="Іванов")
    email: EmailStr = Field(..., example="ivan.ivanov@example.com")
    phone: str = Field(..., example="+380501234567")
    birthday: date = Field(..., example="1990-05-21")
    additional_data: Optional[str] = Field(None, example="Колега по роботі")

    class Config:
        orm_mode = True

class ContactUpdate(Contact):
    pass

class ContactResponse(Contact):
    id: int


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with SessionLocal() as session:
        yield session


async def check_unique(db: AsyncSession, email: str, phone: str, exclude_id: Optional[int] = None):
    query = select(ContactModel).where(
        or_(
            ContactModel.email == email,
            ContactModel.phone == phone
        )
    )
    if exclude_id:
        query = query.where(ContactModel.id != exclude_id)

    result = await db.execute(query)
    existing = result.scalars().first()
    if existing:
        if existing.email == email:
            raise HTTPException(status_code=400, detail="Email вже використовується")
        if existing.phone == phone:
            raise HTTPException(status_code=400, detail="Телефон вже використовується")


@app.post("/contacts/", response_model=ContactResponse)
async def create_contact(contact: Contact, db: AsyncSession = Depends(get_db)):
    await check_unique(db, contact.email, contact.phone)

    new_contact = ContactModel(**contact.dict())
    db.add(new_contact)
    await db.commit()
    await db.refresh(new_contact)
    return new_contact


@app.get("/contacts/", response_model=List[ContactResponse])
async def list_contacts(search: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(ContactModel)
    if search:
        like = f"%{search}%"
        query = query.where(or_(
            ContactModel.first_name.ilike(like),
            ContactModel.last_name.ilike(like),
            ContactModel.email.ilike(like)
        ))

    result = await db.execute(query)
    return result.scalars().all()


@app.get("/contacts/{contact_id}", response_model=ContactResponse)
async def get_contact(contact_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContactModel).where(ContactModel.id == contact_id))
    contact = result.scalar()
    if not contact:
        raise HTTPException(status_code=404, detail="Контакт не знайдено")
    return contact


@app.put("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact(contact_id: int, updated: ContactUpdate, db: AsyncSession = Depends(get_db)):
    await check_unique(db, updated.email, updated.phone, exclude_id=contact_id)

    result = await db.execute(select(ContactModel).where(ContactModel.id == contact_id))
    contact = result.scalar()
    if not contact:
        raise HTTPException(status_code=404, detail="Контакт не знайдено")

    for key, value in updated.dict().items():
        setattr(contact, key, value)

    await db.commit()
    await db.refresh(contact)
    return contact


@app.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContactModel).where(ContactModel.id == contact_id))
    contact = result.scalar()
    if not contact:
        raise HTTPException(status_code=404, detail="Контакт не знайдено")

    await db.delete(contact)
    await db.commit()


@app.get("/contacts/upcoming-birthdays/", response_model=List[ContactResponse])
async def upcoming_birthdays(db: AsyncSession = Depends(get_db)):
    today = date.today()
    in_seven_days = today + timedelta(days=7)

    result = await db.execute(select(ContactModel))
    contacts = result.scalars().all()

    upcoming = []
    for contact in contacts:
        bday = contact.birthday.replace(year=today.year)
        if today <= bday <= in_seven_days:
            upcoming.append(contact)

    return upcoming

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)