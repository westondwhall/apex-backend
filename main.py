import os
from typing import Annotated, Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client
import datetime

# 1. Load environment variables from .env file
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Safety check for environment variables
if not GEMINI_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing critical environment variables. Check your .env file or Render configuration!")

# 2. Initialize Clients
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Default full equipment string used when user leaves equipment empty/blank
DEFAULT_FULL_EQUIPMENT = "Full Commercial Gym, Barbell, Dumbbells, Kettlebells, Pull-up Bar, Ruck Plate, Rowing Machine, Assault Bike, Track/Road"

APEX_SYSTEM_INSTRUCTION = """
You are Apex: a supportive, disciplined, peer-to-peer military mentor and tactical performance coach.
Your voice is direct, grounded, concise, and candid. Treat the user as an equal teammate.
Use the provided tactical documents as your primary ground truth for standards, protocols, and tests.
"""

# 3. Initialize FastAPI App
app = FastAPI(title="Apex Tactical Fitness API")

# Configure CORS Middleware for Flutter Web and local development (Must be configured early)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Bearer Security Scheme
security = HTTPBearer()

def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]) -> str:
    """Validates the Supabase JWT token and returns the authenticated user's ID."""
    token = credentials.credentials
    try:
        user = supabase.auth.get_user(token)
        if not user or not user.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return user.user.id
    except Exception as e:
        print(f"TOKEN VALIDATION ERROR: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

# --- Request Schemas ---
class UserProfile(BaseModel):
    full_name: str
    target_agency: str
    fitness_goals: str
    medical_limitations: Optional[str] = None
    experience_level: Optional[str] = "Intermediate"
    training_days_per_week: Optional[int] = 4
    sports: Optional[str] = None
    physical_metrics: Optional[str] = None
    core_stats: Optional[str] = None
    injuries_limitations: Optional[str] = None
    equipment: Optional[str] = None
    terms_accepted: bool = True
    billing_accepted: bool = True
    privacy_accepted: bool = True

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    target_agency: str
    fitness_goals: str
    medical_limitations: Optional[str] = None
    sports: Optional[str] = None
    physical_metrics: Optional[str] = None
    core_stats: Optional[str] = None
    injuries_limitations: Optional[str] = None
    equipment: Optional[str] = None
    terms_accepted: bool = True
    billing_accepted: bool = True
    privacy_accepted: bool = True

class ChatRequest(BaseModel):
    message: str

class AuthRequest(BaseModel):
    email: EmailStr
    password: str

class WorkoutPlanRequest(BaseModel):
    target_agency: str
    timeline_weeks: int = 4

class SavePlanRequest(BaseModel):
    target_agency: str
    timeline_weeks: int
    plan_text: str

class WorkoutLogRequest(BaseModel):
    exercise: str
    date: Optional[str] = None
    weight: Optional[float] = 0.0
    time: Optional[str] = None
    reps: int
    rpe: int
    timestamp: Optional[str] = None
    status: Optional[str] = "completed"

class NoteCreateRequest(BaseModel):
    title: str
    content: Optional[str] = None
    image_url: Optional[str] = None

class PersonalRecordRequest(BaseModel):
    exercise: str
    metric: str
    date: str

class BenchmarkRequest(BaseModel):
    id: Optional[str] = None
    category: str
    target: str
    progress: float

# --- General Routes ---
@app.get("/")
def home():
    return {"status": "Apex Backend Online", "database": "Connected"}

@app.get("/terms")
def get_terms():
    terms_text = """
    APEX TACTICAL PERFORMANCE - TERMS OF SERVICE & LIABILITY WAIVER
    
    END-USER LICENSE AGREEMENT AND TERMS OF SERVICE
    App Name: APEX TACTICAL PERFORMANCE
    Effective Date: 15 September 2026
    Last Updated: 15 September 2026
    PLEASE READ THIS END-USER LICENSE AGREEMENT AND TERMS OF SERVICE CAREFULLY.
    """
    return {"status": "success", "terms": terms_text.strip()}

@app.get("/billing-policy")
def get_billing_policy():
    billing_text = "APEX TACTICAL PERFORMANCE BILLING & SUBSCRIPTION POLICY..."
    return {"status": "success", "billing_policy": billing_text.strip()}

@app.get("/privacy-policy")
def get_privacy_policy():
    privacy_text = "APEX TACTICAL PERFORMANCE PRIVACY POLICY..."
    return {"status": "success", "privacy_policy": privacy_text.strip()}

# --- Authentication Endpoints ---
@app.post("/auth/signup")
def signup(request: SignupRequest):
    try:
        response = supabase.auth.sign_up({
            "email": request.email,
            "password": request.password
        })
        user_id = response.user.id if response.user else None
        if not user_id:
            raise HTTPException(status_code=400, detail="Failed to create user account.")

        resolved_equipment = request.equipment if (request.equipment and request.equipment.strip()) else DEFAULT_FULL_EQUIPMENT

        profile_data = {
            "user_id": user_id,
            "full_name": request.full_name,
            "target_agency": request.target_agency,
            "fitness_goals": request.fitness_goals,
            "medical_limitations": request.medical_limitations,
            "sports": request.sports,
            "physical_metrics": request.physical_metrics,
            "core_stats": request.core_stats,
            "injuries_limitations": request.injuries_limitations,
            "equipment": resolved_equipment,
            "terms_accepted": request.terms_accepted,
            "billing_accepted": request.billing_accepted,
            "privacy_accepted": request.privacy_accepted
        }
        supabase.table("profiles").upsert(profile_data, on_conflict="user_id").execute()
        return {"status": "User registered and profile initialized successfully", "user_id": user_id}
    except Exception as e:
        print(f"SIGNUP ERROR: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/login")
def login(credentials: AuthRequest):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password
        })
        return {
            "status": "Login successful",
            "access_token": response.session.access_token,
            "user_id": response.user.id
        }
    except Exception as e:
        print(f"REAL LOGIN ERROR: {str(e)}") # Prints detailed reason to Render logs
        raise HTTPException(status_code=401, detail=f"Login failed: {str(e)}")

@app.delete("/auth/account")
def delete_user_account(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        supabase.table("profiles").delete().eq("user_id", current_user_id).execute()
        supabase.table("notes").delete().eq("user_id", current_user_id).execute()
        supabase.table("workout_logs").delete().eq("user_id", current_user_id).execute()
        supabase.table("workout_plans").delete().eq("user_id", current_user_id).execute()
        supabase.table("chat_messages").delete().eq("user_id", current_user_id).execute()
        supabase.table("personal_records").delete().eq("user_id", current_user_id).execute()
        supabase.table("agency_benchmarks").delete().eq("user_id", current_user_id).execute()
        return {"status": "success", "message": "Account and associated data deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Protected Endpoints ---
@app.get("/profile")
def get_profile(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("profiles").select("*").eq("user_id", current_user_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Profile not found")
        return response.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/profile")
def save_profile(profile: UserProfile, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        resolved_equipment = profile.equipment if (profile.equipment and profile.equipment.strip()) else DEFAULT_FULL_EQUIPMENT

        data = {
            "user_id": current_user_id,
            "full_name": profile.full_name,
            "target_agency": profile.target_agency,
            "fitness_goals": profile.fitness_goals,
            "medical_limitations": profile.medical_limitations,
            "experience_level": profile.experience_level,
            "training_days_per_week": profile.training_days_per_week,
            "sports": profile.sports,
            "physical_metrics": profile.physical_metrics,
            "core_stats": profile.core_stats,
            "injuries_limitations": profile.injuries_limitations,
            "equipment": resolved_equipment,
            "terms_accepted": profile.terms_accepted,
            "billing_accepted": profile.billing_accepted,
            "privacy_accepted": profile.privacy_accepted
        }
        response = supabase.table("profiles").upsert(data, on_conflict="user_id").execute()
        return {"status": "Profile saved successfully", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Personal Records Endpoints ---
@app.get("/personal-records")
def get_personal_records(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("personal_records").select("*").eq("user_id", current_user_id).execute()
        return {"status": "success", "records": response.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/personal-records")
def save_personal_record(request: PersonalRecordRequest, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        data = {
            "user_id": current_user_id,
            "exercise": request.exercise,
            "metric": request.metric,
            "date": request.date
        }
        response = supabase.table("personal_records").insert(data).execute()
        return {"status": "success", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/personal-records/{record_id}")
def delete_personal_record(record_id: str, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        supabase.table("personal_records").delete().eq("id", record_id).eq("user_id", current_user_id).execute()
        return {"status": "success", "message": "PR deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Agency Benchmarks Endpoints ---
@app.get("/agency-benchmarks")
def get_agency_benchmarks(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("agency_benchmarks").select("*").eq("user_id", current_user_id).execute()
        return {"status": "success", "benchmarks": response.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agency-benchmarks")
def save_agency_benchmark(request: BenchmarkRequest, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        data = {
            "user_id": current_user_id,
            "category": request.category,
            "target": request.target,
            "progress": request.progress
        }
        if request.id:
            response = supabase.table("agency_benchmarks").update(data).eq("id", request.id).eq("user_id", current_user_id).execute()
        else:
            response = supabase.table("agency_benchmarks").insert(data).execute()
        return {"status": "success", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/agency-benchmarks/{benchmark_id}")
def delete_agency_benchmark(benchmark_id: str, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        supabase.table("agency_benchmarks").delete().eq("id", benchmark_id).eq("user_id", current_user_id).execute()
        return {"status": "success", "message": "Benchmark deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Chat, Workouts, Notes Endpoints ---
@app.post("/chat")
def chat(request: ChatRequest, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        profile_response = supabase.table("profiles").select("*").eq("user_id", current_user_id).execute()
        profile_data = profile_response.data[0] if profile_response.data else None
        
        logs_response = supabase.table("workout_logs").select("exercise, weight, time, reps, rpe, date").eq("user_id", current_user_id).order("timestamp", desc=True).limit(10).execute()
        recent_logs = logs_response.data or []
        
        plans_response = supabase.table("workout_plans").select("target_agency, timeline_weeks, plan_text").eq("user_id", current_user_id).order("created_at", desc=True).limit(1).execute()
        active_plan = plans_response.data[0] if plans_response.data else None

        logs_summary = "\n".join([f"- {l['date']}: {l['exercise']} | Weight: {l['weight']}lbs | Time: {l.get('time', 'N/A')} | Reps: {l['reps']} | RPE {l['rpe']}" for l in recent_logs])
        plan_summary = active_plan.get('plan_text', 'No active plan saved.') if active_plan else 'None'

        if profile_data:
            user_equipment = profile_data.get('equipment')
            if not user_equipment or not user_equipment.strip():
                user_equipment = DEFAULT_FULL_EQUIPMENT

            system_instruction = (
                f"You are the Apex Tactical Fitness AI Coach. "
                f"Client Name: {profile_data.get('full_name', 'User')}. "
                f"Target Agency: {profile_data.get('target_agency', 'General Tactical')}. "
                f"Sport(s): {profile_data.get('sports', 'None specified')}. "
                f"Fitness Goals: {profile_data.get('fitness_goals', 'General Conditioning')}. "
                f"Experience Level: {profile_data.get('experience_level', 'Intermediate')}. "
                f"Training Days/Week: {profile_data.get('training_days_per_week', 4)}. "
                f"Physical Metrics: {profile_data.get('physical_metrics', 'Not specified')}. "
                f"Core Stats: {profile_data.get('core_stats', 'Not specified')}. "
                f"Injuries & Limitations: {profile_data.get('injuries_limitations', profile_data.get('medical_limitations', 'None'))}. "
                f"Available Equipment: {user_equipment}. \n\n"
                f"RECENT WORKOUT LOGS:\n{logs_summary if logs_summary else 'No recent logs found.'}\n\n"
                f"ACTIVE TRAINING PLAN SUMMARY:\n{plan_summary[:500]}...\n\n"
                f"Tailor all training advice specifically to their target agency requirements, sport-specific athletic background, experience level, training frequency, physical metrics, core stats, available equipment, recent performance trends, and medical/injury limitations."
            )
        else:
            system_instruction = "You are the Apex Tactical Fitness AI Coach. Provide safe, effective tactical fitness guidance."

        history_response = supabase.table("chat_messages").select("role, message").eq("user_id", current_user_id).order("created_at", desc=True).limit(5).execute()
        past_messages = history_response.data[::-1] if history_response.data else []
        
        formatted_contents = [f"{msg['role'].capitalize()}: {msg['message']}" for msg in past_messages]
        formatted_contents.append(f"User: {request.message}")
        full_prompt = "\n".join(formatted_contents)

        supabase.table("chat_messages").insert({"user_id": current_user_id, "role": "user", "message": request.message}).execute()

        response = gemini_client.models.generate_content(
            model="models/gemini-3.6-flash",
            contents=full_prompt,
            config={"system_instruction": system_instruction}
        )
        model_reply = response.text

        supabase.table("chat_messages").insert({"user_id": current_user_id, "role": "model", "message": model_reply}).execute()

        return {"response": model_reply, "profile_context_applied": bool(profile_data), "history_length_included": len(past_messages)}
    except Exception as e:
        print(f"CHAT ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat-history")
def get_chat_history(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("chat_messages").select("id, role, message, created_at").eq("user_id", current_user_id).order("created_at", desc=False).execute()
        return {"status": "success", "messages": response.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/chat-messages/{message_id}")
def delete_chat_message(message_id: str, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("chat_messages").delete().eq("id", message_id).eq("user_id", current_user_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Message not found or unauthorized")
        return {"status": "success", "message": "Chat message deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-plan")
def generate_workout_plan(request: WorkoutPlanRequest, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        profile_response = supabase.table("profiles").select("*").eq("user_id", current_user_id).execute()
        profile_data = profile_response.data[0] if profile_response.data else {}

        user_equipment = profile_data.get('equipment')
        if not user_equipment or not user_equipment.strip():
            user_equipment = DEFAULT_FULL_EQUIPMENT

        rag_files = list(gemini_client.files.list())
        prompt = f"""
        Generate a structured, {request.timeline_weeks}-week tactical fitness conditioning program 
        specifically designed to prepare a candidate for the {request.target_agency} test standards.
        User Profile Context:
        - Physical Metrics: {profile_data.get('physical_metrics', 'Not specified')}
        - Core Stats: {profile_data.get('core_stats', 'Not specified')}
        - Injuries/Limitations: {profile_data.get('injuries_limitations', profile_data.get('medical_limitations', 'None'))}
        - Equipment Available: {user_equipment}
        
        Use the provided tactical documents as ground truth for standards, protocols, and performance thresholds.
        Return the response with clear weekly progression, exercises, sets, reps, and rest intervals, strictly adapting to their equipment and physical/injury limitations.
        """
        contents = [f for f in rag_files] + [prompt]
        response = gemini_client.models.generate_content(
            model="models/gemini-3.6-flash",
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=APEX_SYSTEM_INSTRUCTION)
        )
        return {"status": "success", "workout_plan": response.text}
    except Exception as e:
        print(f"GENERATE PLAN ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/save-plan")
def save_workout_plan(request: SavePlanRequest, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("workout_plans").insert({
            "user_id": current_user_id,
            "target_agency": request.target_agency,
            "timeline_weeks": request.timeline_weeks,
            "plan_text": request.plan_text
        }).execute()
        return {"status": "success", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/workout-history")
def get_workout_history(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("workout_plans").select("*").eq("user_id", current_user_id).order("created_at", desc=True).execute()
        return {"status": "success", "history": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/workout-logs")
def log_workout_session(request: WorkoutLogRequest, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        log_data = {
            "user_id": current_user_id,
            "exercise": request.exercise,
            "weight": request.weight,
            "time": request.time,
            "reps": request.reps,
            "rpe": request.rpe,
            "status": request.status or "completed"
        }
        if request.timestamp:
            log_data["timestamp"] = request.timestamp
        response = supabase.table("workout_logs").upsert(log_data).execute()
        return {"status": "success", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/workout-logbook")
def get_workout_logbook(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("workout_logs").select("id, exercise, weight, time, reps, rpe, status, timestamp, created_at").eq("user_id", current_user_id).order("timestamp", desc=True).execute()
        return {"status": "success", "logs": response.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Notepad Persistent Endpoints ---
@app.get("/notes")
def get_notes(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("notes").select("*").eq("user_id", current_user_id).order("created_at", desc=True).execute()
        return {"status": "success", "notes": response.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notes")
def create_note(request: NoteCreateRequest, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        data = {
            "user_id": current_user_id,
            "title": request.title,
            "content": request.content,
            "image_url": request.image_url
        }
        response = supabase.table("notes").insert(data).execute()
        return {"status": "success", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/notes/{note_id}")
def delete_note(note_id: str, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("notes").delete().eq("id", note_id).eq("user_id", current_user_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Note not found or unauthorized")
        return {"status": "success", "message": "Note deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics")
def get_analytics(current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("workout_logs").select("*").eq("user_id", current_user_id).execute()
        logs = response.data or []
        completion_rate = round((sum(1 for l in logs if l.get('status') == 'completed') / len(logs)) * 100, 2) if logs else 0.0
        
        avg_rpe = sum(l.get('rpe', 5) for l in logs) / len(logs) if logs else 5.0
        if len(logs) > 12 and avg_rpe > 8.0:
            readiness = "Overtraining Risk"
        elif len(logs) < 3:
            readiness = "Undertraining"
        else:
            readiness = "Optimal Range"

        return {
            "completion_rate": completion_rate,
            "total_workouts": len(logs),
            "readiness_status": readiness,
            "avg_rpe": round(avg_rpe, 1)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/workout-plans/{plan_id}")
def delete_workout_plan(plan_id: str, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        supabase.table("workout_plans").delete().eq("id", plan_id).eq("user_id", current_user_id).execute()
        return {"status": "success", "message": "Plan deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/workout-logs/{log_id}")
def delete_workout_log(log_id: str, current_user_id: Annotated[str, Depends(get_current_user)]):
    try:
        response = supabase.table("workout_logs").delete().eq("id", log_id).eq("user_id", current_user_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Log entry not found or unauthorized to delete")
        return {"status": "success", "message": "Workout log deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))