import sys
from pathlib import Path


def yes(v):
    return str(v).strip().lower() in ("si", "sí", "s", "yes", "y", "1", "true", "x")


def main(folder, sheets):
    folder = Path(folder)
    key = {r["codigo"]: r for r in csv.DictReader(open(folder / "clave_NO_ABRIR.csv", encoding="utf-8"))}
    rows = []
    for sh in sheets:
        for r in csv.DictReader(open(sh, encoding="utf-8-sig")):
            code = r.get("codigo", "").strip()
            if code not in key or not r.get("aceptable (si/no)", "").strip():
                continue
            k = key[code]
            q = r.get("calidad (1-5)", "").strip()
            rows.append({"codigo": code, "evaluador": r.get("evaluador", "") or Path(sh).stem,
                         "origen": k["origen"], "familia": k["familia"],
                         "aceptable": yes(r["aceptable (si/no)"]),
                         "calidad": float(q) if q else None,
                         "parece_a_mano": yes(r.get("parece hecho a mano (si/no)", "")),
                         "comentario": r.get("comentario", "")})
    if not rows:
        raise SystemExit("No hay respuestas llenas en las planillas.")

    with open(folder / "respuestas_unidas.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    def group(o):
        return [r for r in rows if r["origen"] == o]

    R, G = group("real"), group("generado")
    acc_r = sum(r["aceptable"] for r in R); acc_g = sum(r["aceptable"] for r in G)
    hand_r = sum(r["parece_a_mano"] for r in R); hand_g = sum(r["parece_a_mano"] for r in G)
    qr = [r["calidad"] for r in R if r["calidad"] is not None]
    qg = [r["calidad"] for r in G if r["calidad"] is not None]

    try:
        from scipy.stats import fisher_exact, mannwhitneyu
        p_acc = fisher_exact([[acc_r, len(R) - acc_r], [acc_g, len(G) - acc_g]])[1] if R and G else float("nan")
        p_hand = fisher_exact([[hand_r, len(R) - hand_r], [hand_g, len(G) - hand_g]])[1] if R and G else float("nan")
        p_q = mannwhitneyu(qr, qg).pvalue if len(qr) > 1 and len(qg) > 1 else float("nan")
    except ImportError:
        p_acc = p_hand = p_q = float("nan")

    def pct(a, n):
        return f"{a} de {n} ({100 * a / n:.0f} %)" if n else "–"

    def mean(v):
        return f"{sum(v) / len(v):.2f}" if v else "–"

    # aciertos: reconocer un generado como "no hecho a mano" o un real como "hecho a mano"
    correct = sum((r["origen"] == "real") == r["parece_a_mano"] for r in rows)
    md = ["# Resultados de la prueba ciega\n",
          f"{len(rows)} respuestas de {len({r['evaluador'] for r in rows})} evaluador(es) sobre "
          f"{len({r['codigo'] for r in rows})} niveles.\n",
          "| | Reales | Generados | p |", "|---|---|---|---|",
          f"| Valorados como aceptables | {pct(acc_r, len(R))} | {pct(acc_g, len(G))} | {p_acc:.3f} |",
          f"| Calidad promedio (1-5) | {mean(qr)} | {mean(qg)} | {p_q:.3f} |",
          f"| Le parecieron hechos a mano | {pct(hand_r, len(R))} | {pct(hand_g, len(G))} | {p_hand:.3f} |",
          "",
          f"Acierto al distinguir real de generado: {pct(correct, len(rows))}. "
          "Un 50 % equivale a adivinar al azar: cuanto más cerca de 50 %, menos se distinguen los "
          "niveles generados de los hechos a mano.",
          "",
          "p: prueba exacta de Fisher para proporciones y de Mann-Whitney para la calidad "
          "(p < 0,05 indica una diferencia significativa entre reales y generados)."]
    (folder / "resultados_prueba_ciega.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    main(sys.argv[1], sys.argv[2:])
