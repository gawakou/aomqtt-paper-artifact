#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import statistics
from datetime import datetime
from pathlib import Path

RUNS = [f"r{i:02d}" for i in range(1, 11)]
PUBS = range(1, 6)
SUBS = range(1, 6)

ELP = 6000                  # expected logical messages per publisher
EPP = 7000                  # expected physical publish rows per publisher
ELR = ELP * 5               # expected logical messages published per run = 30,000
EPR = EPP * 5               # expected physical publish rows per run = 35,000
ESR = ELR * 5               # expected unique subscriber observations per run = 150,000

T95 = 2.2621571627409915    # Student t, df=9, two-sided 95% CI


def die(s):
    raise SystemExit("ERROR: " + s)


def nid(s):
    return (s or "").replace(r"\:", ":")


def b(s):
    return str(s).strip().lower() in ("1", "true", "yes", "y")


def rf(p):
    if not p.is_file():
        die(f"missing file: {p}")
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pct(v, q):
    x = sorted(map(float, v))
    if not x:
        return float("nan")
    if len(x) == 1:
        return x[0]
    h = (len(x) - 1) * q
    a = math.floor(h)
    c = math.ceil(h)
    return x[a] if a == c else x[a] + (h - a) * (x[c] - x[a])


def isoepoch(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


def stats(name, v):
    x = list(map(float, v))
    if len(x) != 10:
        die(f"{name}: expected 10 values, got {len(x)}")
    m = statistics.fmean(x)
    sd = statistics.stdev(x)
    h = T95 * sd / math.sqrt(10)
    return dict(
        metric=name,
        n=10,
        mean=m,
        sd=sd,
        median=statistics.median(x),
        min=min(x),
        max=max(x),
        ci95_low=m - h,
        ci95_high=m + h,
    )


def wcsv(p, rows):
    if not rows:
        die(f"no rows for output: {p}")
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def pubsum(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    pats = {
        "total": r"total MQTT messages:\s*(\d+)",
        "success": r"success:\s*(\d+)",
        "failed": r"failed:\s*(\d+)",
        "avg": r"avg_complete_ms:\s*([0-9.]+)",
        "p95": r"p95_complete_ms:\s*([0-9.]+)",
        "reconn": r"reconnect_count:\s*(\d+)",
        "miss": r"pacing_deadline_miss:\s*(\d+)",
        "late": r"pacing_late_max_ms:\s*([0-9.]+)",
    }
    o = {}
    for k, pat in pats.items():
        m = re.findall(pat, t)
        if not m:
            die(f"{p}: missing {k}")
        o[k] = float(m[-1]) if "." in m[-1] else int(m[-1])
    return o


def rsrc(p, start, end):
    # Frozen MC2/MC3-compatible resource-window definition:
    # logical_start < sample_timestamp <= logical_end + 1.0 s
    z = []
    for r in rf(p):
        t = isoepoch(r["timestamp_utc"])
        if start < t <= end + 1.0:
            z.append(r)

    if not z:
        die(f"no logical-window resource samples: {p}")

    cpu = [float(r["proc_cpu_pct_one_core"]) for r in z]
    rss = [float(r["proc_rss_kib"]) for r in z]

    return dict(
        resource_samples=len(z),
        cpu_mean=statistics.fmean(cpu),
        cpu_p95=pct(cpu, .95),
        cpu_max=max(cpu),
        rss_mean=statistics.fmean(rss),
        rss_max=max(rss),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "aomqtt-experiment-archives",
    )
    ap.add_argument("--out", type=Path)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    root = a.root.expanduser().resolve()
    out = (
        a.out.expanduser().resolve()
        if a.out
        else root / "e3-mc4-aomqtt-r01-r10-analysis"
    )

    if out.exists():
        if not a.force:
            die(f"output exists: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    PR = []   # per-run
    PP = []   # per-publisher
    PS = []   # per-subscriber

    G = dict(
        published_logical=0,
        expected_observations=0,
        got_observations=0,
        decrypt_failures=0,
        missing_observations=0,
        unexpected_observations=0,
        pacing_misses=0,
        physical_rows=0,
        subscriber_raw_rows=0,
        subscriber_duplicates=0,
        redundant_publish_rows=0,
        redundant_observation_opportunities=0,
        unobserved_redundant_observations=0,
    )

    for rep in RUNS:
        rid = f"e3-mc4-aomqtt-fr-{rep}"
        d = root / rid
        if not d.is_dir():
            die(f"missing run: {d}")

        union = set()
        P = []
        allcomp = []
        first = []
        last = []

        phys = succ = enc = plain = pace = 0

        # ------------------------------------------------------------
        # Publishers
        # ------------------------------------------------------------
        for p in PUBS:
            pd = d / f"publisher-{p}"
            rows = rf(pd / f"publisher-{p}-metrics.csv")

            uniq = {}
            for r in rows:
                m = nid(r["message_id"])
                if m not in uniq or float(r["timestamp"]) < float(uniq[m]["timestamp"]):
                    uniq[m] = r

            ok = [r for r in rows if b(r["success"])]

            if len(rows) != EPP or len(uniq) != ELP or len(ok) != EPP:
                die(f"{rid} publisher-{p}: count validation failed")

            sm = pubsum(pd / f"publisher-{p}.log")
            if (
                sm["total"] != EPP
                or sm["success"] != EPP
                or sm["failed"] != 0
                or sm["miss"] != 0
            ):
                die(f"{rid} publisher-{p}: summary validation failed")

            ts = sorted(float(r["timestamp"]) for r in uniq.values())
            rate = (len(ts) - 1) / (ts[-1] - ts[0])

            rs = rsrc(
                pd / f"publisher-{p}-proc-resource.csv",
                ts[0],
                ts[-1],
            )
            if rs["resource_samples"] < 50:
                die(f"{rid} publisher-{p}: too few resource samples")

            comp = [
                float(r["publish_complete_ms"])
                for r in rows
                if r["publish_complete_ms"].strip()
            ]
            er = sum(int(r["payload_encrypted_bytes"]) for r in rows)
            pl = sum(int(r["payload_plain_bytes"]) for r in uniq.values())

            info = dict(
                run=rep,
                run_id=rid,
                publisher=p,
                client_id=f"e3-mc4-pub{p}",
                physical_rows=len(rows),
                physical_success=len(ok),
                unique_logical=len(uniq),
                overlap_duplicate_rows=sum(b(r["overlap_duplicate"]) for r in rows),
                effective_rate_msg_s=rate,
                first_metric_timestamp=ts[0],
                last_metric_timestamp=ts[-1],
                publish_complete_mean_ms=statistics.fmean(comp),
                publish_complete_p95_ms=pct(comp, .95),
                publish_complete_max_ms=max(comp),
                log_avg_complete_ms=sm["avg"],
                log_p95_complete_ms=sm["p95"],
                reconnect_count=sm["reconn"],
                pacing_deadline_miss=sm["miss"],
                pacing_late_max_ms=sm["late"],
                encrypted_payload_bytes=er,
                plain_logical_bytes=pl,
                encrypted_payload_bytes_per_logical=er / ELP,
                resource_samples=rs["resource_samples"],
                cpu_mean_one_core_pct=rs["cpu_mean"],
                cpu_p95_one_core_pct=rs["cpu_p95"],
                cpu_max_one_core_pct=rs["cpu_max"],
                rss_mean_kib=rs["rss_mean"],
                rss_max_kib=rs["rss_max"],
            )

            P.append(info)
            union |= set(uniq)

            phys += len(rows)
            succ += len(ok)
            enc += er
            plain += pl
            pace += sm["miss"]

            allcomp += comp
            first.append(ts[0])
            last.append(ts[-1])

        if len(union) != ELR or phys != EPR or succ != EPR:
            die(f"{rid}: publisher union/physical validation failed")

        start = min(first)
        end = max(last)
        spread = (max(first) - min(first)) * 1000.0
        rate_total = sum(float(x["effective_rate_msg_s"]) for x in P)

        brs = rsrc(
            d / "broker-vm" / "broker-proc-resource.csv",
            start,
            end,
        )
        if brs["resource_samples"] < 50:
            die(f"{rid}: too few broker resource samples")

        # ------------------------------------------------------------
        # Subscribers
        # Each subscriber must independently observe all 30,000 logical
        # messages. Across 5 subscribers this is 150,000 unique
        # observations per run; it is NOT 150,000 published messages.
        # ------------------------------------------------------------
        all_lat = []
        all_sub_cpu_mean = []
        all_sub_rss_mean = []
        total_raw = 0
        total_dups = 0
        total_decrypt_fail = 0
        total_missing = 0
        total_unexpected = 0
        total_unique_obs = 0

        # publisher -> all successful subscriber rows across 5 subscribers
        by_pub = {p: [] for p in PUBS}

        pred_per_subscriber = phys - len(union)
        redundant_observation_opportunities = pred_per_subscriber * len(SUBS)

        for s in SUBS:
            sd = d / f"subscriber-{s}"
            sr = rf(sd / f"subscriber-{s}-delivery.csv")

            dok = [r for r in sr if b(r["decrypt_success"])]
            dfail = len(sr) - len(dok)

            uq = [r for r in dok if not b(r["duplicate"])]
            du = [r for r in dok if b(r["duplicate"])]

            got = {nid(r["message_id"]) for r in uq}
            if len(got) != len(uq):
                die(f"{rid} subscriber-{s}: repeated non-duplicate IDs")

            missing = union - got
            unexpected = got - union

            if dfail or missing or unexpected or len(got) != ELR:
                die(f"{rid} subscriber-{s}: delivery validation failed")

            lat = [float(r["delivery_latency_ms"]) for r in uq]

            srs = rsrc(
                sd / f"subscriber-{s}-proc-resource.csv",
                start,
                end,
            )
            if srs["resource_samples"] < 50:
                die(f"{rid} subscriber-{s}: too few resource samples")

            # Attribute each successful row to one of the five publishers.
            by_local = {p: [] for p in PUBS}
            for r in dok:
                m = nid(r["message_id"])
                hit = False
                for p in PUBS:
                    if m.startswith(f"e3-mc4-pub{p}:"):
                        by_local[p].append(r)
                        by_pub[p].append(r)
                        hit = True
                        break
                if not hit:
                    die(f"{rid} subscriber-{s}: cannot attribute {m}")

            # Every subscriber must have 6,000 unique messages from
            # every publisher.
            for p in PUBS:
                rr = by_local[p]
                u = [r for r in rr if not b(r["duplicate"])]
                ids = {nid(r["message_id"]) for r in u}
                if len(ids) != ELP or len(ids) != len(u):
                    die(
                        f"{rid} subscriber-{s} publisher-{p}: "
                        "attribution validation failed"
                    )

            obs = len(du)
            unobs = pred_per_subscriber - obs
            if unobs < 0:
                die(
                    f"{rid} subscriber-{s}: duplicates exceed "
                    "published redundant copies"
                )

            PS.append(
                dict(
                    run=rep,
                    run_id=rid,
                    subscriber=s,
                    client_id=f"e3-mc4-sub{s}",
                    raw_rows=len(sr),
                    decrypt_success_rows=len(dok),
                    decrypt_failures=dfail,
                    unique_logical_observations=len(got),
                    duplicates=obs,
                    missing_logical=len(missing),
                    unexpected_logical=len(unexpected),
                    redundant_observation_opportunities=pred_per_subscriber,
                    unobserved_redundant_observations=unobs,
                    redundant_copy_observation_ratio=obs / pred_per_subscriber,
                    delivery_latency_mean_ms=statistics.fmean(lat),
                    delivery_latency_p95_ms=pct(lat, .95),
                    delivery_latency_p99_ms=pct(lat, .99),
                    delivery_latency_max_ms=max(lat),
                    resource_samples=srs["resource_samples"],
                    cpu_mean_one_core_pct=srs["cpu_mean"],
                    cpu_p95_one_core_pct=srs["cpu_p95"],
                    cpu_max_one_core_pct=srs["cpu_max"],
                    rss_mean_kib=srs["rss_mean"],
                    rss_max_kib=srs["rss_max"],
                )
            )

            total_raw += len(sr)
            total_dups += obs
            total_decrypt_fail += dfail
            total_missing += len(missing)
            total_unexpected += len(unexpected)
            total_unique_obs += len(got)
            all_lat += lat
            all_sub_cpu_mean.append(srs["cpu_mean"])
            all_sub_rss_mean.append(srs["rss_mean"])

        if total_unique_obs != ESR:
            die(
                f"{rid}: expected {ESR} unique subscriber observations, "
                f"got {total_unique_obs}"
            )

        unobserved_redundant_observations = (
            redundant_observation_opportunities - total_dups
        )
        if unobserved_redundant_observations < 0:
            die(f"{rid}: aggregate duplicate count exceeds opportunities")

        # ------------------------------------------------------------
        # Add subscriber-observation metrics to per-publisher rows.
        # Across five subscribers each publisher has 30,000 unique
        # observations (6,000 x 5).
        # ------------------------------------------------------------
        for info in P:
            p = info["publisher"]
            rr = by_pub[p]
            u = [r for r in rr if not b(r["duplicate"])]
            dd = [r for r in rr if b(r["duplicate"])]

            unique_obs = len(u)
            lp = [float(r["delivery_latency_ms"]) for r in u]

            expected_pub_obs = ELP * len(SUBS)
            if unique_obs != expected_pub_obs:
                die(
                    f"{rid} publisher-{p}: expected {expected_pub_obs} "
                    f"unique subscriber observations, got {unique_obs}"
                )

            pr = int(info["physical_rows"]) - int(info["unique_logical"])
            opportunities = pr * len(SUBS)

            info.update(
                subscriber_unique_observations=unique_obs,
                subscriber_observed_duplicates=len(dd),
                subscriber_redundant_observation_opportunities=opportunities,
                subscriber_unobserved_redundant_observations=opportunities - len(dd),
                subscriber_redundant_observation_ratio=len(dd) / opportunities,
                delivery_latency_mean_ms=statistics.fmean(lp),
                delivery_latency_p95_ms=pct(lp, .95),
                delivery_latency_p99_ms=pct(lp, .99),
                delivery_latency_max_ms=max(lp),
            )
            PP.append(info)

        pcpu = sum(float(x["cpu_mean_one_core_pct"]) for x in P)
        prss = sum(float(x["rss_mean_kib"]) for x in P)
        scpu = sum(all_sub_cpu_mean)
        srss = sum(all_sub_rss_mean)

        PR.append(
            dict(
                run=rep,
                run_id=rid,
                publishers=5,
                subscribers=5,
                published_logical_messages=ELR,
                expected_unique_subscriber_observations=ESR,
                delivered_unique_subscriber_observations=total_unique_obs,
                subscriber_unique_observation_rate=total_unique_obs / ESR,
                decrypt_failures=total_decrypt_fail,
                missing_logical_observations=total_missing,
                unexpected_logical_observations=total_unexpected,
                publisher_physical_rows=phys,
                publisher_physical_success=succ,
                publisher_redundant_rows=phys - len(union),
                subscriber_raw_rows=total_raw,
                subscriber_duplicates=total_dups,
                redundant_observation_opportunities=redundant_observation_opportunities,
                unobserved_redundant_observations=unobserved_redundant_observations,
                redundant_copy_observation_ratio=(
                    total_dups / redundant_observation_opportunities
                ),
                pacing_deadline_misses=pace,
                effective_rate_total_msg_s=rate_total,
                effective_rate_mean_per_publisher_msg_s=rate_total / 5,
                publisher_first_metric_timestamp_spread_ms=spread,
                publisher_complete_mean_ms=statistics.fmean(allcomp),
                publisher_complete_p95_ms=pct(allcomp, .95),
                publisher_complete_max_ms=max(allcomp),
                latency_mean_ms=statistics.fmean(all_lat),
                latency_p95_ms=pct(all_lat, .95),
                latency_p99_ms=pct(all_lat, .99),
                latency_max_ms=max(all_lat),
                encrypted_payload_bytes_total=enc,
                plain_logical_bytes_total=plain,
                encrypted_payload_bytes_per_logical=enc / ELR,
                broker_resource_samples=brs["resource_samples"],
                broker_cpu_mean_one_core_pct=brs["cpu_mean"],
                broker_cpu_p95_one_core_pct=brs["cpu_p95"],
                broker_cpu_max_one_core_pct=brs["cpu_max"],
                broker_rss_mean_kib=brs["rss_mean"],
                broker_rss_max_kib=brs["rss_max"],
                publisher_cpu_sum_mean_one_core_pct=pcpu,
                publisher_cpu_mean_per_client_one_core_pct=pcpu / 5,
                publisher_rss_sum_mean_kib=prss,
                publisher_rss_mean_per_client_kib=prss / 5,
                subscriber_cpu_sum_mean_one_core_pct=scpu,
                subscriber_cpu_mean_per_client_one_core_pct=scpu / 5,
                subscriber_rss_sum_mean_kib=srss,
                subscriber_rss_mean_per_client_kib=srss / 5,
                logical_window_start_epoch=start,
                logical_window_end_epoch=end,
                logical_window_duration_s=end - start,
            )
        )

        G["published_logical"] += ELR
        G["expected_observations"] += ESR
        G["got_observations"] += total_unique_obs
        G["decrypt_failures"] += total_decrypt_fail
        G["missing_observations"] += total_missing
        G["unexpected_observations"] += total_unexpected
        G["pacing_misses"] += pace
        G["physical_rows"] += phys
        G["subscriber_raw_rows"] += total_raw
        G["subscriber_duplicates"] += total_dups
        G["redundant_publish_rows"] += phys - len(union)
        G["redundant_observation_opportunities"] += redundant_observation_opportunities
        G["unobserved_redundant_observations"] += unobserved_redundant_observations

    mets = [
        "effective_rate_total_msg_s",
        "effective_rate_mean_per_publisher_msg_s",
        "publisher_first_metric_timestamp_spread_ms",
        "publisher_complete_mean_ms",
        "publisher_complete_p95_ms",
        "latency_mean_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "latency_max_ms",
        "subscriber_duplicates",
        "redundant_copy_observation_ratio",
        "encrypted_payload_bytes_per_logical",
        "broker_cpu_mean_one_core_pct",
        "broker_cpu_p95_one_core_pct",
        "broker_cpu_max_one_core_pct",
        "broker_rss_mean_kib",
        "broker_rss_max_kib",
        "publisher_cpu_sum_mean_one_core_pct",
        "publisher_cpu_mean_per_client_one_core_pct",
        "publisher_rss_sum_mean_kib",
        "publisher_rss_mean_per_client_kib",
        "subscriber_cpu_sum_mean_one_core_pct",
        "subscriber_cpu_mean_per_client_one_core_pct",
        "subscriber_rss_sum_mean_kib",
        "subscriber_rss_mean_per_client_kib",
    ]

    ST = [stats(m, [r[m] for r in PR]) for m in mets]

    wcsv(out / "per-run.csv", PR)
    wcsv(out / "per-publisher.csv", PP)
    wcsv(out / "per-subscriber.csv", PS)
    wcsv(out / "summary-statistics.csv", ST)

    ratio = G["subscriber_duplicates"] / G["redundant_observation_opportunities"]

    L = [
        "E3-MC4 Full AOMQTT r01-r10 aggregate summary",
        "",
        "runs: 10",
        "topology: 5 publishers x 5 subscribers",
        f"published logical messages: {G['published_logical']}",
        (
            "unique subscriber observations: "
            f"{G['got_observations']}/{G['expected_observations']}"
        ),
        (
            "subscriber unique observation rate: "
            f"{G['got_observations']/G['expected_observations']:.9f}"
        ),
        f"decrypt failures: {G['decrypt_failures']}",
        f"missing logical observations: {G['missing_observations']}",
        f"unexpected logical observations: {G['unexpected_observations']}",
        f"total pacing deadline misses: {G['pacing_misses']}",
        f"publisher physical MQTT rows: {G['physical_rows']}",
        f"publisher redundant rows: {G['redundant_publish_rows']}",
        f"subscriber raw rows: {G['subscriber_raw_rows']}",
        f"observed subscriber duplicates: {G['subscriber_duplicates']}",
        (
            "redundant observation opportunities: "
            f"{G['redundant_observation_opportunities']}"
        ),
        (
            "unobserved redundant observations: "
            f"{G['unobserved_redundant_observations']}"
        ),
        f"redundant copy observation ratio: {ratio:.9f}",
        "",
        "Run-level statistics (n=10; 95% CI uses Student t, df=9)",
    ]

    for s in ST:
        L.append(
            f"{s['metric']}: mean={s['mean']:.9f}, "
            f"sd={s['sd']:.9f}, median={s['median']:.9f}, "
            f"min={s['min']:.9f}, max={s['max']:.9f}, "
            f"95%CI=[{s['ci95_low']:.9f}, {s['ci95_high']:.9f}]"
        )

    L += [
        "",
        "Method notes",
        (
            "- Subscriber latency uses decrypt-success, duplicate=False "
            "rows only (one observation per logical message per subscriber)."
        ),
        (
            "- Across five subscribers, 150,000 unique observations per "
            "run correspond to 30,000 published logical messages x 5 "
            "subscribers; they are not 150,000 published messages."
        ),
        (
            "- Resource window uses the frozen MC2-compatible legacy rule: "
            "logical_start < sample_timestamp <= logical_end + 1.0 s."
        ),
        (
            "- publisher_complete_* is based on physical publish_complete_ms "
            "rows and is not an end-to-end security-processing metric."
        ),
        (
            "- encrypted_payload_bytes_* is AOMQTT encrypted application "
            "payload size, not total MQTT/TCP/IP traffic."
        ),
        (
            "- Redundant observation opportunities equal published redundant "
            "rows x number of subscribers. Unobserved redundant copies are "
            "not logical-message loss when every subscriber received all "
            "30,000 logical messages."
        ),
        (
            "- Run-level subscriber CPU/RSS totals are sums of the five "
            "per-subscriber mean values over the frozen logical resource "
            "window; per-client values divide those sums by five."
        ),
    ]

    text = "\n".join(L) + "\n"
    (out / "summary.txt").write_text(text, encoding="utf-8")

    print(text, end="")
    print(f"analysis_dir: {out}")
    print("ANALYSIS=PASS")


if __name__ == "__main__":
    main()
