from datetime import datetime
import json
import re
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ── App & Configuration ───────────────────────────────────────
app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
QCM_HTML_PATH = TEMPLATES_DIR / "create_QCM.html"
QCM_DATA_DIR = BASE_DIR / "QCM_data_base"

# Création des dossiers s'ils n'existent pas
QCM_DATA_DIR.mkdir(exist_ok=True)
PUBLIC_DATA_DIR = QCM_DATA_DIR / "public_data_base"
PRIVATE_DATA_DIR = QCM_DATA_DIR / "private_data_base"
PUBLIC_DATA_DIR.mkdir(exist_ok=True)
PRIVATE_DATA_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=TEMPLATES_DIR), name="static")


# ── Models ────────────────────────────────────────────────────
class QCMSavePayload(BaseModel):
    qcm_name: str = Field(min_length=1)  # Nom personnalisé du QCM
    auteur: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    visibilite: bool
    level: str = Field(min_length=1)
    questions: list
    source_file: str = None  # Optionnel : chemin du fichier existant pour l'édition


# ── Helpers ───────────────────────────────────────────────────
def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "qcm"


def save_qcm(payload: QCMSavePayload) -> dict:
    """Logique de sauvegarde d'un QCM sur le disque."""
    if not payload.questions:
        raise HTTPException(status_code=400, detail="Aucune question à sauvegarder")

    data = {
        "qcm_name": payload.qcm_name,
        "auteur": payload.auteur,
        "theme": payload.theme,
        "visibilite": payload.visibilite,
        "level": payload.level,
        "questions": payload.questions,
    }

    # Si on édite un fichier existant, le remplacer
    if payload.source_file:
        target = (BASE_DIR / payload.source_file).resolve()
        
        # Sécurité : vérifier qu'on ne sort pas du dossier du projet
        if not str(target).startswith(str(BASE_DIR)):
            raise HTTPException(status_code=403, detail="Accès interdit")
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="Fichier QCM introuvable")
        
        # Remplacer le fichier existant
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        
        return {
            "message": "QCM mis à jour",
            "filename": target.name,
            "directory": str(target.parent.relative_to(BASE_DIR)),
        }
    
    # Mode création : créer un nouveau fichier avec timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slugify(payload.theme)}_{slugify(payload.auteur)}_{timestamp}.json"

    # Choix du dossier (public ou privé) + sous-dossier thématique
    target_dir = PUBLIC_DATA_DIR if payload.visibilite else PRIVATE_DATA_DIR
    theme_dir = target_dir / slugify(payload.theme)
    theme_dir.mkdir(exist_ok=True)
    file_path = theme_dir / filename

    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "message": "QCM sauvegardé",
        "filename": filename,
        "directory": str(theme_dir.relative_to(BASE_DIR)),
    }


# ── Pages (HTML) ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def get_login():
    path = TEMPLATES_DIR / "login.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Fichier cherché ici : {path}")
    return path.read_text(encoding="utf-8")


@app.get("/dashboard_prof", response_class=HTMLResponse)
def get_dashboard_prof():
    path = TEMPLATES_DIR / "prof_dashboard.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="prof_dashboard.html introuvable")
    return path.read_text(encoding="utf-8")

@app.get("/prof_dashboard.html", response_class=HTMLResponse)
def get_prof_dashboard_html():
    return get_dashboard_prof()

@app.get("/home_prof.html", response_class=HTMLResponse)
def get_home_prof_html():
    path = TEMPLATES_DIR / "home_prof.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="home_prof.html introuvable")
    return path.read_text(encoding="utf-8")

@app.get("/{page_name}.html", response_class=HTMLResponse)
def get_html_page(page_name: str):
    path = TEMPLATES_DIR / f"{page_name}.html"
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{page_name}.html introuvable")
    return path.read_text(encoding="utf-8")


@app.get("/qcm", response_class=HTMLResponse)
def qcm_page():
    if not QCM_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="create_QCM.html introuvable")
    return QCM_HTML_PATH.read_text(encoding="utf-8")


# ── API (JSON) ────────────────────────────────────────────────
@app.post("/api/qcm/save")
def qcm_save_endpoint(payload: QCMSavePayload):
    """Sauvegarde un nouveau QCM."""
    result = save_qcm(payload)
    return JSONResponse(result)


@app.get("/api/qcm/list")
def qcm_list():
    """Scanne le dossier QCM_data_base et retourne la liste de tous les QCM."""
    qcms = []
    for vis_dir in [PUBLIC_DATA_DIR, PRIVATE_DATA_DIR]:
        if not vis_dir.exists():
            continue
        for theme_dir in vis_dir.iterdir():
            if not theme_dir.is_dir():
                continue
            for file_path in theme_dir.glob("*.json"):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    qcms.append({
                        "filename": file_path.name,
                        "theme_dir": str(theme_dir.relative_to(BASE_DIR)),
                        "full_path": str(file_path.relative_to(BASE_DIR)),
                        "qcm_name": data.get("qcm_name", ""),
                        "auteur": data.get("auteur", "Inconnu"),
                        "theme": data.get("theme", ""),
                        "visibilite": data.get("visibilite", False),
                        "level": data.get("level", ""),
                        "nb_questions": len(data.get("questions", [])),
                    })
                except (json.JSONDecodeError, KeyError):
                    continue
    return JSONResponse(qcms)


@app.get("/api/qcm/read/{file_path:path}")
def qcm_read(file_path: str):
    """Lit un fichier QCM JSON spécifique (pour le mode édition)."""
    target = (BASE_DIR / file_path).resolve()
    
    # Sécurité : vérifier qu'on ne sort pas du dossier du projet
    if not str(target).startswith(str(BASE_DIR)):
        raise HTTPException(status_code=403, detail="Accès interdit")
        
    if not target.exists():
        raise HTTPException(status_code=404, detail="QCM introuvable")
        
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        # On ajoute le chemin du fichier source pour pouvoir l'écraser lors de la sauvegarde
        data["_source_file"] = file_path
        return JSONResponse(data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Fichier JSON invalide")


# ── Lancement du serveur ──────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)