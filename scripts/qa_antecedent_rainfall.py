#!/usr/bin/env python
"""READ-ONLY QA of the antecedent-rainfall table against the daily AOI series (V2.3). Independent re-computation of every prior-N-day window.

Convention audited: window for scene date D and length N = the N labelled days [D-N, D-1]; the scene date D itself is EXCLUDED. A window with ANY expected day that is missing / not 'OK'
is NOT computed (never a partial sum, never zero-filled). Re-calculation = sum of the daily AOI-mean values in the daily series (area-weighted AOI mean is linear, so the AOI mean of an
N-day total equals the sum of the N daily AOI means provided every day has the same weights and complete coverage; the min daily coverage is reported so that caveat is visible).
This checks ARITHMETIC AND DATE COVERAGE only; it does not verify the CHIRPS day-label convention, the AOI weights, or the rasters themselves.
Never modifies an input; never overwrites; the corrected CSV is written ONLY as a separately named CANDIDATE in the new QA directory, and only if a discrepancy is found.
Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\qa_antecedent_rainfall.py"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src.flood_detection.s1_persistence import sha256_file
from src.utils import paths

TAB = "outputs/chirps_2021/tables"
ANTE_DEFAULT = f"{TAB}/rainfall_chirps_2021_2021_sep_nov_antecedent_before_s1.csv"
DAILY_DEFAULT = f"{TAB}/rainfall_chirps_2021_2021_sep_nov_daily_series.csv"
OUT_DEFAULT = "outputs/chirps_2021/qa_antecedent"
STEM = "antecedent_qa"
NAMES = {"qa_table": f"{STEM}_table.csv", "summary": f"{STEM}_summary.csv", "report": f"{STEM}_report.md", "manifest": f"{STEM}_manifest.json", "candidate": "rainfall_chirps_2021_2021_sep_nov_antecedent_before_s1_CANDIDATE_recalc.csv"}


def window_dates(d0, n): return [d0 - timedelta(days=k) for k in range(n, 0, -1)]            # [D-N, D-1]; D excluded


def decimals(series):
    s = series.dropna().astype(str); return max([len(x.split(".")[1]) if "." in x and "e" not in x.lower() else 0 for x in s] or [0])


def tolerance(n, dec): return 0.005 + n * 0.5 * 10 ** (-dec) if dec < 6 else 0.005 + 1e-6      # reported value is rounded to 2 dp; daily inputs may themselves be rounded


def audit(ante, daily):
    """Returns (qa_rows DataFrame, problems list, candidate DataFrame). Pure function: no file access."""
    problems = []
    need_d = {"date", "status", "aoi_mean_mm"}
    if not need_d <= set(daily.columns): return None, [f"daily series lacks columns {sorted(need_d - set(daily.columns))}"], None
    if "s1_date" not in ante.columns: return None, ["antecedent table lacks s1_date"], None
    wins = sorted(int(m.group(1)) for c in ante.columns if (m := re.fullmatch(r"prior_(\d+)d_aoi_mean_mm", c)))
    if not wins: return None, ["antecedent table has no prior_<N>d_aoi_mean_mm columns"], None
    dd = daily.copy(); dd["_d"] = pd.to_datetime(dd["date"]).dt.date
    if dd["_d"].duplicated().any(): problems.append("duplicate dates in the daily series: " + ", ".join(map(str, dd.loc[dd["_d"].duplicated(), "_d"])))
    dec = decimals(daily["aoi_mean_mm"]); by = {r["_d"]: r for _, r in dd.drop_duplicates("_d", keep="first").iterrows()}
    cov_col = "aoi_valid_coverage" if "aoi_valid_coverage" in dd.columns else None
    rows, cand = [], ante.copy()
    for i, a in ante.iterrows():
        d0 = date.fromisoformat(str(a["s1_date"])); tot_prev = {}
        for n in wins:
            exp = window_dates(d0, n); avail, missing, vals, covs = [], [], [], []
            for d in exp:
                r = by.get(d); ok = r is not None and str(r["status"]) == "OK" and pd.notna(r["aoi_mean_mm"])
                if ok:
                    avail.append(d); vals.append(float(r["aoi_mean_mm"]))
                    if cov_col: covs.append(float(r[cov_col]))
                else: missing.append((d, "absent from series" if r is None else str(r["status"])))
            recalc = None if missing else float(np.sum(vals)); rep = a.get(f"prior_{n}d_aoi_mean_mm"); rep = None if pd.isna(rep) else float(rep)
            rep_miss = a.get(f"prior_{n}d_missing_days"); rep_miss = None if rep_miss is None or pd.isna(rep_miss) else int(rep_miss)
            neg = [d for d, v in zip(avail, vals) if v < 0]
            if missing and rep is None: res = "CONSISTENT_NOT_COMPUTABLE (window incomplete, reported blank)"
            elif missing and rep is not None: res = "MISMATCH: reported a value although expected days are missing/unusable"
            elif rep is None: res = "MISMATCH: reported blank although all expected days are available"
            elif abs(rep - recalc) <= tolerance(n, dec): res = "MATCH"
            else: res = "MISMATCH: value differs"
            if rep_miss is not None and rep_miss != len(missing): res += f"; MISMATCH: reported missing_days {rep_miss} != {len(missing)}"
            if neg: res += "; NEGATIVE daily values present"
            tot_prev[n] = (recalc, rep)
            rows.append({"s1_date": a["s1_date"], "window_days": n, "convention": "[D-N, D-1], D excluded", "window_start": exp[0].isoformat(), "window_end": exp[-1].isoformat(),
                         "expected_n": len(exp), "expected_dates": ";".join(map(str, exp)), "available_n": len(avail), "available_dates": ";".join(map(str, avail)), "missing_n": len(missing),
                         "missing_dates": ";".join(f"{d}({why})" for d, why in missing), "reported_mean_mm": rep, "reported_missing_days": rep_miss,
                         "recalculated_mean_mm": None if recalc is None else round(recalc, 4), "difference_mm": None if (recalc is None or rep is None) else round(rep - recalc, 4),
                         "tolerance_mm": round(tolerance(n, dec), 4), "min_daily_aoi_coverage": min(covs) if covs else None, "result": res})
            if recalc is not None and (rep is None or abs(rep - recalc) > tolerance(n, dec)): cand.loc[i, f"prior_{n}d_aoi_mean_mm"] = round(recalc, 2)
            if recalc is None and rep is not None: cand.loc[i, f"prior_{n}d_aoi_mean_mm"] = np.nan
        # internal consistency: totals of nested windows cannot decrease with N when daily rainfall is non-negative
        seq = [(n, v[1]) for n, v in sorted(tot_prev.items()) if v[1] is not None]
        for (n1, v1), (n2, v2) in zip(seq, seq[1:]):
            if v2 + 0.011 < v1: problems.append(f"{a['s1_date']}: reported prior_{n2}d ({v2}) < prior_{n1}d ({v1}); nested windows cannot decrease")
    q = pd.DataFrame(rows)
    return q, problems, cand


def table_checks(ante):
    """Checks that need ONLY the antecedent table (no daily series): date coverage of the expected windows, reported missing-day counts, blanks, nested-window monotonicity and the cross-scene
    inequality 30d(D)-14d(D) <= 30d(P) for consecutive scenes (those 16 days D-30..D-15 lie inside the previous scene's 30-day window when D-P <= 15). These are necessary conditions
    for non-negative rainfall; they are NOT a recalculation and cannot detect an error that preserves them. Returns (rows DataFrame, findings list)."""
    wins = sorted(int(m.group(1)) for c in ante.columns if (m := re.fullmatch(r"prior_(\d+)d_aoi_mean_mm", c))); rows, find = [], []
    a = ante.sort_values("s1_date").reset_index(drop=True)
    for i, r in a.iterrows():
        d0 = date.fromisoformat(str(r["s1_date"])); prev = None
        for n in wins:
            ex = window_dates(d0, n); v = r.get(f"prior_{n}d_aoi_mean_mm"); m = r.get(f"prior_{n}d_missing_days")
            rows.append({"s1_date": r["s1_date"], "window_days": n, "window_start": ex[0].isoformat(), "window_end": ex[-1].isoformat(), "expected_n": len(ex), "scene_date_excluded": d0 not in ex,
                         "reported_mean_mm": None if pd.isna(v) else float(v), "reported_missing_days": None if pd.isna(m) else int(m), "available_dates": "NOT ASSESSED (daily series not supplied)", "recalculated_mean_mm": "NOT ASSESSED"})
            if pd.isna(v): find.append(f"{r['s1_date']} prior_{n}d is blank")
            if not pd.isna(m) and int(m) != 0: find.append(f"{r['s1_date']} prior_{n}d reports {int(m)} missing days")
            if prev is not None and not pd.isna(v) and v + 0.011 < prev[1]: find.append(f"{r['s1_date']}: prior_{n}d ({v}) < prior_{prev[0]}d ({prev[1]})")
            if not pd.isna(v): prev = (n, float(v))
        if i > 0 and {14, 30} <= set(wins):
            P = date.fromisoformat(str(a.loc[i - 1, "s1_date"]))
            if (d0 - P).days <= 15:
                lhs = r["prior_30d_aoi_mean_mm"] - r["prior_14d_aoi_mean_mm"]; rhs = a.loc[i - 1, "prior_30d_aoi_mean_mm"]
                if lhs > rhs + 0.021: find.append(f"{r['s1_date']}: 30d-14d ({lhs:.2f}) exceeds the previous scene's 30d ({rhs}); impossible for non-negative rainfall")
    return pd.DataFrame(rows), find


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); ap.add_argument("--antecedent-csv", default=ANTE_DEFAULT); ap.add_argument("--daily-csv", default=DAILY_DEFAULT); ap.add_argument("--outdir", default=OUT_DEFAULT); ap.add_argument("--table-only", action="store_true", help="only the checks that need the antecedent table (no daily series)")
    a = ap.parse_args(); rp = lambda x: Path(x) if Path(x).is_absolute() else paths.ROOT / x                        # noqa: E731
    ia, idl, od = rp(a.antecedent_csv), rp(a.daily_csv), rp(a.outdir)
    stops = [f"MISSING input: {p}" for p in ((ia,) if a.table_only else (ia, idl)) if not p.exists()]
    if od.resolve() in (ia.resolve().parent, idl.resolve().parent): stops.append(f"--outdir must be a NEW directory, not the folder holding the inputs ({od})")
    existing = [str(od / v) for v in NAMES.values() if (od / v).exists()]
    if existing: stops.append("existing QA outputs would be overwritten: " + "; ".join(existing))
    if stops: print("STOP - nothing was written."); [print("  -", s) for s in stops]; return 2
    if a.table_only:
        h0 = sha256_file(ia); q, find = table_checks(pd.read_csv(ia)); od.mkdir(parents=True, exist_ok=True); q.to_csv(od / NAMES["qa_table"], index=False)
        (od / NAMES["report"]).write_text("# Antecedent rainfall QA - TABLE-ONLY (no daily series supplied)\n\nRe-calculation NOT performed. Findings:\n" + "".join(f"- {x}\n" for x in find or ["none (necessary conditions only)"]), encoding="utf-8")
        (od / NAMES["manifest"]).write_text(json.dumps({"mode": "table-only", "antecedent_sha256_before": h0, "antecedent_sha256_after": sha256_file(ia), "findings": find, "recalculated": False}, indent=1), encoding="utf-8")
        print(f"done (table-only; NO recalculation). findings: {len(find)}"); return 0 if h0 == sha256_file(ia) else 3
    h0 = {str(p): sha256_file(p) for p in (ia, idl)}                                                              # hash before parsing
    ante, daily = pd.read_csv(ia), pd.read_csv(idl); q, problems, cand = audit(ante, daily)
    if q is None: print("STOP - nothing was written."); [print("  -", s) for s in problems]; return 2
    od.mkdir(parents=True, exist_ok=True); q.to_csv(od / NAMES["qa_table"], index=False)
    q["_k"] = q["result"].str.split(";").str[0].str.split(":").str[0].str.split(" ").str[0]
    summ = q.groupby(["window_days", "_k"]).size().rename("windows").reset_index().rename(columns={"_k": "result_class"}); summ.to_csv(od / NAMES["summary"], index=False)
    bad = q[q["result"].str.contains("MISMATCH|NEGATIVE")]; wrote_cand = False
    if len(bad): cand.to_csv(od / NAMES["candidate"], index=False); wrote_cand = True
    L = ["# Antecedent rainfall QA (arithmetic and date coverage only)", "", "Convention audited: `[D-N, D-1]`, scene date D excluded. Missing/unusable days are never treated as zero; an incomplete window is not computed.",
         f"Inputs (read-only): `{ia}`, `{idl}`. Daily AOI-mean decimals detected: {decimals(daily['aoi_mean_mm'])}.", "",
         "Scope: this verifies window dates and sums against the daily AOI-mean series. It does NOT verify CHIRPS day-label timing, AOI weights or the source rasters.", "",
         f"Windows audited: {len(q)}. Non-MATCH results: {int((~q['result'].str.startswith('MATCH')).sum())}. Internal-consistency problems: {len(problems)}.", ""]
    L += ["| S1 date | N | window | expected | available | missing | reported | recalculated | result |", "|---|---|---|---|---|---|---|---|---|"]
    for _, r in q.iterrows(): L.append(f"| {r.s1_date} | {r.window_days} | {r.window_start}..{r.window_end} | {r.expected_n} | {r.available_n} | {r.missing_n}{(' ' + r.missing_dates) if r.missing_dates else ''} | {r.reported_mean_mm} | {r.recalculated_mean_mm} | {r.result} |")
    L += ["", "## Internal consistency problems"] + (["- " + p for p in problems] or ["- none"])
    L += ["", "## Candidate correction", ("- Written as a separately named CANDIDATE (the existing CSV is untouched): `" + NAMES["candidate"] + "`; explain the discrepancy before any replacement.") if wrote_cand else "- No discrepancy found, so no candidate file was written."]
    (od / NAMES["report"]).write_text("\n".join(L) + "\n", encoding="utf-8")
    h1 = {str(p): sha256_file(p) for p in (ia, idl)}
    (od / NAMES["manifest"]).write_text(json.dumps({"inputs_sha256_before": h0, "inputs_sha256_after": h1, "inputs_unchanged": h0 == h1, "windows": len(q), "non_match": int((~q["result"].str.startswith("MATCH")).sum()),
                                                    "problems": problems, "candidate_written": wrote_cand, "status_json_modified": False}, indent=1, sort_keys=True), encoding="utf-8")
    print(f"done. {len(q)} windows; non-MATCH {int((~q['result'].str.startswith('MATCH')).sum())}; consistency problems {len(problems)}; candidate written: {wrote_cand}; inputs unchanged: {h0 == h1}\n  report: {od / NAMES['report']}")
    return 0 if h0 == h1 else 3


if __name__ == "__main__":
    sys.exit(main() or 0)
