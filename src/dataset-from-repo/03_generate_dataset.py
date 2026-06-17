"""
SCRIPT 3 — Generar JSONL final para fine-tuning

Lee todos los ejemplos de output/examples/, estima tokens,
ordena por score, divide en train/eval, y escribe:
  output/dataset.jsonl
  output/dataset_train.jsonl
  output/dataset_eval.jsonl
  output/stats.json            (estadísticas del dataset)

El formato de cada línea es el messages format compatible con
Qwen3, OpenAI fine-tuning API y Unsloth:

  {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
"""

import json
import math
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
import config


# ── Estimación de tokens (sin cargar modelo) ──────────────────────────────────

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")  # Aproximación razonable para Qwen
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except ImportError:
    # Fallback: ~4 chars por token
    def count_tokens(text: str) -> int:
        return len(text) // 4


def example_tokens(example: dict) -> int:
    total = 0
    for msg in example["messages"]:
        total += count_tokens(msg["content"])
    return total


# ── Estadísticas ──────────────────────────────────────────────────────────────

def compute_stats(examples: list[dict]) -> dict:
    tokens_list = [ex["_tokens"] for ex in examples]
    scores_list = [ex["score"] for ex in examples]
    diff_lines_list = [ex["diff_lines"] for ex in examples]

    type_counts: dict[str, int] = {}
    for ex in examples:
        t = ex["pr_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    def percentile(lst, p):
        lst_sorted = sorted(lst)
        idx = int(math.ceil(len(lst_sorted) * p / 100)) - 1
        return lst_sorted[max(0, idx)]

    return {
        "total_examples": len(examples),
        "total_tokens": sum(tokens_list),
        "tokens": {
            "min": min(tokens_list),
            "max": max(tokens_list),
            "mean": sum(tokens_list) // len(tokens_list),
            "p50": percentile(tokens_list, 50),
            "p90": percentile(tokens_list, 90),
            "p95": percentile(tokens_list, 95),
        },
        "scores": {
            "min": min(scores_list),
            "max": max(scores_list),
            "mean": sum(scores_list) // len(scores_list),
        },
        "diff_lines": {
            "min": min(diff_lines_list),
            "max": max(diff_lines_list),
            "mean": sum(diff_lines_list) // len(diff_lines_list),
        },
        "pr_types": type_counts,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Script 03 — Generación de dataset JSONL")
    print("=" * 60)

    examples_dir = config.OUTPUT_DIR / "examples"
    example_files = sorted(examples_dir.glob("pr_*.json"))

    if not example_files:
        print("❌  No hay ejemplos en output/examples/. Corre 02_build_examples.py primero.")
        sys.exit(1)

    print(f"\n→ Cargando {len(example_files)} ejemplos…")

    examples = []
    skipped_tokens = 0

    for f in tqdm(example_files, desc="Estimando tokens"):
        ex = json.loads(f.read_text(encoding="utf-8"))
        tokens = example_tokens(ex)
        ex["_tokens"] = tokens

        # Descartar ejemplos que excedan el contexto del modelo (32K tokens)
        if tokens > 28_000:
            tqdm.write(f"  ✗ PR #{ex['pr_number']}: demasiado largo ({tokens} tokens), descartado")
            skipped_tokens += 1
            continue

        examples.append(ex)

    if not examples:
        print("❌  Ningún ejemplo pasó los filtros.")
        sys.exit(1)

    # Ordenar por score descendente
    examples.sort(key=lambda x: x["score"], reverse=True)

    # Split train / eval
    eval_count = max(1, int(len(examples) * config.EVAL_RATIO))
    train_count = len(examples) - eval_count

    # Estrategia: eval = los mejores del final (más representativos)
    # Train = el resto ordenado por score
    eval_examples  = examples[:eval_count]
    train_examples = examples[eval_count:]

    # ── Escribir archivos ──
    def write_jsonl(path: Path, exs: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for ex in exs:
                record = {"messages": ex["messages"]}
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    write_jsonl(config.DATASET_FILE, examples)
    write_jsonl(config.TRAIN_FILE, train_examples)
    write_jsonl(config.EVAL_FILE, eval_examples)

    # ── Estadísticas ──
    stats = compute_stats(examples)
    stats["train_examples"] = train_count
    stats["eval_examples"] = eval_count
    stats["skipped_token_limit"] = skipped_tokens

    stats_file = config.OUTPUT_DIR / "stats.json"
    stats_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Reporte ──
    print(f"\n{'='*60}")
    print(f"✅  Dataset generado")
    print(f"{'='*60}")
    print(f"  Total ejemplos : {stats['total_examples']}")
    print(f"  Train          : {train_count}")
    print(f"  Eval           : {eval_count}")
    print(f"  Descartados (tokens): {skipped_tokens}")
    print(f"")
    print(f"  Tokens totales : {stats['total_tokens']:,}")
    print(f"  Tokens / ejemplo (media): {stats['tokens']['mean']:,}")
    print(f"  Tokens / ejemplo (p95)  : {stats['tokens']['p95']:,}")
    print(f"")
    print(f"  Score medio    : {stats['scores']['mean']}/100")
    print(f"  Diff lines (media): {stats['diff_lines']['mean']}")
    print(f"")
    print(f"  Tipos de PR    :")
    for ptype, count in sorted(stats["pr_types"].items(), key=lambda x: -x[1]):
        print(f"    {ptype:<15} {count}")
    print(f"")
    print(f"  📄  {config.TRAIN_FILE}")
    print(f"  📄  {config.EVAL_FILE}")
    print(f"  📊  {stats_file}")


if __name__ == "__main__":
    main()
