# Dataset Pipeline — Fine-Tuning desde PRs de GitHub

Genera un dataset JSONL para fine-tuning de **Qwen3-35B-A22B** usando el historial
de Pull Requests de ProjectSight.

## Prerequisitos

### 1. Autorizar el token para SAML SSO (obligatorio)

El token PAT de GitHub necesita autorización explícita para la org `Trimble-Construction`:

1. Ve a https://github.com/settings/tokens
2. Busca tu token → **Configure SSO** → **Authorize** para `Trimble-Construction`
3. Confirma que funciona: `curl -H "Authorization: token TU_TOKEN" https://api.github.com/repos/Trimble-Construction/projectsight`

### 2. Instalar dependencias Python

```bash
cd scripts/dataset
pip install -r requirements.txt
```

### 3. Configurar `config.py`

El token ya está en `config.py`. Si quieres sobreescribirlo sin editar el archivo:

```bash
export GITHUB_TOKEN=ghp_...        # Linux/Mac
$env:GITHUB_TOKEN = "ghp_..."      # PowerShell
```

---

## Correr el pipeline

### Fase 1 — PoC con PRs abiertos (~46 PRs)

```bash
python 01_fetch_prs.py      # ~5-10 min (descarga API)
python 02_build_examples.py # ~2-5 min (cruza con git local)
python 03_generate_dataset.py
```

### Fase 2 — Dataset completo (10,000+ PRs merged)

Edita `config.py`:
```python
PR_STATE = "closed"    # PRs cerrados (incluye merged)
PR_LIMIT = None        # Sin límite
```

Luego corre el mismo pipeline. Con 10K PRs espera ~2-4 horas para el script 01.

---

## Estructura de salida

```
output/
  raw/
    _index.json          # Índice de todos los PRs descargados
    pr_1234.json         # JSON crudo por PR (metadata + diff + reviews)
    pr_1235.json
    ...
  examples/
    pr_1234.json         # Ejemplo procesado con score de calidad
    ...
  dataset.jsonl          # Dataset completo
  dataset_train.jsonl    # 90% para entrenamiento
  dataset_eval.jsonl     # 10% para evaluación
  stats.json             # Estadísticas del dataset
```

---

## Formato de cada ejemplo

```jsonl
{
  "messages": [
    {
      "role": "system",
      "content": "Eres un experto en el codebase de ProjectSight..."
    },
    {
      "role": "user",
      "content": "# PR #1234: Fix export de sitios\n**Tipo:** bugfix\n...\n## Código ANTES del cambio\n..."
    },
    {
      "role": "assistant",
      "content": "```diff\n--- a/Core/Services/ExportService.cs\n+++ b/Core/Services/ExportService.cs\n..."
    }
  ]
}
```

---

## Score de calidad (0-100)

| Criterio | Puntos |
|----------|--------|
| Descripción ≥ 200 chars | +30 |
| Descripción ≥ 80 chars | +15 |
| ≥ 2 reviewers aprobaron | +20 |
| ≥ 1 reviewer aprobó | +10 |
| Tiene review comments inline | +20 |
| Tiene comentarios en el hilo | +10 |
| Draft PR | -20 |
| Diff trivial (< 5 líneas) | descartado |
| Descripción placeholder ("fix", "wip") | -15 |

Solo se incluyen PRs con score ≥ 40 (ajustable en `config.py`).

---

## Tips para Fase 2

- **Rate limit de GitHub**: ~5,000 req/hora con PAT. Para 10K PRs + sus detalles se necesitan ~50-100K requests. El script maneja automáticamente el rate limit.
- **PRs más valiosos**: Los que tienen 8-20 review comments son los mejores — contienen el razonamiento implícito del equipo.
- **Filtrar bots**: Copilot, Dependabot y cherry-picks automáticos tienen descripciones pobres y score bajo → se descartan solos.
- **Escalado**: Para correr en background: `nohup python 01_fetch_prs.py > logs/fetch.log &`
