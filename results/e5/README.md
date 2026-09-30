# E5 closed-loop evaluation runs

E5 is a single-step functional closed-loop evaluation of the implemented
observation-driven AOMQTT v1.3.7 policy-control path.

## Formal runs

The following five runs form the frozen formal data set:

- `e5-20260930T070708Z`
- `e5-20260930T071422Z`
- `e5-20260930T071740Z`
- `e5-20260930T072057Z`
- `e5-20260930T072414Z`

All five passed the predefined formal gates. The controller observed a
subscriber duplicate rate above 10% with a 5-s overlap, selected
`decrease_overlap`, generated and distributed a signed policy with a 3-s
overlap, and both Publisher and Subscriber reported accepted/applied. Across
the five runs, delivery loss remained 0% and decryption success remained 100%.

Frozen aggregate outputs:

- `results/analysis/e5-closed-loop/`
- `provenance/e5-provenance.md`

## Pilot / validity-aborted runs

The following runs are retained as provenance and are not part of the five
formal runs:

- `e5-20260930T062130Z` — pilot. The signed policy was published and both
  clients reported accepted/applied, but the initial harness stopped while
  parsing mixed controller stdout before writing a final summary.
- `e5-20260930T062834Z` — pilot. A 5-s to 0-s overlap change removed overlap
  duplicates but produced three post-window delivery losses, each occurring
  approximately 0.438 s after consecutive epoch boundaries.
- `e5-20260930T063929Z` — validity-aborted run. One local Publisher PUBLISH
  failure (`rc=4`) and one actual reconnect occurred. Corrected analysis showed
  zero delivery loss among successfully published logical messages.

The run directories remain in place so the raw observations, controller logs,
and development provenance remain inspectable.
