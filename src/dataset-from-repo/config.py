"""
Configuración central del pipeline de dataset.
Edita estas variables antes de correr los scripts.
"""
import os
from pathlib import Path

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_OWNER = "Trimble-Construction"
GITHUB_REPO  = "projectsight"
GITHUB_API   = "https://api.github.com"

# ── Repo local ────────────────────────────────────────────────────────────────
REPO_LOCAL = Path(r"C:\Users\eherrad\source\repos\projectsight")

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR   = Path(__file__).parent / "output"
RAW_DIR      = OUTPUT_DIR / "raw"
DATASET_FILE = OUTPUT_DIR / "dataset.jsonl"
TRAIN_FILE   = OUTPUT_DIR / "dataset_train.jsonl"
EVAL_FILE    = OUTPUT_DIR / "dataset_eval.jsonl"

RAW_DIR.mkdir(parents=True, exist_ok=True)

# ── Fase 1: solo PRs abiertos  /  Fase 2: todos los merged ───────────────────
PR_STATE = "open"       # "open" | "closed" | "all"
PR_LIMIT = 200          # None = sin límite (cuidado con rate limits)

# ── Límites de calidad ────────────────────────────────────────────────────────
MIN_DESCRIPTION_CHARS = 80    # Descripciones < N chars → descartado
MIN_SCORE             = 40    # Score mínimo para incluir en el dataset (0-100)
MAX_DIFF_LINES        = 800   # Diffs muy grandes → ruido (se truncan, no se descartan)
MIN_DIFF_LINES        = 5     # Diffs triviales → descartados
EVAL_RATIO            = 0.1   # Fracción del dataset para evaluación

# ── Límites de tokens (Qwen3.6-35B-A3B tiene un contexto de 262,144 tokens, aproximadamente 200,000 palabras o más de 300 páginas de texto) ──────────────────────
MAX_USER_CHARS    = 12_000   # ~3 500 tokens (deja mucho margen para system + assistant)
MAX_ASSISTANT_CHARS = 8_000  # ~2 000 tokens

# ── System prompt base ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
Eres un experto en el codebase de ProjectSight (Trimble Construction).
El proyecto usa .NET/C# en el backend con ASP.NET MVC/Razor y Angular en el frontend.

Reglas críticas del proyecto (nunca las violes):
- Backend: Nunca uses ORM (Entity Framework, Dapper). Solo IDBHelper con stored procedures por nombre.
- Backend: Toda operación de BD va a través de stored procedures nombrados. Jamás inline SQL.
- Frontend: Nunca uses Angular HttpClient. Usa RxJS ajax() via APIBase / APIFactory.
- Frontend: Usa DestroyRef + subscribeTo() para subscriptions, NO Subscription arrays manuales.
- Frontend: Nunca hardcodees colores hex. Usa variables CSS de Default.css.
- No edites delta_procs.sql directamente; se genera automáticamente desde base_procs.sql.
- Agregar o quitar [UseInAPI] en una propiedad dispara APIClientComponentGenerator al compilar.

Cuando implementes cambios, sigue el patrón exacto del diff que se te proporciona.\
"""
