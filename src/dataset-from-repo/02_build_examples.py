"""
SCRIPT 2 — Construir ejemplos de entrenamiento

Para cada PR en output/raw/:
  1. Carga el JSON crudo
  2. Usa git local para obtener el contenido de los archivos ANTES del cambio
  3. Construye la tripla (system, user, assistant) del ejemplo de entrenamiento
  4. Calcula un score de calidad (0-100)
  5. Guarda en output/examples/pr_{number}.json

Requiere el repo clonado en config.REPO_LOCAL.

Score de calidad:
  +30  Descripción ≥ 200 chars
  +15  Descripción ≥ 80 chars
  +20  ≥ 2 reviewers aprobaron
  +10  ≥ 1 reviewer aprobó
  +20  Tiene review comments (feedback inline)
  +10  Tiene comments del hilo (discusión)
  -20  Draft PR
  -10  Diff vacío o sin patch
  -15  Descripción parece placeholder ("fix", "wip", "update", "changes")
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
import config


# ── Git helpers ───────────────────────────────────────────────────────────────

def git_file_at(sha: str, filepath: str) -> str | None:
    """Obtiene el contenido de un archivo en un commit específico del repo local."""
    try:
        result = subprocess.run(
            ["git", "show", f"{sha}:{filepath}"],
            cwd=config.REPO_LOCAL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n\n[... truncado {len(text) - max_chars} chars ...]\n\n" + text[-half:]


# ── Clasificación del tipo de PR ──────────────────────────────────────────────

LABEL_MAP = {
    "bug": "bugfix",
    "fix": "bugfix",
    "hotfix": "bugfix",
    "feature": "feature",
    "feat": "feature",
    "enhancement": "feature",
    "refactor": "refactor",
    "chore": "chore",
    "docs": "docs",
    "test": "test",
    "config": "config",
}

TITLE_PATTERNS = [
    (r"\b(fix|bug|hotfix|patch)\b", "bugfix"),
    (r"\b(feat|feature|add|implement|new)\b", "feature"),
    (r"\b(refactor|cleanup|clean|improve|simplify)\b", "refactor"),
    (r"\b(test|spec|coverage)\b", "test"),
    (r"\b(docs?|documentation|readme|comment)\b", "docs"),
    (r"\b(config|settings?|setup|deploy)\b", "config"),
]

PLACEHOLDER_PATTERNS = re.compile(
    r"^(fix|wip|update|changes|minor|misc|todo|temp|test|draft|quick fix|refactor)[.\s]*$",
    re.IGNORECASE,
)


def classify_pr(pr: dict) -> str:
    for label in pr.get("labels", []):
        label_lower = label.lower()
        for key, ptype in LABEL_MAP.items():
            if key in label_lower:
                return ptype
    title_lower = pr["title"].lower()
    for pattern, ptype in TITLE_PATTERNS:
        if re.search(pattern, title_lower):
            return ptype
    return "unknown"


# ── Score de calidad ──────────────────────────────────────────────────────────

def score_pr(pr: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    body = pr.get("body") or ""
    body_len = len(body.strip())

    if body_len >= 200:
        score += 30
        reasons.append("+30 descripción larga")
    elif body_len >= config.MIN_DESCRIPTION_CHARS:
        score += 15
        reasons.append("+15 descripción media")
    else:
        reasons.append(f" 0 descripción corta ({body_len} chars)")

    if PLACEHOLDER_PATTERNS.match(body.strip()):
        score -= 15
        reasons.append("-15 descripción placeholder")

    approvals = pr.get("approvals_count", 0)
    if approvals >= 2:
        score += 20
        reasons.append(f"+20 {approvals} approvals")
    elif approvals >= 1:
        score += 10
        reasons.append("+10 1 approval")

    if pr.get("review_comments"):
        score += 20
        reasons.append(f"+20 {len(pr['review_comments'])} review comments")

    if pr.get("issue_comments"):
        score += 10
        reasons.append(f"+10 {len(pr['issue_comments'])} issue comments")

    if pr.get("draft", False):
        score -= 20
        reasons.append("-20 draft PR")

    diff = pr.get("diff", "")
    diff_lines = len(diff.splitlines())
    if diff_lines < config.MIN_DIFF_LINES:
        score -= 10
        reasons.append(f"-10 diff trivial ({diff_lines} líneas)")

    return max(0, score), reasons


# ── Construcción del ejemplo de entrenamiento ─────────────────────────────────

def build_before_section(pr: dict) -> str:
    """
    Intenta obtener el contenido de los archivos ANTES del cambio usando git local.
    Si el SHA no está disponible localmente, usa el patch del PR como fallback.
    """
    base_sha = pr.get("base_sha", "")
    files = pr.get("files", [])

    # Solo archivos de texto (excluir binarios y archivos de assets)
    TEXT_EXTENSIONS = {
        ".cs", ".ts", ".js", ".html", ".css", ".scss", ".json",
        ".xml", ".config", ".csproj", ".sql", ".md", ".razor",
        ".cshtml", ".txt", ".yaml", ".yml",
    }

    sections = []
    total_chars = 0
    budget = config.MAX_USER_CHARS // 2  # La mitad del budget para "before"

    for f in files:
        if total_chars >= budget:
            sections.append(f"\n[... más archivos omitidos por límite de contexto ...]")
            break

        filepath = f["filename"]
        ext = Path(filepath).suffix.lower()
        if ext not in TEXT_EXTENSIONS:
            continue
        if f["status"] == "added":
            # Archivo nuevo: no hay "before"
            sections.append(f"### {filepath}\n*(archivo nuevo — no existía antes)*")
            continue

        content = git_file_at(base_sha, filepath)

        if content is None:
            # Fallback: mostrar el patch para dar contexto
            patch = f.get("patch", "")
            if patch:
                sections.append(f"### {filepath}\n*(usando patch como contexto)*\n```diff\n{patch}\n```")
        else:
            content = truncate(content, budget // max(len(files), 1))
            total_chars += len(content)
            lang = ext.lstrip(".")
            sections.append(f"### {filepath}\n```{lang}\n{content}\n```")

    return "\n\n".join(sections) if sections else "*(no se pudo obtener contenido previo)*"


def build_review_context(pr: dict) -> str:
    """Serializa los comentarios de review más relevantes."""
    lines = []

    # Reviews con cuerpo sustancial
    for rv in pr.get("reviews", []):
        body = (rv.get("body") or "").strip()
        if len(body) > 20:
            lines.append(f"[{rv['state']} por @{rv['author']}]: {body}")

    # Review comments inline
    for rc in pr.get("review_comments", []):
        body = (rc.get("body") or "").strip()
        if len(body) > 10:
            path = rc.get("path", "?")
            line = rc.get("line", "?")
            lines.append(f"[Comentario en {path}:{line} por @{rc['author']}]: {body}")

    return "\n".join(lines) if lines else ""


def build_example(pr: dict) -> dict:
    """Construye la tripla (system, user, assistant) para fine-tuning."""
    title = pr["title"]
    body  = (pr.get("body") or "").strip()
    diff  = (pr.get("diff") or "").strip()

    # Truncar diff si es muy grande
    diff_lines = diff.splitlines()
    if len(diff_lines) > config.MAX_DIFF_LINES:
        kept = diff_lines[:config.MAX_DIFF_LINES]
        diff = "\n".join(kept) + f"\n\n[... diff truncado: {len(diff_lines) - config.MAX_DIFF_LINES} líneas adicionales omitidas ...]"

    before_section = build_before_section(pr)
    review_context = build_review_context(pr)

    pr_type = classify_pr(pr)
    score, score_reasons = score_pr(pr)

    # ── User turn ──
    user_parts = [
        f"# PR #{pr['number']}: {title}",
        f"**Tipo:** {pr_type}",
        f"**Branch:** `{pr['head_branch']}` → `{pr['base_branch']}`",
    ]
    if pr.get("labels"):
        user_parts.append(f"**Labels:** {', '.join(pr['labels'])}")
    if body:
        user_parts.append(f"\n## Descripción\n{body}")
    if review_context:
        user_parts.append(f"\n## Feedback de reviewers\n{review_context}")
    user_parts.append(f"\n## Código ANTES del cambio\n{before_section}")
    user_parts.append("\nGenera el diff exacto que implementa los cambios descritos.")

    user_text = "\n".join(user_parts)
    user_text = truncate(user_text, config.MAX_USER_CHARS)

    # ── Assistant turn ──
    assistant_text = f"```diff\n{diff}\n```" if diff else "*(diff no disponible)*"
    assistant_text = truncate(assistant_text, config.MAX_ASSISTANT_CHARS)

    return {
        "pr_number": pr["number"],
        "pr_type": pr_type,
        "score": score,
        "score_reasons": score_reasons,
        "approvals": pr.get("approvals_count", 0),
        "diff_lines": len((pr.get("diff") or "").splitlines()),
        "messages": [
            {"role": "system", "content": config.SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Script 02 — Construcción de ejemplos de entrenamiento")
    print("=" * 60)

    examples_dir = config.OUTPUT_DIR / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(config.RAW_DIR.glob("pr_*.json"))
    if not raw_files:
        print("❌  No hay archivos en output/raw/. Corre 01_fetch_prs.py primero.")
        sys.exit(1)

    print(f"\n→ {len(raw_files)} PRs encontrados en {config.RAW_DIR}\n")

    results = {"included": 0, "skipped_score": 0, "skipped_diff": 0}

    for raw_file in tqdm(raw_files, desc="Procesando PRs", unit="PR"):
        pr = json.loads(raw_file.read_text(encoding="utf-8"))
        n = pr["number"]

        # Filtro de diff mínimo
        diff_lines = len((pr.get("diff") or "").splitlines())
        if diff_lines < config.MIN_DIFF_LINES:
            tqdm.write(f"  ✗ PR #{n}: diff trivial ({diff_lines} líneas)")
            results["skipped_diff"] += 1
            continue

        # Filtro de descripción mínima
        body_len = len((pr.get("body") or "").strip())
        if body_len < config.MIN_DESCRIPTION_CHARS:
            # No lo descartamos aún, pero el score va a penalizarlo
            pass

        example = build_example(pr)

        if example["score"] < config.MIN_SCORE:
            tqdm.write(
                f"  ✗ PR #{n}: score bajo ({example['score']}/100) — "
                + ", ".join(example["score_reasons"])
            )
            results["skipped_score"] += 1
            continue

        out = examples_dir / f"pr_{n}.json"
        out.write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")
        results["included"] += 1

    print(f"\n✅  Incluidos: {results['included']}")
    print(f"   Descartados (score bajo): {results['skipped_score']}")
    print(f"   Descartados (diff trivial): {results['skipped_diff']}")
    print(f"   Ejemplos en: {examples_dir}")


if __name__ == "__main__":
    main()
