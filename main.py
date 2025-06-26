from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import date, datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from bson.errors import InvalidId

app = FastAPI()

MONGO_DETAILS = "mongodb+srv://user2008:ninesoft@cluster0.8nyejvu.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = AsyncIOMotorClient(MONGO_DETAILS)
database = client.contacts_db
contacts_collection = database.get_collection("contacts")


def contact_helper(contact) -> dict:
    return {
        "id": str(contact["_id"]),
        "first_name": contact["first_name"],
        "last_name": contact["last_name"],
        "email": contact["email"],
        "phone": contact["phone"],
        "birthday": contact["birthday"].date() if "birthday" in contact else None,
        "additional_data": contact.get("additional_data"),
    }


class Contact(BaseModel):
    first_name: str = Field(..., example="Іван")
    last_name: str = Field(..., example="Іванов")
    email: EmailStr = Field(..., example="ivan.ivanov@example.com")
    phone: str = Field(..., example="+380501234567")
    birthday: date = Field(..., example="1990-05-21")
    additional_data: Optional[str] = Field(None, example="Колега по роботі")

class ContactUpdate(Contact):
    pass

@app.post("/contacts/", response_model=Contact)
async def create_contact(contact: Contact):
    contact_data = contact.dict()
    contact_data["birthday"] = datetime.combine(contact_data["birthday"], datetime.min.time())

    if await contacts_collection.find_one({"email": contact_data["email"]}):
        raise HTTPException(status_code=400, detail="Email вже використовується")
    if await contacts_collection.find_one({"phone": contact_data["phone"]}):
        raise HTTPException(status_code=400, detail="Телефон вже використовується")

    result = await contacts_collection.insert_one(contact_data)
    new_contact = await contacts_collection.find_one({"_id": result.inserted_id})
    return contact_helper(new_contact)

@app.get("/contacts/", response_model=List[Contact])
async def list_contacts(search: Optional[str] = None):
    query = {}
    if search:
        query = {
            "$or": [
                {"first_name": {"$regex": search, "$options": "i"}},
                {"last_name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
            ]
        }
    contacts = []
    cursor = contacts_collection.find(query)
    async for document in cursor:
        contacts.append(contact_helper(document))
    return contacts

@app.get("/contacts/{contact_id}", response_model=Contact)
async def get_contact(contact_id: str):
    try:
        oid = ObjectId(contact_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Невірний ідентифікатор контакту")
    contact = await contacts_collection.find_one({"_id": oid})
    if contact:
        return contact_helper(contact)
    raise HTTPException(status_code=404, detail="Контакт не знайдено")

@app.put("/contacts/{contact_id}", response_model=Contact)
async def update_contact(contact_id: str, contact_update: ContactUpdate):
    try:
        oid = ObjectId(contact_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Невірний ідентифікатор контакту")

    contact_data = contact_update.dict()
    contact_data["birthday"] = datetime.combine(contact_data["birthday"], datetime.min.time())

  
    existing_email = await contacts_collection.find_one({"email": contact_data["email"], "_id": {"$ne": oid}})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email вже використовується")
    existing_phone = await contacts_collection.find_one({"phone": contact_data["phone"], "_id": {"$ne": oid}})
    if existing_phone:
        raise HTTPException(status_code=400, detail="Телефон вже використовується")

    result = await contacts_collection.update_one(
        {"_id": oid},
        {"$set": contact_data}
    )
    if result.modified_count == 1:
        updated_contact = await contacts_collection.find_one({"_id": oid})
        return contact_helper(updated_contact)
    raise HTTPException(status_code=404, detail="Контакт не знайдено")

@app.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: str):
    try:
        oid = ObjectId(contact_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Невірний ідентифікатор контакту")

    result = await contacts_collection.delete_one({"_id": oid})
    if result.deleted_count == 1:
        return
    raise HTTPException(status_code=404, detail="Контакт не знайдено")


@app.get("/contacts/upcoming-birthdays/", response_model=List[Contact])
async def upcoming_birthdays():
    today = datetime.utcnow()
    in_seven_days = today + timedelta(days=7)

    
    pipeline = [
        {
            "$addFields": {
                "birthMonth": {"$month": "$birthday"},
                "birthDay": {"$dayOfMonth": "$birthday"},
            }
        },
        {
            "$match": {
                "$expr": {
                    "$and": [
                        {"$gte": [
                            {"$dateFromParts": {
                                "year": today.year,
                                "month": "$birthMonth",
                                "day": "$birthDay"
                            }},
                            today
                        ]},
                        {"$lte": [
                            {"$dateFromParts": {
                                "year": today.year,
                                "month": "$birthMonth",
                                "day": "$birthDay"
                            }},
                            in_seven_days
                        ]}
                    ]
                }
            }
        }
    ]

    contacts = []
    async for doc in contacts_collection.aggregate(pipeline):
        contacts.append(contact_helper(doc))
    return contacts
