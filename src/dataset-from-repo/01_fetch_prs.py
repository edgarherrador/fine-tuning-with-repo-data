"""
SCRIPT 1 — Extracción de PRs desde GitHub API

Descarga para cada PR:
  - Metadata (título, descripción, labels, autor, fechas)
  - Lista de archivos cambiados
  - Reviews (approve / request-changes + cuerpo del review)
  - Review comments (comentarios inline por línea)
  - Issue comments (discusión general del PR)
  - El diff completo del PR

Prerequisito: el token debe estar autorizado para SAML SSO de Trimble-Construction.
  → github.com/settings/tokens → Configure SSO → Authorize Trimble-Construction

Salida: output/raw/pr_{number}.json  (uno por PR)
         output/raw/_index.json       (lista de todos los PRs descargados)
"""

import json
import sys
import time
from pathlib import Path

import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
import config


# ── HTTP helpers ──────────────────────────────────────────────────────────────

HEADERS = {
    "Authorization": f"token {config.GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

DIFF_HEADERS = {
    **HEADERS,
    "Accept": "application/vnd.github.v3.diff",
}


def gh_get(url: str, params: dict = None) -> requests.Response:
    """GET con manejo automático de rate-limit."""
    while True:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 429 or (
            r.status_code == 403 and "rate limit" in r.text.lower()
        ):
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time(), 5)
            print(f"\n[rate-limit] Esperando {wait:.0f}s…", flush=True)
            time.sleep(wait)
            continue
        return r


def paginate(url: str, params: dict = None) -> list:
    """Descarga todas las páginas de una lista de la API."""
    params = {**(params or {}), "per_page": 100, "page": 1}
    results = []
    while True:
        r = gh_get(url, params)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        results.extend(page)
        params["page"] += 1
    return results


# ── Validación del token ──────────────────────────────────────────────────────

def validate_token() -> None:
    url = f"{config.GITHUB_API}/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}"
    r = gh_get(url)
    if r.status_code == 403 and "SAML" in r.text:
        print("❌  El token no está autorizado para la org Trimble-Construction vía SAML SSO.")
        print("    1. Ve a https://github.com/settings/tokens")
        print("    2. Busca el token → 'Configure SSO' → 'Authorize' para Trimble-Construction")
        print("    3. Vuelve a correr este script.")
        sys.exit(1)
    if r.status_code == 401:
        print(f"❌  Token inválido (401). Verifica GITHUB_TOKEN en config.py.")
        sys.exit(1)
    r.raise_for_status()
    repo = r.json()
    print(f"✅  Conectado a {repo['full_name']}  (rama default: {repo['default_branch']})")


# ── Extracción por PR ─────────────────────────────────────────────────────────

def fetch_pr_diff(pr_number: int) -> str:
    """Descarga el diff completo del PR como texto."""
    url = f"{config.GITHUB_API}/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/pulls/{pr_number}"
    r = requests.get(url, headers=DIFF_HEADERS, timeout=60)
    if r.status_code != 200:
        return ""
    return r.text


def fetch_reviews(pr_number: int) -> list:
    """Descarga todos los reviews (approve / request-changes / comment)."""
    url = f"{config.GITHUB_API}/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/pulls/{pr_number}/reviews"
    return paginate(url)


def fetch_review_comments(pr_number: int) -> list:
    """Comentarios inline de código (línea específica en el diff)."""
    url = f"{config.GITHUB_API}/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/pulls/{pr_number}/comments"
    return paginate(url)


def fetch_issue_comments(pr_number: int) -> list:
    """Comentarios generales en el hilo del PR."""
    url = f"{config.GITHUB_API}/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/issues/{pr_number}/comments"
    return paginate(url)


def fetch_pr_files(pr_number: int) -> list:
    """Lista de archivos cambiados con patch por archivo."""
    url = f"{config.GITHUB_API}/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/pulls/{pr_number}/files"
    return paginate(url)


def has_required_commenter(pr_number: int) -> bool:
    """Valida si el PR tiene al menos un comentario/review de algún autor requerido."""
    required_commenters = {
        commenter.strip().lower()
        for commenter in getattr(config, "REQUIRED_COMMENTERS", [])
        if commenter and commenter.strip()
    }

    if not required_commenters:
        return True

    issue_comments = fetch_issue_comments(pr_number)
    if any((c.get("user") or {}).get("login", "").lower() in required_commenters for c in issue_comments):
        return True

    review_comments = fetch_review_comments(pr_number)
    if any((c.get("user") or {}).get("login", "").lower() in required_commenters for c in review_comments):
        return True

    reviews = fetch_reviews(pr_number)
    return any((r.get("user") or {}).get("login", "").lower() in required_commenters for r in reviews)


def fetch_single_pr(pr: dict) -> dict:
    """Compila toda la información de un PR en un solo dict."""
    n = pr["number"]
    diff           = fetch_pr_diff(n)
    reviews        = fetch_reviews(n)
    review_comments = fetch_review_comments(n)
    issue_comments = fetch_issue_comments(n)
    files          = fetch_pr_files(n)

    approvals = [r for r in reviews if r["state"] == "APPROVED"]
    changes_requested = [r for r in reviews if r["state"] == "CHANGES_REQUESTED"]

    return {
        "number": n,
        "title": pr["title"],
        "body": pr.get("body") or "",
        "state": pr["state"],
        "draft": pr.get("draft", False),
        "labels": [lb["name"] for lb in pr.get("labels", [])],
        "author": pr["user"]["login"],
        "created_at": pr["created_at"],
        "merged_at": pr.get("merged_at"),
        "base_branch": pr["base"]["ref"],
        "base_sha": pr["base"]["sha"],
        "head_branch": pr["head"]["ref"],
        "head_sha": pr["head"]["sha"],
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_files": pr.get("changed_files", 0),
        "approvals_count": len(approvals),
        "approvers": [r["user"]["login"] for r in approvals],
        "changes_requested_count": len(changes_requested),
        "reviews": [
            {
                "state": r["state"],
                "body": r.get("body") or "",
                "author": r["user"]["login"],
                "submitted_at": r["submitted_at"],
            }
            for r in reviews
        ],
        "review_comments": [
            {
                "path": c["path"],
                "line": c.get("line") or c.get("original_line"),
                "body": c["body"],
                "author": c["user"]["login"],
                "created_at": c["created_at"],
                "in_reply_to_id": c.get("in_reply_to_id"),
            }
            for c in review_comments
        ],
        "issue_comments": [
            {
                "body": c["body"],
                "author": c["user"]["login"],
                "created_at": c["created_at"],
            }
            for c in issue_comments
        ],
        "files": [
            {
                "filename": f["filename"],
                "status": f["status"],      # added | modified | removed | renamed
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": f.get("patch", ""),   # puede estar ausente en archivos binarios o muy grandes
            }
            for f in files
        ],
        "diff": diff,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Script 01 — Extracción de PRs desde GitHub API")
    print("=" * 60)

    validate_token()

    # Listar PRs
    print(f"\nListando PRs (state={config.PR_STATE})…")
    pr_list_url = f"{config.GITHUB_API}/repos/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/pulls"
    pr_list = paginate(pr_list_url, {"state": config.PR_STATE, "sort": "updated", "direction": "desc"})

    if config.PR_LIMIT:
        pr_list = pr_list[: config.PR_LIMIT]

    print(f"→ {len(pr_list)} PRs encontrados")

    if getattr(config, "REQUIRED_COMMENTERS", []):
        commenters_display = ", ".join(f"@{user}" for user in config.REQUIRED_COMMENTERS)
        print(f"Filtrando PRs con comentarios/reviews de: {commenters_display}…")
        filtered_pr_list = []
        for pr in tqdm(pr_list, desc="Filtrando PRs", unit="PR"):
            if has_required_commenter(pr["number"]):
                filtered_pr_list.append(pr)

        pr_list = filtered_pr_list
        print(f"→ {len(pr_list)} PRs cumplen el filtro\n")
    else:
        print()

    # Descargar uno por uno
    index = []
    failed = []

    for pr in tqdm(pr_list, desc="Descargando PRs", unit="PR"):
        n = pr["number"]
        out_file = config.RAW_DIR / f"pr_{n}.json"

        if out_file.exists():
            tqdm.write(f"  ↩ PR #{n} ya existe, saltando")
            index.append({"number": n, "title": pr["title"], "cached": True})
            continue

        try:
            data = fetch_single_pr(pr)
            out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            index.append({"number": n, "title": pr["title"], "cached": False})
        except Exception as exc:
            tqdm.write(f"  ⚠ PR #{n} error: {exc}")
            failed.append(n)

    # Índice global
    index_file = config.RAW_DIR / "_index.json"
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅  Descargados: {len(index) - len(failed)} PRs")
    if failed:
        print(f"⚠   Fallidos: {failed}")
    print(f"    Archivos en: {config.RAW_DIR}")


if __name__ == "__main__":
    main()
