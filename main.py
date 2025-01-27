from fastapi import FastAPI, Request, Form, UploadFile, File, Response  # Tambahkan Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException

from pydantic import BaseModel
from bson import ObjectId
import motor.motor_asyncio
import os
from datetime import datetime

app = FastAPI()

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Database Configuration
DATABASE_URI = "mongodb://localhost:27017"
DATABASE_NAME = "backendinterview"
COLLECTION_NAME = "backendinterview"

client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]

# Templates
templates = Jinja2Templates(directory="templates")

# Pydantic Models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class Transaction(BaseModel):
    user_id: str
    amount: int
    type: str  # 'credit' atau 'debit'

class Product(BaseModel):
    name: str
    quantity: int
    price: int
    image: str = None
    user_id: str
    _id: str = None  # Menambahkan field _id untuk menyimpan ObjectId sebagai string

# Routes
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, user_id: str = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required.")

    # Ambil data pengguna berdasarkan user_id
    user = await collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Ambil produk yang telah ditambahkan oleh pengguna
    products = await collection.find({"user_id": user_id}).to_list(100)
    for product in products:
        product["_id"] = str(product["_id"])

    # Ambil history transaksi pengguna
    transactions = await collection.find({"user_id": user_id}).sort("date", -1).to_list(100)

    return templates.TemplateResponse(
        "dashboard.html", 
        {"request": request, "user": user, "products": products, "transactions": transactions}
    )

@app.post("/login")
async def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    # Cari pengguna berdasarkan email
    user = await collection.find_one({"email": email})
    if not user or user["password"] != password:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password"}
        )
    
    response = RedirectResponse(url=f"/dashboard?user_id={user['_id']}", status_code=303)
    response.set_cookie(key="user_id", value=str(user["_id"]))
    return response

@app.post("/register")
async def register_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    user_dict = {
        "username": username,
        "email": email,
        "password": password,
        "balance": 0,
        "profile_picture": None,
    }
    await collection.insert_one(user_dict)
    return {"message": "User registered successfully."}

@app.post("/upload-profile")
async def upload_profile(user_id: str = Form(...), file: UploadFile = File(...)):
    file_location = f"static/uploads/{user_id}_{file.filename}"
    with open(file_location, "wb") as f:
        f.write(await file.read())

    await collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"profile_picture": file_location}})
    return {"message": "Profile picture updated successfully."}

@app.post("/top-up")
async def top_up_balance(user_id: str = Form(...), amount: int = Form(...)):
    await collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"balance": amount}}
    )
    await collection.insert_one({
        "user_id": user_id,
        "amount": amount,
        "type": "credit",
        "date": datetime.now()
    })
    return {"message": "Top-up successful."}

@app.post("/buy-product")
async def buy_product(user_id: str, product: Product):
    user = await collection.find_one({"_id": ObjectId(user_id)})
    total_cost = product.quantity * product.price

    if user["balance"] < total_cost:
        return {"error": "Insufficient balance."}

    await collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"balance": -total_cost}}
    )
    await collection.insert_one({
        "user_id": user_id,
        "amount": total_cost,
        "type": "debit",
        "date": datetime.now()
    })
    return {"message": "Product purchased successfully."}

@app.post("/add-product")
async def add_product(
    name: str = Form(...),
    quantity: int = Form(...),
    price: int = Form(...),
    product_image: UploadFile = File(...),
    user_id: str = Form(...),
):
    # Pastikan direktori untuk menyimpan file ada
    upload_dir = "static/uploads"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)

    # Tentukan lokasi file
    file_location = f"{upload_dir}/{product_image.filename}"

    try:
        # Simpan file gambar
        with open(file_location, "wb") as f:
            f.write(await product_image.read())

        # Siapkan data produk untuk disimpan ke database
        product = {
            "name": name,
            "quantity": quantity,
            "price": price,
            "image": file_location,
            "user_id": user_id
        }

        # Masukkan produk ke dalam koleksi MongoDB
        result = await collection.insert_one(product)
        product["_id"] = str(result.inserted_id)

        # Ambil produk yang telah ditambahkan
        products = await collection.find({"user_id": user_id}).to_list(100)
        for product in products:
            product["_id"] = str(product["_id"])

        return {"message": "Product added successfully.", "products": products}

    except Exception as e:
        # Log error dan kirim respons error
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# Endpoint baru untuk mengambil data produk
@app.get("/get-products/{user_id}", response_class=JSONResponse)
async def get_products(user_id: str):
    products = await collection.find({"user_id": user_id}).to_list(100)
    for product in products:
        product["_id"] = str(product["_id"])
    return {"products": products}
    
# Fungsi Logout	
@app.get("/logout")
async def logout_user(request: Request, response: Response):
    response = RedirectResponse(url="/")
    response.delete_cookie("user_id")
    return response

	