#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, math, statistics
from pathlib import Path

def pct(xs, q):
    if not xs: return math.nan
    ys=sorted(xs); k=(len(ys)-1)*q
    lo=int(math.floor(k)); hi=int(math.ceil(k))
    if lo==hi: return ys[lo]
    return ys[lo]*(hi-k)+ys[hi]*(k-lo)

def mean(xs): return statistics.fmean(xs) if xs else math.nan

def readcsv(p):
    with p.open(newline="") as f: return list(csv.DictReader(f))

def b(v):
    return str(v).strip().lower() in {"1","true","yes"}

def analyze_run(d: Path, cond: str, rep: int):
    pub=readcsv(d/"publisher_metrics.csv")
    sub=readcsv(d/"subscriber_metrics.csv")
    if cond=="A1":
        logical_ids=[r["seq"] for r in pub]
        physical=len(pub)
        pub_ok=sum(int(r.get("success","0") or 0) for r in pub)
        pub_payload=[float(r["payload_bytes"]) for r in pub if r.get("payload_bytes")]
        decrypt_fail=0
        first={}
        duplicates=0
        for r in sub:
            k=r.get("seq","")
            duplicates += int(r.get("duplicate","0") or 0)
            if k and k not in first and r.get("delivery_latency_ms","") not in ("",None):
                first[k]=float(r["delivery_latency_ms"])
    else:
        logical_ids=[r["logical_seq"] for r in pub if r.get("logical_seq","")!=""]
        physical=len(pub)
        pub_ok=sum(1 for r in pub if b(r.get("success","")))
        pub_payload=[float(r["payload_encrypted_bytes"]) for r in pub if r.get("payload_encrypted_bytes","")!=""]
        decrypt_fail=sum(1 for r in sub if not b(r.get("decrypt_success","")))
        first={}
        duplicates=sum(1 for r in sub if b(r.get("duplicate","")))
        for r in sub:
            k=r.get("logical_seq","")
            if not b(r.get("decrypt_success","")): continue
            if k and k not in first and r.get("delivery_latency_ms","") not in ("",None):
                first[k]=float(r["delivery_latency_ms"])
    logical=len(set(logical_ids))
    lats=list(first.values())
    extra=max(0, physical-logical)
    return {
        "condition":cond,"repetition":rep,
        "logical_messages":logical,
        "physical_publications":physical,
        "extra_publications":extra,
        "extra_rate_pct":100*extra/logical if logical else math.nan,
        "publisher_success":pub_ok,
        "subscriber_rows":len(sub),
        "subscriber_unique_for_latency":len(first),
        "subscriber_duplicates":duplicates,
        "decrypt_failures":decrypt_fail,
        "latency_mean_ms":mean(lats),
        "latency_median_ms":pct(lats,.5),
        "latency_p95_ms":pct(lats,.95),
        "latency_p99_ms":pct(lats,.99),
        "payload_per_physical_mean_bytes":mean(pub_payload),
        "payload_per_logical_bytes":sum(pub_payload)/logical if logical else math.nan,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root")
    args=ap.parse_args()
    root=Path(args.root)
    rows=[]
    for rep in range(1,6):
        for cond in ("A1","A2","A3","A4"):
            d=root/f"formal-{cond.lower()}-r{rep:02d}"
            if d.exists():
                rows.append(analyze_run(d,cond,rep))
    if len(rows)!=20:
        raise SystemExit(f"expected 20 run directories, found {len(rows)}")

    fields=list(rows[0])
    with (root/"run_summary.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

    condrows=[]
    for cond in ("A1","A2","A3","A4"):
        rr=[r for r in rows if r["condition"]==cond]
        cr={"condition":cond,"runs":len(rr)}
        for k in ("latency_mean_ms","latency_median_ms","latency_p95_ms","latency_p99_ms",
                  "payload_per_physical_mean_bytes","payload_per_logical_bytes","extra_rate_pct"):
            vals=[float(r[k]) for r in rr]
            cr[k+"_mean"]=mean(vals)
            cr[k+"_sd"]=statistics.stdev(vals) if len(vals)>1 else 0.0
        cr["logical_messages_total"]=sum(int(r["logical_messages"]) for r in rr)
        cr["physical_publications_total"]=sum(int(r["physical_publications"]) for r in rr)
        cr["extra_publications_total"]=sum(int(r["extra_publications"]) for r in rr)
        cr["subscriber_duplicates_total"]=sum(int(r["subscriber_duplicates"]) for r in rr)
        cr["decrypt_failures_total"]=sum(int(r["decrypt_failures"]) for r in rr)
        condrows.append(cr)

    cfields=list(condrows[0])
    with (root/"condition_summary.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cfields); w.writeheader(); w.writerows(condrows)

    lines=["B-8 E1 v1.3.7 replication summary"]
    for r in condrows:
        lines += [
            f"{r['condition']}: runs={r['runs']}",
            f"  logical_total={r['logical_messages_total']} physical_total={r['physical_publications_total']} extra_total={r['extra_publications_total']}",
            f"  subscriber_duplicates_total={r['subscriber_duplicates_total']} decrypt_failures_total={r['decrypt_failures_total']}",
            f"  latency_mean_ms={r['latency_mean_ms_mean']:.6f} sd={r['latency_mean_ms_sd']:.6f}",
            f"  p95_mean_ms={r['latency_p95_ms_mean']:.6f} p99_mean_ms={r['latency_p99_ms_mean']:.6f}",
            f"  payload_physical_mean_B={r['payload_per_physical_mean_bytes_mean']:.3f}",
            f"  payload_per_logical_B={r['payload_per_logical_bytes_mean']:.3f}",
            f"  extra_rate_pct={r['extra_rate_pct_mean']:.4f}",
        ]
    (root/"summary.txt").write_text("\n".join(lines)+"\n")
    print("\n".join(lines))
    print(f"run_summary={root/'run_summary.csv'}")
    print(f"condition_summary={root/'condition_summary.csv'}")

if __name__=="__main__":
    main()
