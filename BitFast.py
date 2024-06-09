from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import supabase
import time
import asyncio
from cachetools import TTLCache, cached

# Initialize FastAPI app
app = FastAPI()

# Set up CORS
origins = [
    "http://localhost",
    "http://localhost:8000",
    # Add other origins as needed
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase configuration
supabase_url = "YOUR_SUPABASE_URL"
supabase_key = "YOUR_SUPABASE_KEY"
supabase_client = supabase.create_client(supabase_url, supabase_key)

# Define cache with TTL of 2 minutes to respect API limits
cache = TTLCache(maxsize=100, ttl=120)  # 120 seconds (2 minutes) TTL

class BitcoinPrice(BaseModel):
    price: float

async def rate_limit_check():
    """ Helper function to ensure we don't exceed CoinGecko's rate limits. """
    await asyncio.sleep(2)  # Wait for 2 seconds between API calls

@cached(cache)
async def fetch_bitcoin_price_from_api():
    """ Function to fetch Bitcoin price from CoinGecko API. """
    await rate_limit_check()
    response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd')
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Error fetching data from CoinGecko API")

    data = response.json()
    bitcoin_price = data['bitcoin']['usd']
    return bitcoin_price

@app.get("/fetch-bitcoin-price", response_model=BitcoinPrice)
async def fetch_bitcoin_price():
    """ Endpoint to fetch Bitcoin price, respecting rate limits and using cache. """
    try:
        bitcoin_price = await fetch_bitcoin_price_from_api()

        # Insert into Supabase
        data = {'price': bitcoin_price, 'timestamp': int(time.time())}
        supabase_client.table('bitcoin_prices').insert(data).execute()

        return BitcoinPrice(price=bitcoin_price)
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/bitcoin-price-history")
async def get_bitcoin_price_history(limit: int = 10):
    """ Endpoint to fetch historical Bitcoin prices from Supabase. """
    try:
        response = supabase_client.table('bitcoin_prices').select('*').order('timestamp', desc=True).limit(limit).execute()
        data = response.get('data', [])
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# To ensure you don't exceed the monthly cap of 10,000 calls, monitor your usage:
api_call_count = 0

@app.on_event("startup")
async def startup_event():
    global api_call_count
    # Load the initial count from your database or a file if necessary
    api_call_count = 0

@app.on_event("shutdown")
async def shutdown_event():
    global api_call_count
    # Save the count to your database or a file if necessary

@app.middleware("http")
async def check_api_call_limit(request, call_next):
    global api_call_count
    if api_call_count >= 10000:
        return JSONResponse(status_code=429, content={"message": "API call limit exceeded"})
    
    response = await call_next(request)
    api_call_count += 1
    return response
