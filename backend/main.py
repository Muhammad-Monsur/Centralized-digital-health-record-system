from pathlib import Path

from fastapi import Cookie, Depends, FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models, seed
from .database import SessionLocal, init_db
from .deps import get_db
from .routers import auth, doctor, hospital_admin, patient, system_admin
from .routers.auth import PORTAL_ROLE
from .security import read_session

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="CDHRS - Centralized Digital Health Record System")


@app.on_event("startup")
def on_startup():
    init_db()   # create tables if they don't exist (MySQL or the SQLite fallback)
    seed.run()  # insert demo accounts the first time only


#  API routers
app.include_router(auth.router)
app.include_router(auth.me_router)
app.include_router(patient.router)
app.include_router(doctor.router)
app.include_router(hospital_admin.router)
app.include_router(system_admin.router)


#  protected portal pages by Access Control 
def make_guard(portal: str, role: str):
    
    def guard(cdhrs_session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
        user_id = read_session(cdhrs_session)
        user = db.query(models.User).filter(models.User.id == user_id).first() if user_id else None
        if not user or user.role != role or user.status == "Blocked":
            return RedirectResponse(f"/{portal}/login.html", status_code=302)
        response = FileResponse(FRONTEND_DIR / portal / "profile.html")
        response.headers["Cache-Control"] = "no-store"
        return response
    return guard


def make_home(portal: str):
    def home():
        return RedirectResponse(f"/{portal}/login.html", status_code=302)
    return home


for _portal, _role in PORTAL_ROLE.items():
    app.add_api_route(f"/{_portal}/profile.html", make_guard(_portal, _role), methods=["GET"], include_in_schema=False)
    app.add_api_route(f"/{_portal}", make_home(_portal), methods=["GET"], include_in_schema=False)
    app.add_api_route(f"/{_portal}/", make_home(_portal), methods=["GET"], include_in_schema=False)

#  static files
#the guard first; every other file in each portal folder (login.html,
# register.html) is served normally through these mounts.
app.mount("/shared", StaticFiles(directory=FRONTEND_DIR / "shared"), name="shared")
for _portal in PORTAL_ROLE:
    app.mount(f"/{_portal}", StaticFiles(directory=FRONTEND_DIR / _portal), name=_portal)


@app.get("/")
def landing():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/preview.html")
def preview():
    return FileResponse(FRONTEND_DIR / "preview.html")
