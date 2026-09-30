# E5 closed-loop evaluation provenance

## Scope

E5 is a single-step functional closed-loop demonstration of the implemented
observation-driven path in AOMQTT v1.3.7. It evaluates the sequence

raw client observations → evaluation adapter → existing v1.3.7 metric
aggregation → existing rule-based decision → generated signed runtime policy →
MQTT control topic → guarded client acceptance/application → post-observation.

It is not a stability, convergence, or optimal-control experiment.

## Frozen implementation

- Paper-artifact Git HEAD before this freeze: `d6efc44ac2916e544b3f9dc3631eb1c6937ebd08`
- AOMQTT software snapshot: `software/aomqtt-v1.3.7/`
- E5 runner SHA-256: `c5302b662de391eeba2826a0eb8909c7578a3e040f74aa70283bb721eadcf702`
- E5 observation adapter SHA-256: `f9a1f6113fc244cf695d390a675f32e55c95fcef59c09235c6a30ec3e3117369`
- E5 initial policy SHA-256: `ed9ee48d023c8c0ffbceb3e5b10677ab4a4369494fff19bcd7135fcd7be7be0f`
- Python: `Python 3.12.3`

The evaluation adapter leaves the v1.3.7 software snapshot unchanged. It:
1. exposes numeric `logical_seq` as `seq` for the existing auto-controller
   aggregator;
2. distinguishes delivery loss from publisher-side local PUBLISH failures by
   using successfully published logical messages as the delivery-loss
   denominator and writes explicit `loss_rate`/`duplicate_rate` fields that
   the existing v1.3.7 aggregator already consumes; and
3. converts the raw cumulative `reconnect_count` into per-row increments only
   in the controller-input snapshot so the existing aggregator's sum equals the
   actual reconnect count.

Raw CSV files are preserved unchanged.

## Formal configuration

- Broker: `172.16.10.200:1883`
- Publisher/subscriber: separate processes on publisher-1
- QoS: 1
- token mode: whole
- fixed padding: 512 B
- rotation interval: 30 s
- initial overlap: 5 s
- duplicate-rate threshold: 0.10
- controller action: `decrease_overlap`
- overlap step: 2 s
- generated overlap: 3 s
- pre-observation: 90 s
- settle: 5 s
- post-observation: 90 s

## Formal runs

- `e5-20260930T070708Z`
- `e5-20260930T071422Z`
- `e5-20260930T071740Z`
- `e5-20260930T072057Z`
- `e5-20260930T072414Z`

All five runs passed every predefined formal gate:
- zero publisher reconnects and zero local publisher failures in pre/post phases;
- pre duplicate rate > 10%;
- existing controller decision = `decrease_overlap`;
- generated overlap = 3 s;
- Publisher and Subscriber ACK = accepted and Status = applied;
- generated policy observed in both clients post-application;
- post duplicate rate lower than pre and <= 10%;
- post delivery loss = 0%; and
- post decryption success = 100%.

## Aggregate result

Across the five formal runs:
- duplicate rate decreased from **12.773% ± 1.381%** to
  **7.386% ± 1.556%**;
- the absolute reduction was **5.387 ± 0.175 percentage points**;
- the mean relative reduction was **42.670% ± 5.757%**;
- physical MQTT rows per successfully published logical message decreased from
  **1.166667** to **1.100000**;
- delivery loss remained **0%** in every pre/post phase; and
- decryption success remained **100%** in every pre/post phase.

## Pilot / aborted runs

Three pre-formal runs are retained as provenance but are not part of the five
formal runs.

- `e5-20260930T062130Z`: the controller reached signed policy publication and
  both clients reported accepted/applied, but the initial harness failed while
  parsing mixed stdout and did not generate a final closed-loop summary.
- `e5-20260930T062834Z`: pilot step 5 s → 0 s; overlap-induced duplicates were
  eliminated, but three post-window losses occurred, each about 0.438 s after
  consecutive epoch boundaries.
- `e5-20260930T063929Z`: validity-aborted run with one local publisher PUBLISH
  failure (`rc=4`) and one actual reconnect. Corrected delivery-loss analysis
  showed zero loss among successfully published logical messages.

These pilot observations motivated the final formal validity gates and the
2-second decrement used in the frozen formal design.
