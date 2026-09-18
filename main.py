import os
from typing import Annotated
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client

# 1. Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not GEMINI_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing critical environment variables. Check your .env file!")

# 2. Initialize Gemini and Supabase clients
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 3. Initialize FastAPI App
app = FastAPI(title="Apex Tactical Fitness API")
security = HTTPBearer()

# Helper dependency to authenticate bearer token
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        token = credentials.credentials
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid authentication token")
        return user_response.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

# Request schemas
class UserProfile(BaseModel):
    full_name: str
    target_agency: str
    fitness_goals: str
    medical_limitations: str | None = None

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def home():
    return {"status": "Apex Backend Online", "database": "Connected"}

# Endpoint: Fetch user profile
@app.get("/profile")
def get_profile(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("profiles").select("*").eq("user_id", current_user_id).execute()
        if response.data:
            return response.data[0]
        return {"user_id": current_user_id, "username": "Unknown User"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint: Create or update user fitness profile
@app.post("/profile")
def save_profile(
    profile: UserProfile, 
    current_user_id: Annotated[str, Depends(get_current_user)]
):
    try:
        data = {
            "user_id": current_user_id,
            "full_name": profile.full_name,
            "target_agency": profile.target_agency,
            "fitness_goals": profile.fitness_goals,
            "medical_limitations": profile.medical_limitations
        }
        response = supabase.table("profiles").upsert(data).execute()
        return {"status": "Profile saved successfully", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint: Process user chat with dynamic profile + recent chat history using Gemini 3.6 Flash
@app.post("/chat")
def chat(
    request: ChatRequest, 
    current_user_id: Annotated[str, Depends(get_current_user)]
):
    try:
        # 1. Fetch user profile from Supabase
        profile_response = supabase.table("profiles").select("*").eq("user_id", current_user_id).execute()
        profile_data = profile_response.data[0] if profile_response.data else None

        # 2. Build system instruction based on profile context
        if profile_data:
            system_instruction = (
                f"You are the Apex Tactical Fitness AI Coach. "
                f"Client Name: {profile_data.get('full_name', 'User')}. "
                f"Target Agency: {profile_data.get('target_agency', 'General Tactical')}. "
                f"Fitness Goals: {profile_data.get('fitness_goals', 'General Conditioning')}. "
                f"Medical Limitations/Injuries: {profile_data.get('medical_limitations', 'None')}. "
                f"Tailor all training advice specifically to their target agency requirements, "
                f"strictly accounting for any medical limitations."
            )
        else:
            system_instruction = "You are the Apex Tactical Fitness AI Coach. Provide safe, effective tactical fitness guidance."

        # 3. Fetch recent chat history (last 5 messages) for context
        history_response = (
            supabase.table("chat_messages")
            .select("role, message")
            .eq("user_id", current_user_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        
        past_messages = history_response.data[::-1] if history_response.data else []
        
        formatted_contents = []
        for msg in past_messages:
            formatted_contents.append(f"{msg['role'].capitalize()}: {msg['message']}")
        formatted_contents.append(f"User: {request.message}")

        full_prompt = "\n".join(formatted_contents)

        # 4. Save current user message to Supabase
        supabase.table("chat_messages").insert({
            "user_id": current_user_id,
            "role": "user",
            "message": request.message
        }).execute()

        # 5. Call Gemini API using gemini-3.6-flash
        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=full_prompt,
            config={"system_instruction": system_instruction}
        )
        model_reply = response.text

        # 6. Save AI reply to Supabase
        supabase.table("chat_messages").insert({
            "user_id": current_user_id,
            "role": "model",
            "message": model_reply
        }).execute()

        return {
            "response": model_reply,
            "profile_context_applied": bool(profile_data),
            "history_length_included": len(past_messages)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))