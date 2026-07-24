# Claude session — pybb blackboard attestation (dev branch)

Exported 2026-07-24. Topics: dev branch setup; live-target attestation and
removal of path_map; golden directory (capture/restore); vendoring the
temp-control-jvm HAMR example; provisioning partition + predicate;
protocol readiness; tier decomposition (l1a/l1b/l2); repair layer;
design walkthroughs of predicates, partitions, routes, and dispatch.

---

## User

I'd like to make some updates to the blackboard architecture and knowledge sources here:  https://github.com/ku-sldg/pybb .  Let's make a dev branch first.

## Assistant

I'll check whether the pybb repo is already cloned in your workspace first.

> `[Bash]` Check for existing pybb clone in workspace

> `[Bash]` Show pybb git status, branches, recent commits

> `[Bash]` Fetch origin and create dev branch from attestation-routes

> `[Bash]` Compare attestation-routes with updated origin/main

> `[Bash]` Diff dev against updated origin/main

> `[Bash]` Point dev at origin/main (identical tree, no local commits)

The `dev` branch is ready. Summary of what I did:

- Your local clone at [pybb](pybb) was on `attestation-routes`, but fetching revealed that branch was merged to `main` as PR #4, along with PR #5 (`anakha/c`).
- Since the file trees were identical, I created `dev` pointing at `origin/main` (`dd250fa`), so it cleanly descends from the up-to-date mainline including all the routed-blackboard and outcome-routed dispatch work.

What updates would you like to make to the blackboard architecture and knowledge sources? Once you describe them, I'll sketch a plan for your approval before editing.

## User

First let's review what the existing temp-control knowledge sources are and what they do.

## Assistant

> `[Bash]` List Python files and top-level layout of pybb

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Bash]` Find temp-control references in pybb

> `[Bash]` Show protocol fixture directories and metadata

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/ks_examples.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/knowledge_source.py

Here's a review of the temp-control knowledge-source setup on the current `dev` branch (which now includes all the merged `attestation-routes` work).

## The short version

There is exactly **one knowledge-source class** in the attestation layer — `TierKS` in [knowledge_sources.py:122](pybb/pybb/attestation/knowledge_sources.py:122) — and the temp-control demo instantiates it twice (three times with `--validate`). The KSs don't run protocols or parse evidence; the **predicate** does the actual attesting. A `TierKS` is just a "tier rung": when dispatched, it re-points the entry's measurement at its own protocol so the controller's next evaluation cycle attests at that tier.

## How the pieces divide the work

- **Predicate** (built by `make_attestation_predicate`, [knowledge_sources.py:79](pybb/pybb/attestation/knowledge_sources.py:79)) — runs the protocol named in the entry's measurement via `CvmSubprocessClient`, appraises the response into a `Verdict` (truthy iff every component passed). Memoized on the measurement so per-cycle re-evaluation doesn't re-run minutes-long protocols.
- **Measurement** — a request descriptor `{"protocol", "path_map"?, "nonce"}`. Changing it is how a KS "acts."
- **TierKS.execute** — rewrites the measurement to `{"protocol": <its protocol_id>, ...}`, sets `result=None`, and lets the controller re-evaluate. Its one knob is `carry_path_map`: integrity tiers keep the path re-rooting (attest the tampered copy), while the semantic tier drops it because Sireum has to run against the real, runnable project.

## The temp-control tiers (from [gumbo_attestation.py](pybb/examples/gumbo_attestation.py))

The single entry `"gumbo"` starts at `gumbo_l1`, and the route encodes the decision tree:

```python
controller.route("gumbo",
    on_pass=[TierKS(protocol_id="gumbo_validation", carry_path_map=False)],  # only with --validate
    on_fail=[TierKS(protocol_id="gumbo_l2")])
```

| Tier | What it measures | Cost | Role |
|---|---|---|---|
| `gumbo_l1` | Whole-file hashes of 4 "do not edit" artifacts: `TempControlSystem.aadl`, `TempSensor.aadl`, and the two GumboX oracle `.scala` files | ~1s | Fast integrity gate; the entry's starting tier |
| `gumbo_l2` | 28 fine-grained slices — 22 line-range reads of AADL GUMBO clauses and GumboX predicates, plus 6 BEGIN/END-marker-delimited component contract blocks | ~1s | `on_fail` rung: attributes an l1 failure to specific contracts (or clears the entry if the tamper fell outside measured content) |
| `gumbo_validation` | Live Sireum tooling: `proyek tipe` type-check, Logika verification of both GumboX modules, and randomized GumboX unit tests for TempControl and TempSensor | ~minutes | `on_pass` confirmation rung (opt-in via `--validate`): an l1 pass is provisional until semantics concur |

Either chosen tier's pass ends the episode in good standing; its failure exhausts the chain and the controller moves the entry to the **escalate segment**, carrying that tier's failing `Verdict` as the report plus the `ks_history` of attempts. `trust_summary` then narrates the outcome ("intact", "confirmed by validation", "clean at finer granularity", "passed but confirmation failed").

## What else exists

- [ks_examples.py](pybb/pybb/ks_examples.py) has the pre-attestation toy KSs (`NumberAdder`/`Subtractor`/`Nothinger`, plus component-scoped variants) — these actually *mutate* measurements toward a goal, i.e. they're repair-shaped, unlike `TierKS` which only re-targets tiers.
- Deliberately **not** on this branch (deferred, living on `attestation-integration`): the repair layer (`RepairKS`, `GoldenRestoreRepairer` — designed to slot in by lengthening the `on_fail` chain) and the isolette/rodeo material. Also worth knowing: provisioning of golden values is intentionally out of pybb's scope (owned by the cvm-mcp dashboard, as a trust boundary).

One structural observation for whatever updates you're planning: the current design is elegantly minimal — the "knowledge" in each knowledge source is just *which protocol to try next* — so anything that needs richer behavior (repair, nonce-bumping re-attestation, multi-entry coordination, new measurement kinds) will mean either new KS classes alongside `TierKS` or generalizing what a measurement rewrite can express.

What updates did you have in mind?

## User

I'd like to see about getting rid of the path_map field (And also carry_path_map).  Let's review what they do and why they are there.

## Assistant

Let me trace every use of `path_map` and `carry_path_map` through the codebase.

> `[Bash]` Find all path_map and rewrite_filepaths usages

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/client.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

Here's the full picture of `path_map` / `carry_path_map` on the current code.

## What `path_map` does

It's a mapping of path prefixes, e.g. `{"/Users/.../temp-control-jvm": "/tmp/pybb_tamper_x/temp-control-jvm"}`, that re-roots a protocol run onto a copied file tree. It threads through four places:

1. **The measurement** — `attestation_request()` puts it in the entry's descriptor: `{"protocol", "path_map"?, "nonce"}` ([knowledge_sources.py:48](pybb/pybb/attestation/knowledge_sources.py:48)).
2. **Request assembly** — `ProtocolDir.build_request(path_map)` calls `rewrite_filepaths` on the fully-assembled CVM request, rewriting every string (in term asp_args and session alike) whose prefix matches ([client.py:113](pybb/pybb/attestation/client.py:113)). So a protocol *provisioned* against the real `temp-control-jvm` tree *measures* the copy — while still appraising against the original golden values.
3. **Appraisal alignment** — after the run, `_attest` applies the same rewrite to `protocol.target_records()` so appraisal results (which carry rewritten filepaths) can be matched back to stable target ids ([knowledge_sources.py:111](pybb/pybb/attestation/knowledge_sources.py:111)).
4. **The client interface** — `AttestationClient.run_protocol(protocol, path_map=None)` carries it as a transport parameter ([client.py:134](pybb/pybb/attestation/client.py:134)).

## Why it's there

One reason: **safe tampering**. The fail path (l1 → l2 → escalate) can only be exercised by corrupting a watched file, but the provisioned originals must never be modified — tampering the real tree would require re-provisioning golden values, which is deliberately out of pybb's scope (owned by the cvm-mcp dashboard, as a trust boundary). So the `--tamper` demo and the CVM integration tests copy the watched files to a temp tree, corrupt the copy, and re-root the run onto it. The integration tests use it even for *clean* runs, so tests never touch the real tree at all.

## Why `carry_path_map` exists

Once `path_map` lives in the measurement, tier hops have to decide whether to forward it. `TierKS` defaults to carrying it (l2 attribution must measure the *same tampered copy* that failed l1 — that's what `test_path_map_carried_on_fail_dropped_on_pass` pins down). But the validation tier sets `carry_path_map=False` for two reasons: the copy holds only the ~10 watched files, not a runnable Sireum project, and semantically the confirmation tier is *supposed* to check the real project. So `carry_path_map` is a patch on top of a patch — a per-rung knob to undo the forwarding of a field that only exists for test hygiene.

## Assessment: can they go away?

Yes, and cleanly. The core smell is that **re-rooting is a property of demo/test setup, but it's currently expressed per-request**, which forces it into the measurement descriptor, the KS class, the client ABC, and appraisal alignment — four pieces of core architecture carrying test plumbing.

The natural fix: make re-rooting a **load-time property of the `ProtocolDir`** instead. Something like `ProtocolDir.load(dir, path_map=...)` (or a `.rerooted(path_map)` method) that rewrites `term`/`asp_args`/`session`/`prebuilt_request` once at construction. Then:

- `attestation_request` shrinks to `{"protocol", "nonce"}` — the measurement is purely "which trust question, which freshness".
- `run_protocol(protocol)` loses the parameter; the client ABC gets simpler.
- The `target_records()` realignment in `_attest` disappears — records are automatically consistent because the rewrite happened before both.
- `TierKS.carry_path_map` disappears entirely. The l2-measures-the-copy / validation-measures-the-real-project asymmetry moves to where it naturally belongs: the tamper demo loads `gumbo_l1`/`gumbo_l2` re-rooted and `gumbo_validation` un-re-rooted when building the `protocols` dict. Tiers just name protocols; what tree a protocol measures is baked into the protocol.
- `rewrite_filepaths` itself stays in `copland.py` (now called only at load time), and the memoization key still works — `protocol` + `nonce` distinguishes everything that matters.

The cost is confined to demo/test code: `make_tampered_copy` in the example, the `_run(path_map)` helper in `test_integration_cvm.py`, the mock-client tests in `test_knowledge_sources.py` (the carried-on-fail/dropped-on-pass test becomes moot and gets deleted), one copland test, and the README's architecture table.

Want me to draw up the concrete implementation plan along these lines?

## User

I'd like to instead simply keep around a clean copy of the target files before any attestation and repair.  The attestation protocols themselves should operate on live targets.  Only during repair or new runs of the workflow should the live targets be reverted to clean copies.  For now, let's add a capability to copy the target files (file tree) before doing the L1 protocol, and decide later what to do with the copies.  Does this get rid of the need for path_map?

## Assistant

Yes — this model eliminates `path_map` entirely, and it's arguably truer to what attestation should mean. Here's the reasoning:

## Why it gets rid of `path_map`

`path_map` exists for exactly one purpose: letting runs (tampered *and* clean) measure a copy so the live tree stays pristine. Your model inverts the direction of the copy: instead of *attesting the copy and protecting the original*, you *snapshot the original and attest live*. Every use dissolves:

- **Request re-rooting** (`build_request`) — gone; protocols measure the live paths they were provisioned against.
- **Appraisal record realignment** in `_attest` — gone; evidence filepaths match `target_records()` directly.
- **`path_map` in the measurement descriptor** — gone; it shrinks to `{"protocol", "nonce"}`.
- **`carry_path_map`** — gone, and this one dies for a deeper reason: the l2/validation asymmetry (integrity tiers measure the copy, validation runs the real project) only existed *because* of the copy. When every tier measures the live tree, there's no asymmetry left to configure.

One consequence to accept: the `--tamper` demo and the tampered integration test currently get their safety from isolation (corrupt the copy, originals untouched). Under the new model they must tamper the **live** tree, and safety comes from snapshot-before / restore-after instead. That's not a downside — it's precisely the repair workflow you're describing, exercised honestly — but the restore path needs to be robust (restore in a `finally`, so an aborted run can't leave the provisioned tree tampered).

## Proposed plan for this step

Scope for now, per your framing — add the snapshot capability, leave `path_map` removal for the next step:

1. **New module `pybb/attestation/snapshot.py`**:
   - `watched_files(protocols) -> set[Path]` — collect every `filepath` from the protocols' `asp_args` (this logic already exists in triplicate: `make_tampered_copy`, `test_integration_cvm._watched_files`; consolidate it here).
   - `TargetSnapshot.capture(protocols, dest=None) -> TargetSnapshot` — copy the watched file tree (preserving relative layout, `copy2` for metadata) into `dest` or a temp dir, recording the root mapping.
   - `TargetSnapshot.restore()` — copy the files back over the live targets. Written now, wired to nothing yet — it's the hook the future repair KS / new-run revert will call.
2. **Export** from `pybb.attestation.__init__`.
3. **Integrate capture into the workflow**: in `examples/gumbo_attestation.py`, capture the snapshot before writing the l1 entry / running the controller, and print where it landed.
4. **Unit test** (`tests/test_snapshot.py`, no CVM needed): capture from a fixture-backed protocols dict into a tmp dir, verify tree layout and content; tamper a live file, `restore()`, verify reverted.

Not touched yet: `path_map`/`carry_path_map` and their tests stay as-is until we do the removal pass (where the tamper demo flips to tamper-live + restore).

Want me to proceed with this?

## User

Yes, proceed with the plan.

## Assistant

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

> `[Write]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/snapshot.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/snapshot.py

Now export it and integrate capture into the example:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/tests/conftest.py

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/test_snapshot.py

> `[Bash]` Run non-CVM unit tests

> `[Bash]` Run clean gumbo attestation example with snapshot capture

> `[Bash]` Run tampered example to confirm refactored make_tampered_copy still works

Done. The snapshot capability is in place on `dev`, and both example flows verify clean against the real CVM.

## What was added

- **[snapshot.py](pybb/pybb/attestation/snapshot.py)** — the new module:
  - `watched_files(protocols)` — collects every `filepath` from the protocols' `asp_args` (consolidates logic that previously lived in duplicate in the example and the integration test).
  - `TargetSnapshot.capture(protocols, dest=None)` — copies the watched live files into `dest` or a temp dir, mirroring their absolute paths under the snapshot root (so files from multiple target trees coexist without needing a common ancestor).
  - `TargetSnapshot.dirty()` — lists live targets that no longer match their clean copy (a deleted live file counts as dirty rather than crashing).
  - `TargetSnapshot.restore()` — reverts changed targets to their clean copies and returns what it reverted. Deliberately wired to nothing yet — it's the hook for the future repair KS / new-run revert, and keeping it out of the measurement path preserves the trust boundary (a failed appraisal can't overwrite its own evidence).
- **[gumbo_attestation.py:112](pybb/examples/gumbo_attestation.py:112)** — the example captures the snapshot before writing the L1 entry and prints where it landed; `make_tampered_copy` now reuses `watched_files`.
- **[test_snapshot.py](pybb/tests/test_snapshot.py)** — 5 unit tests (no CVM needed) covering filepath collection/dedup, tree mirroring, default temp root, and restore of both tampered and deleted targets.

## Verification

- `pytest -m "not cvm"`: **34 passed** (was 29; the 5 new snapshot tests all pass).
- Clean run: snapshot of 6 target files captured, `gumbo_l1` passes in 1 cycle.
- `--tamper` run: unchanged behavior — l1 fail → l2 attributes `tc_sys_aadl_305_308_targ` → escalate.

Nothing is committed yet. Next step when you're ready: the `path_map` removal pass — flip the tamper demo and integration tests to tamper the live tree and `restore()` in a `finally`, then strip `path_map` from the measurement, client, `TierKS` (`carry_path_map`), and the README.

## User

Why are files copied by filepath?  Why not as a whole directory/tree?

## Assistant

Deliberate choice, with the file *set* coming from the protocols themselves. The reasoning:

**1. The attested scope defines the snapshot scope.** The protocols' `asp_args` are the single authority on what attestation vouches for — those 6 filepaths are the only files with provisioned golden values. There is actually no "target tree" concept anywhere in the protocol format: `ProtocolDir` holds a flat set of absolute filepaths, and nothing declares a root. `temp-control-jvm` is just where those files happen to live. Copying by filepath means the snapshot is *derived* from the measurement definition rather than from a separately-maintained root path that could drift out of sync with it.

**2. Restore stays a precise instrument.** This matters more once `restore()` gets wired into repair. With file-scoped copies, "revert to clean" means: restore exactly the artifacts attestation measured and found violated. A whole-tree restore would clobber everything else under the root — a developer's in-progress edits to unattested source, build outputs, generated code — none of which the snapshot has any standing to revert, because attestation never measured them. For a real HAMR project the tree is also heavy (`.git`, `out/`, IDE state), so whole-tree capture would be slow and mostly dead weight; you'd immediately reach for an `ignore=` filter, and then you're back to curating a file set — just a worse-sourced one.

**3. No root assumption to break.** The watched files needn't share an ancestor: the validation protocol targets the project root itself, other protocols could watch files elsewhere (system configs, a second component's tree). Mirroring absolute paths under the snapshot root handles any mix; `copytree` would force a one-root assumption that the protocol format doesn't make.

**4. Whole-tree restore raises questions file-restore avoids.** Files *created* after the snapshot — does restore delete them? Symlinks, permissions on unmeasured dirs? File-scoped restore sidesteps all of it: each measured path either matches its clean copy or is put back.

The honest counterpoint: if the threat model were "tamper can hide in *unmeasured* files that influence the system," a whole-tree snapshot would restore a fully known state. But that's really an attestation-coverage question — the answer to unmeasured influence is measuring it (that's what the l2/validation tiers are for), not a blunter restore. If a protocol should vouch for an entire directory, the cleaner path is a directory-hash ASP whose `asp_args` names the dir — and then the snapshot would naturally widen with it.

That said, if you want repair to mean "return the whole project to a known state," I can add a tree-mode capture (explicit root + ignore filter) alongside the file-scoped one — just say the word.

## User

Restoring individual files according to the protocol is fine for now.  Let's move on.

## Assistant

Moving on to the `path_map` removal pass. The plan, concretely:

1. Strip `path_map` from the measurement (`attestation_request`), the predicate (`_attest`), `TierKS` (delete `carry_path_map`), and `build_request`/`run_protocol` in the client.
2. Delete `rewrite_filepaths` from `copland.py` — it becomes dead code.
3. Rework the `--tamper` demo: snapshot first, tamper the **live** file, restore in a `finally`.
4. Rework the CVM integration tests the same way (snapshot fixture with teardown restore); drop the now-moot carried/dropped `path_map` test; update the README.

Let me look at the remaining files I'll touch:

> `[Read]` /Users/adampetz/Claude_workspace/pybb/tests/test_knowledge_sources.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/tests/test_copland.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/copland.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_sireum.py

Now the edits. First `knowledge_sources.py`:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

Now `client.py`:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/client.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/client.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/client.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/client.py

Now remove `rewrite_filepaths` from `copland.py` and update its docstring reference:

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/copland.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/copland.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/copland.py

Now rework the example — tamper the live tree, restore in `finally`:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_copland.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_copland.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_copland.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_sireum.py

> `[Bash]` Check workflow script for stale path_map references

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/run_gumbo_workflow.sh

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/run_gumbo_workflow.sh

Now the attestation README:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Bash]` Verify no path_map references remain

> `[Bash]` Run non-CVM unit tests

> `[Bash]` Run CVM integration tests, then check temp-control-jvm tree is clean

> `[Bash]` Confirm tampered line was restored in live tree

Restored correctly. Now the example, both modes:

> `[Bash]` Run clean and tampered example, verify live tree restored

`path_map` and `carry_path_map` are fully removed, and everything verifies against the real CVM. Summary of the pass:

## Core changes

- **[knowledge_sources.py](pybb/pybb/attestation/knowledge_sources.py)** — the measurement descriptor is now just `{"protocol", "nonce"}`; `_attest` lost the record-realignment step; `TierKS` lost `carry_path_map` (the l2/validation asymmetry it encoded no longer exists — every tier measures the live tree).
- **[client.py](pybb/pybb/attestation/client.py)** — `build_request()` and `run_protocol()` no longer take `path_map`; the client ABC is now just "run this protocol".
- **[copland.py](pybb/pybb/attestation/copland.py)** — `rewrite_filepaths` deleted (dead code once nothing re-roots).

## Demo and tests flipped to tamper-live + restore

- **[gumbo_attestation.py](pybb/examples/gumbo_attestation.py)** — `make_tampered_copy` replaced by `tamper_live()`; the snapshot is captured *before* tampering, and `snapshot.restore()` runs in a `finally` so even a crashed run puts the tree back.
- **[test_integration_cvm.py](pybb/tests/test_integration_cvm.py)** — the `target_copy` fixture became a `live_snapshot` fixture (capture → yield → restore in teardown); the tampered test corrupts the live AADL file directly.
- **[test_knowledge_sources.py](pybb/tests/test_knowledge_sources.py)** — fake client simplified; the carried-on-fail/dropped-on-pass test deleted (moot).
- **[test_copland.py](pybb/tests/test_copland.py)** — `rewrite_filepaths` test deleted; the prebuilt-with-path_map test became a plain prebuilt-request-used-verbatim test.
- README and workflow script updated: new "Live targets and the clean snapshot" section replaces the `carry_path_map` asymmetry paragraph.

## Verification

- `pytest -m "not cvm"`: **32 passed**.
- CVM integration tests (real binary): **2 passed**, and the live tree came back clean — which matters more than usual, because it turns out **`temp-control-jvm` is not a git repo**, so the snapshot is genuinely the only restore mechanism.
- Example clean run: 1 cycle, intact. `--tamper` run: l1 fail → l2 attributes `tc_sys_aadl_305_308_targ` → escalate, then "Restored 1 live target(s) from the clean snapshot", and line 306 verified back to its clean content.

One design note: the predicate's memoization key is now `protocol` + `nonce` alone. Within a single workflow run that's correct, but any future flow that re-attests after a repair *must* bump the nonce to defeat the cache — which is exactly the role the nonce was designed for, and the repair KS will need to honor it.

Nothing committed yet. Given `temp-control-jvm` has no version control, if you'd like a belt-and-suspenders option later, the "decide later what to do with copies" step could include persisting snapshots somewhere durable instead of a temp dir.

## User

For now, let's create a separate directory for golden example files.  These will be what we provision from, and what we copy from upon restore.

## Assistant

Good move — this closes the trust-boundary gap in the current setup: capturing the "clean" snapshot at the start of every run would declare whatever state the tree happens to be in as known-good. A persistent golden directory makes "declare known-good" a deliberate, one-time act, and every restore sources from it. Here's my proposed plan:

1. **New top-level `golden/` directory in the pybb repo**, holding clean copies of the watched target files in the same absolute-path-mirror layout the snapshot already uses. In-repo means it's durable and versioned — which matters since `temp-control-jvm` itself has no git. Populated once, now, from the current live tree (just verified clean by the l1 run).
2. **`TargetSnapshot.load(protocols, root)`** classmethod — opens an existing golden directory instead of capturing; errors up front listing any watched file with no golden copy (e.g. after protocols change). `capture(protocols, dest=GOLDEN)` remains the way to (re)provision it.
3. **New `examples/capture_golden.py`** — the explicit out-of-band "declare known-good" step that captures the live targets into `golden/`. The attestation/restore flow itself never writes golden state, preserving the single-writer trust boundary.
4. **`gumbo_attestation.py`**: drop the per-run temp capture; `load()` the golden dir (with a pointer to `capture_golden.py` if it's missing), tamper live, and `restore()` from golden in the `finally`.
5. **Integration tests**: the `live_snapshot` fixture loads from `golden/` instead of capturing per-test.
6. **README**: update the snapshot section to describe golden provisioning vs. restore.

One choice worth flagging: I'm putting `golden/` inside the pybb repo (committed alongside the protocol fixtures it was provisioned with, since the two must stay in sync). If you'd rather keep it outside the repo (e.g. a sibling of `temp-control-jvm`), say so — everything else is unchanged.

Proceed?

## User

Yes, proceed.

## Assistant

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/snapshot.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/snapshot.py

> `[Write]` /Users/adampetz/Claude_workspace/pybb/examples/capture_golden.py

The live tree was verified clean by the last l1 run, so provision `golden/` now:

> `[Bash]` Provision the golden directory from the clean live tree

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_snapshot.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_snapshot.py

> `[Bash]` Run unit and CVM integration tests

> `[Bash]` Run clean and tampered example against golden dir

The golden directory is in place and everything verifies. Summary:

## What changed

- **`golden/` at the repo top level** — provisioned now with clean copies of all 6 watched files (2 AADL models, 2 GumboX oracles, 2 component `.scala` files), mirrored by absolute path so they map unambiguously back to their live locations.
- **[capture_golden.py](pybb/examples/capture_golden.py)** — the explicit provisioning step that (re)creates `golden/` from the live tree. Its docstring states the policy: run it only when the tree is verified clean, in step with the protocol fixtures whose golden hash values were provisioned against these same files.
- **`TargetSnapshot.load(protocols, root)`** in [snapshot.py](pybb/pybb/attestation/snapshot.py) — opens an existing golden dir and fails up front, naming each watched file that lacks a golden copy (the guard for protocols drifting ahead of the golden set). `capture()` is now purely the provisioning primitive; nothing in the attestation or restore flow writes golden state.
- **[gumbo_attestation.py](pybb/examples/gumbo_attestation.py)** — loads `golden/` instead of capturing a temp snapshot (exiting with a pointer to `capture_golden.py` if missing); the `finally` restores the live tree from golden.
- **[test_integration_cvm.py](pybb/tests/test_integration_cvm.py)** — the `live_snapshot` fixture loads from `golden/` too.
- README's snapshot section rewritten around golden provisioning vs. restore; 2 new unit tests for `load()` (happy path, missing-copy error).

## Verification

- Unit tests: **34 passed**. CVM integration tests: **2 passed** (tamper-live → l2 attribution → teardown restore from golden).
- Clean example run: "Golden targets: 6 files", l1 passes. `--tamper` run: escalates with the l2 report, then "Restored 1 live target(s) from golden", and the live AADL line verified back to clean.

A nice property of the new arrangement: the restore source no longer depends on run-time state at all — a tampered tree can sit tampered across runs (or a crash) and the next run still restores from true gold, whereas the old per-run capture would have snapshotted the tampered state as "clean."

Still nothing committed — `golden/` should land in the same commit as the work, since it's provisioned in step with the protocol fixtures. Want me to commit the branch at this point?

## User

commit

## Assistant

> `[Bash]` Show working tree status before committing

> `[Bash]` Commit all changes on dev branch

> `[Read]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

> `[Edit]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

Committed and memory updated.

**Commit `1d6d53f` on `dev`** — "attestation: attest live targets, restore from provisioned golden dir" — 20 files changed, +1311/−209. It includes:

- The new `snapshot.py` module and its unit tests
- The complete `path_map`/`carry_path_map` removal (including `rewrite_filepaths` deletion)
- The `golden/` directory with the 6 provisioned target copies and `capture_golden.py`
- The reworked `--tamper` demo and integration tests (tamper live, restore from golden)
- README updates documenting the golden-directory trust model

The branch is local-only at this point (no `origin/dev`). Say the word if you want it pushed, and likewise when you're ready to tackle the next piece — the open threads are what triggers restore (the repair KS / new-run revert decision you deferred) and re-porting the repair layer from `attestation-integration` onto the routed design, remembering that post-repair re-attestation now needs a nonce bump to defeat the predicate cache.

## User

First, confirm where the provisioned evidence bundle comes from

## Assistant

Let me trace the provenance concretely — both what the fixtures contain and where they were generated.

> `[Bash]` Inspect fixture asp_args and cvm-mcp protocol_dirs

> `[Bash]` Compare pybb fixtures against cvm-mcp protocol_dirs and find provisioning code

> `[Bash]` Locate provisioning endpoint and inspect provision_bundle.json shape

> `[Read]` /Users/adampetz/Claude_workspace/cvm-mcp/protocol_loader.py

> `[Bash]` Confirm dashboard provisioning endpoint

Confirmed — here's the full provenance chain, verified against the actual code and data:

## Where the provisioned evidence comes from

**1. The pybb fixtures are verbatim copies of cvm-mcp's protocol dirs.** I diffed `asp_args.json` for both `gumbo_l1` and `gumbo_l2` between [pybb/tests/fixtures](pybb/tests/fixtures) and `cvm-mcp/protocol_dirs/` — byte-identical, golden values included. (pybb copies only the config files; the bundle itself stays in cvm-mcp.)

**2. They were provisioned by the cvm-mcp dashboard**, via `GET /api/provision/<protocol_id>` (dashboard.py:1884 → the `provision()` closure at protocol_loader.py:503). What that does, mechanically:

- Builds a **measurement-only variant of the protocol's own term** (`_make_measurement_term` swaps APPR → NULL so the run always succeeds), strips bookkeeping keys and injects `asp_id_appr` so evidence args stay stable across runs.
- **Runs the real CVM binary against the live `temp-control-jvm` tree** — so the goldens are produced by the exact same ASPs (`hashfile`, `readfile_range`, `readfile_marker_range`) that later re-measure at attestation time, not by some parallel hashing path.
- Writes the response as **`provision_bundle.json`** in the protocol dir — `[[rawev, evidencet], global_context]`, i.e. the CVM's own evidence tree of the live tree at provision time. That file *is* the provisioned evidence bundle.
- For each target, invokes the **`extract_golden_slice` binary from asp-libs** (`asp-libs/target/release`) with `(protocol_dir, asp_id, targ_id)` to cut that component's slice out of the bundle, and writes it back as **`golden_b64` + `golden_ts` in `asp_args.json`**.

**3. The timestamps date the declarations:** `gumbo_l1` goldens were provisioned 2026-05-07, `gumbo_l2` 2026-05-27 — both snapshots of the same live tree we're attesting now, which is why the clean l1 run still passes.

## Implication for our golden directory

There are now **two golden artifacts, provisioned from the same source (the live tree) by two different writers**:

| artifact | content | writer | consumed by |
|---|---|---|---|
| `golden_b64` in `asp_args.json` (+ `provision_bundle.json`) | evidence slices (hashes / content) | cvm-mcp dashboard, May 2026 | appraisal (pass/fail verdicts) |
| pybb `golden/` file copies | the files themselves | `capture_golden.py`, today | restore (repair / new-run revert) |

They agree today (l1 passes and our capture happened right after a verified-clean run), but they're coupled only by discipline: re-provisioning through the dashboard without re-running `capture_golden.py` (or vice versa) would let them drift. That's the invariant the repair work needs to respect — a restore from `golden/` should put the tree in exactly the state the `golden_b64` values attest to, or l1 will fail *after* a "successful" repair.

## User

Let's add a knowledge source that provisions files from the golden directory, in response to some external event that adds new files to the golden directory (and adds a request to the blackboard to re-provision the files in the golden dir)

## Assistant

Let me review the controller and blackboard mechanics first so the new KS fits the routed idiom properly.

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/controller.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/blackboard.py

Now I understand the controller mechanics well enough to design this in the routed idiom. One structural observation first: this KS is different in kind from `TierKS` — it's the first *repair-shaped* KS on the attestation blackboard (it changes the world, then asks the predicate to re-check), which is exactly the `NumberAdder` pattern from `ks_examples.py`: predicate = "is the live tree in sync with golden", KS = "make it so".

One design point the request surfaces: `TargetSnapshot.load()` derives its file set from the *protocols'* `asp_args` — but your external event adds **new** files to the golden directory, which no protocol watches yet. So the provisioning flow must be driven by *what's in the golden dir*, not by the protocols. Here's my plan:

1. **`TargetSnapshot.scan(root)`** in [snapshot.py](pybb/pybb/attestation/snapshot.py) — build the snapshot from the golden tree itself: walk every file under `root` and map it back to the live absolute path it mirrors. This naturally picks up newly added golden files.
2. **New module `pybb/attestation/provision.py`**:
   - `provision_request(golden_root, event)` — measurement builder, analogous to `attestation_request`; `event` (an id/timestamp supplied by the external event) distinguishes successive requests.
   - `ProvisionStatus` — result model like `Verdict`: `pending` (live files out of sync with golden) + `error`; truthy iff fully synced, so `good_standing = bool(result)` just works.
   - `provision_predicate(measurement)` — scans the golden root, reports dirty/missing live files. Cheap (byte compare), so no memoization — it genuinely re-checks each cycle.
   - `ProvisionKS` — on dispatch, `scan(golden_root).restore()` (copy golden → live, creating files that don't exist yet), then rewrites the entry with `result=None` so the controller re-evaluates. If restore can't converge (e.g. permissions), attempts exhaust and the entry escalates carrying the pending list — same end-of-chain behavior as the tiers.
3. **Wiring** (in the example): the external event does two things — drops files into `golden/` and calls `blackboard.write_entry(key="provision", predicate="provision", measurement=provision_request(...))`; the route is `controller.route("provision", on_fail=[ProvisionKS()])`.
4. **Unit tests** (tmp golden + live trees, no CVM): event adds a brand-new golden file and updates an existing one → request entry → run → both provisioned to live, entry in good standing, `ks_history` shows the KS fired once; plus the escalation path.
5. **Example** `examples/golden_provision_event.py` — simulates the event against the real trees (adds a demo file to `golden/`, tampers a live target), runs the controller, then cleans up the demo file from both trees in a `finally`.
6. README section on the provisioning KS.

Deliberately deferred (flag if you want it now): after provisioning, the attested files have changed, so the `gumbo` attestation entry should re-attest via a nonce bump — but whether provisioning *triggers* attestation (and how the two entries link) feels like the next design conversation, tangled with the golden_b64-staleness coupling we identified.

Proceed?

## User

Provisioning should be simpler on the blackboard.  Create a distinct predicate as a blackboard request for provisioning, and have that predicate invoke the cvm in its normal provisioning mode (to create the golden evidence bundle) but targeting the files in the golden directory.

## Assistant

This changes the shape nicely — the provisioning *predicate* mirrors the attestation predicate ("the predicate IS the provisioning"), no repair-shaped KS needed. Before I draft the plan, let me check the mechanics I'd need to replicate: how cvm-mcp builds the measurement-only term, and how the gumbo protocols' appraisers are configured.

> `[Bash]` Inspect gumbo session appraiser config and measurement-term builder

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/appraisal.py

> `[Bash]` Read evidence slice logic and check extract binary

One more mechanic to pin down — what `extract_golden_slice` reads from its directory argument:

> `[Bash]` Read extract_golden_slice source

I have the full picture now. Key facts that shape the design:

- Both gumbo protocols are `goldenbytes_appr`-based (`extract_golden_slice`'s exact use case), so pybb can drive the same provisioning flow cvm-mcp does: measurement-only CVM run (APPR stripped) → `provision_bundle.json` → `extract_golden_slice <dir> <asp_id> <targ_id>` → `golden_b64` per target.
- `hashfile`/`readfile_range` goldens are functions of file *content* only — so goldens provisioned from the golden-dir copies are exactly valid for attesting the live tree. That's what makes "provision from golden/" sound.
- `extract_golden_slice` matches evidence by ASP_ARGS, so the bundle dir it reads needs an `asp_args.json` whose filepaths match the (golden-rooted) term we ran.

## Plan

**1. New `pybb/attestation/provision.py`** — "the predicate IS the provisioning", mirroring the attestation predicate:

- `provision_request(protocol_id, nonce=0)` → `{"protocol", "nonce"}` (same descriptor shape; the predicate name distinguishes the semantics).
- `ProvisionOutcome` result model (protocol, provisioned target ids, bundle path, error; truthy iff provisioning succeeded) — so `good_standing = bool(result)` works unchanged.
- `make_provision_predicate(client, protocols, golden_root)` — memoized on the measurement like attestation. Per call it:
  1. Builds the measurement-only term (vendor `_make_measurement_term` — APPR→NULL — and `asp_id_appr` injection from cvm-mcp, the repo's established vendoring pattern), gated on the session actually using `goldenbytes_appr`.
  2. Re-roots every `filepath` arg to its **golden-dir mirror**, erroring up front if any golden copy is missing.
  3. Runs it through the existing client — no client-interface change: `run_protocol(protocol.model_copy(update={"prebuilt_request": request}))`.
  4. Writes the **golden evidence bundle** `[payload, global_context]` + the matching golden-path `asp_args.json` under `golden/_bundles/<protocol_id>/`.
  5. Invokes asp-libs `extract_golden_slice` per target, then writes the fresh `golden_b64`/`golden_ts` back into the protocol's `asp_args.json` (live paths) and updates the in-memory `ProtocolDir` — **also dropping any stale `cvm_request.json`/`prebuilt_request`**, which bakes in old goldens (this is a real staleness bug waiting to happen for `gumbo_l1`).

**2. Blackboard usage** — just an entry, no KS, no route needed: the external event drops files in `golden/` and writes `write_entry(key="provision:gumbo_l1", predicate="provision", measurement=provision_request("gumbo_l1"))`; re-provisioning later = new entry with a bumped nonce.

**3. Tests** — unit tests with a fake client + injected fake extractor (term has no APPR, paths golden-rooted, memoization, missing-golden-file error); a CVM integration test that copies the fixture protocol dirs to tmp, provisions from the real `golden/`, and asserts the freshly extracted `golden_b64` values **equal the May-provisioned fixture values** (they must, since golden content == provisioned content) and that attestation then passes.

**4. Example + README** — a demo showing the provision request on the blackboard followed by a clean attestation; README gains a "Provisioning on the blackboard" section (and retires the "provisioning is out of scope" claim in favor of: pybb provisions *only from the golden directory*, so the trust boundary — never provision from live/failed state — moves to who may write `golden/`).

Sound good?

## User

What is run_protocol?

## Assistant

`run_protocol` is the single method on the attestation client abstraction — the seam between the blackboard layer and the actual CVM transport. Concretely, in [client.py](pybb/pybb/attestation/client.py):

**The interface** (`AttestationClient`, client.py:130) declares just one method:

```python
@abstractmethod
def run_protocol(self, protocol: ProtocolDir) -> dict:
    """Execute the protocol and return the parsed ProtocolRunResponse dict."""
```

It takes a `ProtocolDir` (the loaded protocol directory: term, session, manifest, asp_args, optional prebuilt request) and returns the CVM's parsed JSON response. It's deliberately transport-agnostic — the docstring's promise is "execute this protocol somehow, give me the response dict."

**The one real implementation**, `CvmSubprocessClient` (client.py:140), does:

```python
def run_protocol(self, protocol: ProtocolDir) -> dict:
    request = protocol.build_request()      # assemble the ProtocolRunRequest
    return self._run_cvm(protocol.manifest, request)
```

where `build_request()` (client.py:90) returns the protocol's `prebuilt_request` verbatim if `cvm_request.json` was present in the directory, otherwise assembles one dynamically (splices `asp_args` into the term via `inject_asp_args`, normalizes, wraps with the session). `_run_cvm` then writes the manifest and request to temp files and invokes the CVM binary as a subprocess with the configured environment (`ASP_BIN`, `path_prepend`, etc.).

**Who calls it:** exactly one place in the core — the attestation predicate's `_attest` ([knowledge_sources.py:99](pybb/pybb/attestation/knowledge_sources.py:99)) calls `client.run_protocol(protocol)` and appraises the response. Tests substitute a `FakeClient` with a scripted `run_protocol`; the README notes a future socket/AM client could slot in behind the same interface.

**Why my plan mentioned it:** the provisioning predicate needs to run a *modified* request (APPR-stripped term, golden-rooted paths) that no protocol directory literally contains. Rather than widening the client interface with a "run this raw request" method, the plan exploits the `prebuilt_request` precedence in `build_request()`: hand `run_protocol` a `protocol.model_copy(update={"prebuilt_request": <provisioning request>})`, and the existing client executes it unchanged — same transport, same manifest, same environment handling.

If you'd rather the client grow an explicit `run_request(manifest, request)` method instead of the `model_copy` trick (arguably more honest, at the cost of touching the ABC and the fake), that's an easy swap — say which you prefer.

## User

So run_protocol is an internal helper function, and not a predicate on the blackboard?  What are all the current predicates on the blackborad?

## Assistant

Right — `run_protocol` never touches the blackboard. Let me enumerate every registered predicate across the codebase:

> `[Bash]` Find all predicate registrations

Correct — `run_protocol` is plumbing inside the client, three layers below the blackboard. The blackboard only ever sees **named predicates**: callables registered in the controller's `predicate_registry` (controller.py:51), referenced by entries by name, and invoked as `fn(entry.measurement)` each cycle with `good_standing = bool(result)`.

Here's the complete current inventory:

## Attestation predicates (the real system)

There is exactly **one**: `"attestation"`, the closure built by `make_attestation_predicate(client, protocols)` ([knowledge_sources.py:79](pybb/pybb/attestation/knowledge_sources.py:79)). It's registered under that name in four places — [gumbo_attestation.py:110](pybb/examples/gumbo_attestation.py:110) and the three attestation test files — always the same factory, just different clients (real `CvmSubprocessClient` vs. `FakeClient`).

Its internal call chain, none of which is blackboard-visible:

```
"attestation" predicate(measurement)          <- the only blackboard-facing layer
  └─ _attest(client, protocols, measurement)
       └─ client.run_protocol(protocol)       <- transport
       │    └─ protocol.build_request() → _run_cvm(...)
       └─ parse_appraisal(response, records) → Verdict
```

## Toy predicates (pre-attestation examples)

From [ks_examples.py](pybb/pybb/ks_examples.py), used only by `example.py`, `example_pair.py`, and `test_controller_routes.py`:

- `"less_than_3"`, `"is_positive"`, `"is_100"` — plain int checks. The pair example uses the first two as per-component `conditions` rather than a single entry predicate.

## So the picture for the provisioning work

Today the attestation blackboard is a **one-predicate system** — every entry asks the same kind of question ("does this protocol attest clean?") and all variation lives in the measurement (`which` protocol) and the routes (what to try next). What you asked for adds the **second predicate kind**, `"provision"`: same registry mechanism, same `bool(result)` convention, but the question is "has the golden evidence bundle been produced from the golden directory?" — and its side effect is creating that bundle, exactly as the attestation predicate's side effect is running the protocol. `run_protocol` stays where it is, serving both predicates from below.

## User

How are protocols distinguished in the attestation predicate?  Break it down in detail.

## Assistant

Protocol identity flows through the attestation predicate as a **string id in the measurement**, resolved against a **dict captured in the predicate's closure**. Here's the complete chain, layer by layer:

## 1. The id enters via the measurement

An attestation entry's measurement is the descriptor built by `attestation_request` ([knowledge_sources.py:58](pybb/pybb/attestation/knowledge_sources.py:58)):

```python
{"protocol": "gumbo_l1", "nonce": 0}
```

The `"protocol"` field is the *only* thing that names a protocol on the blackboard. Entries, verdicts, and routes never hold `ProtocolDir` objects — just this string.

## 2. The resolution table lives in the closure

`make_attestation_predicate(client, protocols)` captures a plain dict at construction time:

```python
protocols = {pid: ProtocolDir.load(str(fixtures / pid))
             for pid in ("gumbo_l1", "gumbo_l2", "gumbo_validation")}
```

The **caller chooses the keys**. By convention they match the fixture directory name (`ProtocolDir.load` also defaults its own `protocol_id` field to the dir basename, client.py:80), but nothing enforces that the dict key equals `ProtocolDir.protocol_id` — the dict key is what the blackboard id resolves against; the `protocol_id` attribute is used for logging and by the `FakeClient` to script responses. That's a soft coupling worth knowing about: register a protocol under a different key than its `protocol_id` and lookups still work, but reporting would show the mismatch.

## 3. Lookup and the unknown-protocol path

`_attest` ([knowledge_sources.py:95](pybb/pybb/attestation/knowledge_sources.py:95)) does the resolution:

```python
protocol_id = measurement.get("protocol", "")
protocol = protocols.get(protocol_id)
if protocol is None:
    return Verdict(protocol=protocol_id, passed=False,
                   error=f"unknown protocol '{protocol_id}'")
```

An unregistered id isn't an exception — it's a *failing Verdict*, so the controller treats it like any attestation failure: dispatch to `on_fail`, ultimately escalate. The resolved `ProtocolDir` then supplies everything protocol-specific downstream: `client.run_protocol(protocol)` (term, session, manifest, prebuilt request) and `protocol.target_records()` (the asp_args flattened to `{asp_id, targ_id, args}` so appraisal components can be matched back to stable target ids).

## 4. The memo cache distinguishes protocols too

The predicate memoizes on the **entire serialized measurement** (knowledge_sources.py:88):

```python
key = json.dumps(measurement, sort_keys=True)   # e.g. '{"nonce": 0, "protocol": "gumbo_l1"}'
```

So `gumbo_l1` and `gumbo_l2` verdicts cache independently, and the same protocol re-attests only when the nonce changes. This is why one entry can walk multiple tiers in one run without re-running earlier tiers.

## 5. Tier hops = rewriting the id

`TierKS.execute` is *nothing but* a protocol-id rewrite (knowledge_sources.py:130): it writes a new measurement with its own `protocol_id` (carrying the nonce forward) and `result=None`. Next cycle, the controller re-evaluates the entry, the predicate sees a measurement it hasn't cached, and attestation happens at the new tier. The `Verdict.protocol` field records which id produced the current result — that's how `trust_summary` can say "l1 passed; confirmed by gumbo_validation".

## 6. Which ids get tried is route topology

The decision tree over protocol ids lives entirely outside the predicate, in the route: `route("gumbo", on_pass=[TierKS("gumbo_validation")], on_fail=[TierKS("gumbo_l2")])`. The predicate is deliberately ignorant of tier ordering — it answers "what does protocol X say right now", and the routes decide which X comes next.

**Summary:** one string field, resolved through one closure-captured dict, cached by one JSON key — with unknown ids degrading to failing verdicts rather than errors. The provisioning predicate in our plan mirrors this exactly: same `{"protocol", "nonce"}` descriptor, its own `protocols` + `golden_root` closure, registered under the distinct name `"provision"` so the entry's `predicate` field — not the measurement — is what distinguishes attesting from provisioning.

## User

break down the "attestation" predicate.  How does it map to protocols?

## Assistant

Here's the anatomy of the `"attestation"` predicate, from registration down to the verdict — with emphasis on where the protocol mapping actually happens.

## The three-level mapping

```
"attestation"  ──registry──▶  predicate closure  ──protocols dict──▶  ProtocolDir  ──client──▶  Verdict
 (entry.predicate)             (one instance)      (measurement["protocol"])         (CVM run)
```

Two different names are being resolved, at two different times: the **predicate name** (`entry.predicate = "attestation"`, resolved through `predicate_registry` once per evaluation) selects the *kind* of question; the **protocol id** (`entry.measurement["protocol"]`, resolved through the closure's dict) selects *which* protocol answers it. One predicate instance serves every protocol — per-protocol variation is data in the measurement, never code.

## Level 1: the factory and its closure

```python
def make_attestation_predicate(client, protocols) -> Callable[[dict], Verdict]:
    cache: Dict[str, Verdict] = {}

    def predicate(measurement: dict) -> Verdict:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            cache[key] = _attest(client, protocols, measurement)
        return cache[key]

    return predicate
```

([knowledge_sources.py:79](pybb/pybb/attestation/knowledge_sources.py:79)) The closure captures three things for life: the **client** (transport), the **protocols dict** (`{id → ProtocolDir}` — the whole protocol map), and the **cache**. The controller calls this every cycle for every attestation entry; the cache is what makes that affordable. Note what the cache key is: the *serialized measurement*, so the memo table is itself keyed by protocol id + nonce — `{"nonce": 0, "protocol": "gumbo_l1"}` and `{"nonce": 0, "protocol": "gumbo_l2"}` are separate rows, and a nonce bump is a cache miss by construction.

## Level 2: `_attest` — where the id becomes a protocol

```python
def _attest(client, protocols, measurement) -> Verdict:
    protocol_id = measurement.get("protocol", "")          # (a) extract the id
    protocol = protocols.get(protocol_id)                  # (b) THE mapping
    if protocol is None:                                   # (c) unknown id -> failing Verdict
        return Verdict(protocol=protocol_id, passed=False,
                       error=f"unknown protocol '{protocol_id}'")
    try:
        response = client.run_protocol(protocol)           # (d) execute
    except Exception as e:
        return Verdict(protocol=protocol_id, passed=False, error=str(e))
    components = parse_appraisal(response, protocol.target_records())   # (e) appraise
    return Verdict(protocol=protocol_id,
                   passed=overall_verdict(components),
                   components=components)
```

Step **(b)** is the entire protocol mapping: a dict lookup. Everything protocol-specific downstream comes from the resolved `ProtocolDir` object — the term/session/manifest that `run_protocol` executes, and `target_records()` (asp_args flattened to `{asp_id, targ_id, args}`), which step **(e)** uses to match appraisal evidence back to stable target ids like `tc_sys_aadl_305_308_targ`.

Note the failure discipline: *every* path returns a `Verdict` tagged with the protocol id — unknown id, transport exception, failed appraisal. Nothing raises through to the controller, so bad states flow through the normal routing machinery (on_fail → escalate) instead of crashing the run.

## Level 3: the Verdict carries the mapping back out

```python
class Verdict(BaseModel):
    protocol: str          # which id produced this result
    passed: bool
    components: List[ComponentResult]
    error: str = ""
    def __bool__(self): return self.passed
```

The controller does `good_standing = bool(result)` blindly; `Verdict.__bool__` makes that the overall appraisal. The `protocol` field is how downstream consumers (routes' dispatch logs, `trust_summary`, the escalate report) know *which tier* rendered the current verdict — remember the entry's measurement gets rewritten by `TierKS` as tiers change, so the verdict's own tag is the durable record of who said what.

## Where the dict itself comes from

The mapping table is assembled by the caller, once, before the run:

```python
protocols = {pid: ProtocolDir.load(str(FIXTURES / pid))
             for pid in ("gumbo_l1", "gumbo_l2", "gumbo_validation")}
controller.register_predicate("attestation",
    make_attestation_predicate(CvmSubprocessClient(), protocols))
```

So the predicate's protocol universe is fixed at registration time — a `TierKS` can only point at ids the closure already knows, and anything else degrades to the `unknown protocol` verdict. (This is also the constraint our provisioning predicate will inherit: for freshly provisioned goldens to be *seen* by attestation in the same run, the provisioning step must mutate these same shared `ProtocolDir` objects, not reload its own copies.)

## User

How do predicates relate to "partitions" in the blackboard architecture?

## Assistant

"Partition" actually names **two different things** in this codebase, and predicates relate to each differently. Worth separating cleanly:

## The two partitions

**1. `KnowledgeSource.partition: list[str]`** ([knowledge_source.py:11](pybb/pybb/knowledge_source.py:11)) — the set of blackboard *keys this KS is currently responsible for*. This is the classic blackboard-architecture notion of a KS watching its region of the board. In pybb it's dynamic: comment says "assigned by controller route()".

**2. The board segments** — `write_entry(..., partition="certify"|"escalate")` ([blackboard.py:38](pybb/pybb/blackboard.py:38)): the blackboard's two regions. `entries` (the certify segment — the working board) and `escalate` (the terminal segment for entries the KS machinery gave up on). History is a third, append-only view.

## How predicates drive both

Predicates are the **judgment axis**; partitions are the **responsibility axis**. The controller's cycle wires them together in one direction — predicate outcomes move keys between partitions, never the reverse:

**Predicates gate whether a partition means work.** A KS holding keys in its partition does nothing while those entries are in good standing: `can_contribute` → `_needs_work` → `not entry.good_standing` (knowledge_source.py:15-27), and `good_standing` is nothing but the boolean of the last predicate result. So a `TierKS` with `"gumbo"` in its partition is *armed*, not active — the `"attestation"` predicate's Verdict decides if it fires.

**Predicate outcomes populate partitions.** All routed KSs start with empty partitions (`route()` even scrubs the key from them, controller.py:68-70). The first predicate evaluation is what places a key: `_dispatch` (controller.py:72) reads the entry's fresh `good_standing` and appends the key to the *first KS of the chosen chain's* partition — `on_fail`'s head if the predicate failed it, `on_pass`'s head if it passed with a confirmation chain pending. Partition membership is therefore an *artifact of a predicate verdict*, not static configuration.

**Predicate outcomes move keys along and out of partitions.** When a KS exhausts `max_attempts` on a key that predicates still fail, `_advance` removes the key from its partition and appends it to the next KS in the dispatched chain (controller.py:97). When no KS remains, the entry leaves the certify segment entirely — popped from `entries` into `escalate` (controller.py:120), carrying its last predicate result as the failure report. And the escalate segment is precisely the region **predicates no longer touch**: `_evaluate_all` iterates only `blackboard.entries`, so escalation is the transition from "predicate-governed" to "human-governed."

## The component-scoped refinement

For dict measurements, the pairing gets finer-grained: an entry can carry `conditions` (component name → predicate name) instead of one predicate, and a KS can set `component` to scope itself to one slice. Then `_needs_work` consults `component_good(self.component)` — that component's own predicate result — so two KSs can share a key in their partitions while each answers to a different predicate (`example_pair.py`'s `ComponentAdder`/`ComponentSubtractor` under `less_than_3`/`is_positive`). Success-driven handoff (`_advance_ready`) likewise advances a key when *its* component's predicate goes green, independent of siblings.

## In the attestation instantiation

Concretely for the gumbo run: `"gumbo"` starts in nobody's partition. The `"attestation"` predicate fails it at l1 → `_dispatch` puts `"gumbo"` into `TierKS("gumbo_l2")`'s partition → that KS rewrites the measurement → the predicate (cache-missed by the new protocol id) passes l2 → the key sits in the partition but `_needs_work` is false, so the run halts with the entry in certify, in good standing. Had l2 failed too: attempts exhaust, no next KS, and the entry migrates to the escalate segment with the failing Verdict.

**One-line summary:** predicates decide *standing*; standing decides *which partition a key occupies* (whose KS partition, and ultimately which board segment); partitions decide *who may act next* — a strict evaluate → place → act loop, repeated each cycle. The provisioning predicate will slot into this untouched: a `provision:*` entry fails until the bundle exists, sits in whatever chain you route it to (likely none — straight to escalate on failure), and goes green when provisioning succeeds.

## User

Before we go forward, can you tell me where the temp-control-jvm example came from or how I'd point at it

## Assistant

Let me look at the tree itself for provenance clues.

> `[Bash]` Inspect temp-control-jvm tree for provenance

> `[Bash]` Look for readme/config and AADL header

> `[Bash]` Check HAMR codegen version metadata and stale sidecar files

> `[ToolSearch]`

> `[WebSearch]`

Here's the full provenance picture:

## What it is

`~/Claude_workspace/temp-control-jvm` is the **canonical HAMR "Temperature Control" tutorial example** from SAnToS Lab (KSU) — the AADL header in [TempControlSystem.aadl](../temp-control-jvm/aadl/packages/TempControlSystem.aadl) identifies it as "Temperature Control System — Tutorial 00 (initial model), Mixed port categories, Platform: Slang/JVM, Author: SAnToS Lab Team." It's the standard pedagogical model used throughout the HAMR documentation and course materials: a temp sensor, cooling fan, and controller with GUMBO contracts, code-generated to Slang/JVM by HAMR (the `slang/` tree is HAMR codegen output — `bridge/`, `component/`, GumboX oracles, `versions.properties`).

The local copy has **no `.git`**, so I can't tell you definitively which upstream it was cloned/exported from, but the family lives in the [SAnToS Lab GitHub org](https://github.com/santoslab) (e.g. `hamr-examples`, [tccoe22-hamr](https://github.com/santoslab/tccoe22-hamr)) and the model is walked through in the [HAMR docs' Temp Control walkthrough](https://hamr.sireum.org/hamr-doc/ch0X-hamr-sel4-tempControl-walkthrough.html). Provisioning timestamps in the fixtures say this copy has been in place since at least 2026-05-07.

## How it's pointed at (three places, all hardcoded absolute paths)

1. **`TC_ROOT` constants** — `Path("/Users/adampetz/Claude_workspace/temp-control-jvm")` in [gumbo_attestation.py:44](pybb/examples/gumbo_attestation.py:44) and [test_integration_cvm.py](pybb/tests/test_integration_cvm.py) (used only to locate the tamper target and gate test skips).
2. **The provisioned protocol fixtures** — every `filepath` in `tests/fixtures/gumbo_*/asp_args.json` (and the l1 `cvm_request.json`) is an absolute path into that tree. This is the binding that actually matters: the CVM measures exactly these paths.
3. **The `golden/` mirror** — which encodes the same absolute paths in its directory layout.

So "pointing at it" somewhere else isn't a one-variable change: the paths are baked into the provisioned artifacts. Moving or renaming the tree means **re-provisioning** — regenerate `asp_args.json` (via cvm-mcp's generators/dashboard, or the blackboard provisioning predicate we're about to build), re-extract goldens, and re-capture `golden/`. That's worth keeping in mind as a design input for the provisioning predicate: it's also the mechanism that would let you re-target a relocated or freshly cloned example.

## One incidental find

The AADL directory contains stale sidecar files from the *old* (pre-`golden/`) backup mechanism: `TempControlSystem.aadl.original`, `.src`, and four `*.original_golden.json` files — artifacts of the earlier copy-backup/restore demos from the `attestation-integration` era. I verified `.original` matches the current file (clean). Now that `golden/` owns restore, these are dead weight and mild confusion risk; a quick cleanup pass over `temp-control-jvm` is worth doing at some point (not urgent, and I haven't touched them).

Sources: [SAnToS Laboratory GitHub](https://github.com/santoslab), [Temp Control Walkthrough — Sireum HAMR](https://hamr.sireum.org/hamr-doc/ch0X-hamr-sel4-tempControl-walkthrough.html), [tccoe22-hamr](https://github.com/santoslab/tccoe22-hamr)

## User

Before proceeding, let's add the original temp-control-jvm example files to the pybb repo in a directory, so that they are pushed to the repo and available to others

## Assistant

Let me check what the tree contains and how big each part is, so we vendor the right subset.

> `[Bash]` Measure temp-control-jvm tree sizes

The whole tree is 9.1 MB / 998 files, but 7.9 MB of that is `slang/out/` — HAMR/sbt build output. Excluding it leaves a clean 1.2 MB / 135 files. My proposed plan:

1. **Copy to `targets/temp-control-jvm/`** at the pybb repo top level (peer of `golden/`, which references it) — keeping the internal layout (`aadl/`, `slang/bin`, `slang/src`, `versions.properties`) intact so it's a runnable HAMR project after `sireum proyek` regeneration.
2. **Exclude**: `slang/out/` (build output), and the stale sidecar files we just identified (`*.original`, `*.src`, `*.original_golden.json` — artifacts of the retired backup mechanism; they'd be noise for anyone pulling the repo).
3. **Add `targets/temp-control-jvm/README.md`** noting provenance (SAnToS Lab HAMR TempControl tutorial, Slang/JVM platform, with links) and the important caveat: the *attested live tree* is `~/Claude_workspace/temp-control-jvm` — the provisioned protocol fixtures and `golden/` bake in that absolute path, so someone adopting this copy as their live target must re-provision (which the upcoming provisioning predicate will make possible from the blackboard).
4. **Commit** on `dev`.

This is a vendored source-of-record — it does *not* re-point anything; the live target stays where it is for now.

Proceed?

## User

Yes, proceed.

## Assistant

> `[Bash]` Copy temp-control-jvm sources into pybb/targets, excluding build output and stale sidecars

Let me verify the copy landed in the right place (shell cwd can be surprising):

> `[Bash]` Verify copy destination is correct

> `[Bash]` Confirm sidecars and build output excluded

> `[Write]` /Users/adampetz/Claude_workspace/pybb/targets/temp-control-jvm/README.md

> `[Bash]` Commit vendored temp-control-jvm to dev

Done — committed as `4adb424` on `dev`.

**What landed in `targets/temp-control-jvm/`** (117 files, ~1 MB):
- `aadl/packages/` — the four AADL files only (`TempControlSystem`, `TempSensor`, `CoolingFan`, `defs`); the stale `*.original`/`*.src`/`*.original_golden.json` sidecars were excluded, verified zero slipped through.
- `slang/` — the full HAMR-generated project (`bin/` cmd scripts, `src/main` architecture/bridges/components/GumboX oracles, `src/test` GumboX unit-test harnesses, `versions.properties`); `slang/out/` build output (7.9 MB) excluded.
- [README.md](pybb/targets/temp-control-jvm/README.md) with provenance (SAnToS Lab HAMR TempControl tutorial, links to the HAMR walkthrough and org) and the re-provisioning caveat: fixtures and `golden/` still bake in absolute paths to the live tree at `~/Claude_workspace/temp-control-jvm`, so anyone adopting this copy as their live target needs to re-provision against their chosen path.

The `dev` branch now has two commits (`1d6d53f` golden/live-target rework, `4adb424` vendored target) and is still local-only — tell me when you want it pushed.

Ready to return to the provisioning predicate whenever you are; the vendored copy actually strengthens that story, since the provisioning predicate is exactly the mechanism that would let someone re-target a fresh checkout of `targets/temp-control-jvm`.

## User

push dev branch to github

## Assistant

> `[Bash]` Push dev branch to origin with upstream tracking

> `[Bash]` Push dev branch to origin with upstream tracking

Pushed — `dev` is now on GitHub at [ku-sldg/pybb](https://github.com/ku-sldg/pybb/tree/dev) with both commits (`1d6d53f` live-target attestation + golden restore, `4adb424` vendored temp-control-jvm), tracking `origin/dev`. GitHub offers [a PR creation link](https://github.com/ku-sldg/pybb/pull/new/dev) whenever you're ready to merge to `main`.

## User

Let's look at the plan again for provisioning before proceeding

## Assistant

Here's the provisioning plan again, refreshed with everything we've established since I first sketched it — the settled parts, then the open decisions I'd like your ruling on before writing code.

## The core design (settled, unless you object)

**A second named predicate, `"provision"`, alongside `"attestation"`** — same registry mechanism, same `bool(result)` convention, same descriptor shape. The predicate IS the provisioning, exactly parallel to the attestation predicate:

```python
controller.register_predicate("provision",
    make_provision_predicate(client, protocols, golden_root))
blackboard.write_entry(key="provision:gumbo_l1", predicate="provision",
    measurement=provision_request("gumbo_l1"))   # {"protocol": ..., "nonce": 0}
```

No KS, no route required. The external event = drop files into `golden/` + write this entry. Failure leaves the entry out of good standing (routable to escalate); re-provisioning later = nonce bump (cache miss by construction, same memoization as attestation).

**What the predicate does per protocol** (mirroring cvm-mcp's `provision()`, the reference flow):

1. Resolve the id through the closure's `protocols` dict; gate on the session using `goldenbytes_appr` (so `gumbo_validation` → clean error Verdict-equivalent, not a crash).
2. Build the **measurement-only term**: vendor `_make_measurement_term` (APPR→NULL) and `_inject_asp_id_appr` + bookkeeping-key stripping from cvm-mcp — the repo's established vendoring pattern.
3. **Re-root every `filepath` arg to its `golden/` mirror** — provisioning measures the golden copies, never the live tree. Error up front listing any watched file missing from `golden/`.
4. Run it through the existing client unchanged.
5. Write the **golden evidence bundle** `[payload, global_context]` plus the golden-path `asp_args.json` (needed for slice matching) under `golden/_bundles/<protocol_id>/`.
6. Invoke asp-libs **`extract_golden_slice`** per `(asp_id, targ_id)` → fresh `golden_b64` + `golden_ts` → write back into the protocol's `asp_args.json` (live paths) and the in-memory `ProtocolDir`, **and invalidate `cvm_request.json`/`prebuilt_request`** (the l1 prebuilt bakes in old goldens — a real staleness trap).
7. Return a truthy `ProvisionOutcome` (protocol, provisioned target ids, bundle path) or a failing one with the error.

**Trust boundary, restated:** pybb's blackboard becomes a golden-state writer, but one that can *only* source from `golden/` — the "provision from live/failed state" laundering path stays structurally impossible; the human control point moves to who writes `golden/`.

**Tests:** unit (fake client + injectable extractor: APPR really stripped, paths golden-rooted, memoization, missing-golden error, `gumbo_validation` gate) and CVM integration (copy fixture dirs to tmp, provision from the real `golden/`, assert the freshly extracted `golden_b64` **equal the May-provisioned fixture values** — they must, since content is identical — then attest clean). Plus example + README, retiring the "provisioning is out of scope" section.

## Open decisions for you

1. **Client interface:** run the provisioning request via the `model_copy(update={"prebuilt_request": ...})` trick (zero interface change), or add an explicit `run_request(manifest, request)` to `AttestationClient` (more honest, touches the ABC and the test fake). I lean the trick for this PR, promote to a real method if a second caller appears.
2. **Disk writes to the protocol dir:** the predicate updating `tests/fixtures/gumbo_*/asp_args.json` in place makes provisioning durable but means a blackboard run mutates committed fixtures. Alternatives: write only in-memory (durability lost), or point the predicate at a *copy* of the protocol dirs. My lean: write-through to whatever protocol dir the `ProtocolDir` was loaded from — tests use tmp copies, and mutating fixtures is *correct* when you genuinely re-provision.
3. **Bundle location:** `golden/_bundles/<protocol_id>/` (my proposal) vs. inside each protocol dir like cvm-mcp does. Golden-side keeps all provisioning artifacts in one committed place; protocol-dir-side matches cvm-mcp convention.
4. **Scope boundary to confirm:** provisioning covers files *the protocol terms already name*. A genuinely new file appearing in `golden/` can't be measured until some term/`asp_args` references it — term generation (cvm-mcp's `hamr_report_protocols.py` territory) stays out of scope for this step.
5. **Deferred as agreed:** wiring provision-success to attestation nonce bumps (re-attest after re-provisioning) — next conversation.

Anything you'd change before I start?

## User

I'd like to walk through the full workflow, to make sure the design for predicates, knowledge sources, and blackboard partitions is sound and clean.  Let's start from the beginning.  How does a provisioning predicate show up on the blackboard, and what happens all the way through attestation and appraisal?

## Assistant

Let me walk the whole thing end to end, cycle by cycle, using the controller's actual mechanics — and I'll flag the two places where the design has real friction, because the walkthrough exposes them.

## Stage 0: Standing state (before any event)

The workflow session sets up one controller with **two named predicates** and the **shared** `protocols` dict — shared is load-bearing: both predicates capture the *same* `ProtocolDir` objects, which is how provisioning's effects become visible to attestation without any reload.

```python
protocols = {pid: ProtocolDir.load(...) for pid in ("gumbo_l1", "gumbo_l2", "gumbo_validation")}
controller.register_predicate("provision",   make_provision_predicate(client, protocols, GOLDEN_ROOT))
controller.register_predicate("attestation", make_attestation_predicate(client, protocols))
```

The blackboard is empty. Both KS partitions and both board segments (certify / escalate) are empty. Nothing runs — predicates only fire when an entry names them.

## Stage 1: The external event

Some out-of-band actor (a human, a release pipeline) does two things:

1. **Writes files into `golden/`** — new or updated clean copies.
2. **Writes a request entry** to the certify segment:

```python
bb.write_entry(key="provision:gumbo_l1", predicate="provision",
               measurement=provision_request("gumbo_l1"))       # {"protocol": "gumbo_l1", "nonce": 0}
controller.route("provision:gumbo_l1", on_fail=[])              # failures escalate, no repair chain
```

The entry now exists with `result=None`, `good_standing=False`, in **no KS's partition** (routes start keys unplaced — placement is earned by a verdict). Note the empty route registration: without it, a failed provisioning would just sit in certify forever with no KS able to contribute; with it, `_dispatch` sends first-failure straight to escalate. Design rule worth adopting: *every request entry gets a route, even an empty one*, so failure always has a destination.

## Stage 2: Cycle 1 — evaluation is where provisioning happens

`run()` begins. `_evaluate_all` walks entries in insertion order and calls `fn(entry.measurement)` for each.

For `provision:gumbo_l1`, that call **is** the provisioning (memoized, so at-most-once per descriptor):

1. Resolve `"gumbo_l1"` in the shared dict; confirm the session uses `goldenbytes_appr`.
2. Build the measurement-only term (APPR→NULL, `asp_id_appr` injected, bookkeeping stripped).
3. Re-root every `filepath` to its `golden/` mirror — **the CVM never reads the live tree during provisioning**. Missing golden copy → failing `ProvisionOutcome` immediately, nothing run.
4. `client.run_protocol(...)` — the CVM measures the golden copies; response payload = raw evidence + evidence-type tree.
5. Write `[payload, global_context]` as the bundle; run `extract_golden_slice` per target; write fresh `golden_b64`/`golden_ts` into the protocol's `asp_args.json` and the in-memory `ProtocolDir`; invalidate the stale prebuilt request.
6. Return truthy `ProvisionOutcome(protocol="gumbo_l1", provisioned=[...5 targets...], bundle=...)`.

The controller stores it: `good_standing=True`, and — because `result is not None` — **history records the provisioning act**. The audit trail showing *when goldens changed and from what* falls out of existing machinery for free.

`_dispatch`: entry passed, no `on_pass` chain → **pass is final**. The entry rests in certify as the durable record "these goldens were provisioned from golden/ at nonce 0." Every subsequent cycle re-evaluates it, hits the memo cache, and returns the same outcome instantly.

**Failure variant:** CVM error / extraction mismatch / missing golden file → falsy outcome → `_dispatch` finds an empty `on_fail` chain → the entry moves to the **escalate segment** carrying the `ProvisionOutcome` as the failure report. Symmetric with attestation escalation: escalate is where predicate-governed ends and human-governed begins. (And if you ever want automated remediation — retry against the previous bundle, say — it's a KS appended to that `on_fail` chain. The slot exists; nothing occupies it yet.)

## Stage 3: Attestation enters

Now the attestation workflow runs — the `"gumbo"` entry with `attestation_request("gumbo_l1")` and its route (`on_pass=[TierKS("gumbo_validation")]`, `on_fail=[TierKS("gumbo_l2")]`).

Evaluation: the `"attestation"` predicate resolves the same shared `ProtocolDir` — which now carries the **fresh goldens** and no stale prebuilt — builds the request dynamically, and runs the protocol **against the live tree** (live paths are exactly what `asp_args.json` holds). This is the pleasing symmetry the design lands on:

```
provision  =  measure golden/,  compare-target: (none — APPR stripped)
attest     =  measure live,     compare-target: what provisioning measured from golden/
```

## Stage 4: Appraisal, in detail

The CVM response comes back with `PAYLOAD = [{"RawEv": [...]}, evidence_tree]`. `parse_appraisal` walks the tree in DFS order; each appraiser node (`hashfile_appr`-shaped, i.e. `asp_id` containing `"appr"`) consumes the next RawEv item: base64 of `""` = pass, anything else = the failure reason. Each becomes a `ComponentResult`, matched back to a stable `targ_id` by comparing its ASP_ARGS against `protocol.target_records()` on `_MATCH_KEYS` (`filepath`, index ranges, markers) — note these keys are **invariant under re-provisioning** (only `golden_b64`/`golden_ts` changed), so target attribution is unaffected by fresh goldens. `overall_verdict` ANDs the components; the `Verdict` (tagged with the protocol id that produced it) becomes the entry's result; `good_standing = bool(verdict)`.

From here the tier walk is the established machinery: pass → dispatch to `on_pass`, standing cleared, `TierKS("gumbo_validation")` gets `"gumbo"` in its partition, rewrites the measurement's protocol id, next cycle attests semantically. Fail → `on_fail`, l2 attributes per contract. Chain exhaustion → escalate with the failing tier's Verdict. `trust_summary` narrates.

## The two frictions the walkthrough exposes

**1. Ordering between provisioning and attestation in the *same* run.** `_evaluate_all` uses insertion order. If the provision entry is written before the attestation entry, cycle 1 provisions first and attestation sees fresh goldens — correct, but *implicitly* so. If attestation evaluates first (or was already cached from an earlier cycle at the same nonce), it holds a verdict rendered against **old goldens**, and provisioning afterward changes nothing until the attestation nonce bumps. The blackboard has no inter-entry dependency primitive, and I'd argue it shouldn't grow one for this. Two clean resolutions, not mutually exclusive: (a) **sequence episodes** — the external event's run provisions; the attestation workflow is a separate `run()` (fits your "new runs of the workflow" framing); (b) the deferred **nonce wiring** — and the walkthrough reveals its natural home: a tiny KS on the provision entry's `on_pass` chain whose whole job is bumping the attestation entry's nonce. "Provisioning confirmed → force re-attestation" expressed in existing route vocabulary, no new machinery.

**2. Predicates are now effectful writers.** The attestation predicate's side effect (running a protocol) is observational; the provision predicate *writes durable state* (bundle, asp_args, ProtocolDir mutation). The idiom holds — "the predicate IS the X", memoization gives at-most-once-per-descriptor — but it means predicate evaluation order *within a cycle* is state-mutation order, which is exactly what friction #1 is. I think that's an acceptable, honest trade for the simplicity you asked for ("provisioning should be simpler on the blackboard"), provided we document that provision entries should be run to quiescence before attestation entries are written in the same session.

**Partition summary, one line each:** certify holds both request kinds as living records; escalate receives either kind's terminal failures with typed reports; KS partitions stay empty except when a verdict places a key (tier hops for attestation; nothing today for provisioning, with clean slots for a retry KS and the nonce-bump KS later).

That's the whole arc. If the two-episode sequencing + future nonce-bump KS resolution for friction #1 sounds right to you, the plan stands as reviewed and I can start building.

## User

I'd like to explore adding a provisioning partition.  This partition will only hold requests for provisioning, following an external event that adds new files to the golden directory.  Let's plan this change first.

## Assistant

Good instinct — and the walkthrough already showed why: a dedicated partition gives provisioning requests **structural precedence** instead of relying on entry insertion order. Here's the plan for review.

## What the partition means

The blackboard grows from two segments to three, each with a distinct governance role:

| segment | holds | governed by |
|---|---|---|
| **provision** (new) | requests to (re-)provision golden evidence, written by the external event | the `"provision"` predicate only — no KSs, no routes |
| **certify** (existing `entries`) | trust questions under active judgment (attestation entries) | predicates + routed KS chains |
| **escalate** (existing) | terminal failures of either kind, with typed reports | humans |

A provision request's lifecycle is deliberately simpler than a certify entry's: evaluated → either **good standing** (stays in the partition as the durable record of current provisioned state, memoized thereafter) or **failed** → moved straight to escalate carrying its `ProvisionOutcome`. No chains, no dispatch, no `TierKS`-style hops. If we later want a retry KS or the nonce-bump KS, that's the moment to extend dispatch to this partition — not now.

## The semantic payoff: evaluation precedence

The controller's cycle becomes:

```
1. evaluate provision partition     <- provisioning happens FIRST, structurally
2. evaluate certify entries         <- attestation sees fresh goldens, guaranteed
3. dispatch / advance / run KSs     <- unchanged, certify-only
```

This eliminates friction #1's fragile half: within any run, attestation can never evaluate ahead of a pending provision request. (The other half — *re*-provisioning invalidating an already-cached attestation verdict — remains the deferred nonce wiring, unchanged by this design.)

## Concrete changes

1. **`blackboard.py`**: add `provision: dict[str, BlackboardEntry]`; teach `write_entry(partition="provision")` and add `get_provision()`; history stays shared (provisioning acts land in the same audit trail — that's a feature). Small refactor so entry updates route to the owning segment.
2. **`controller.py`**: `_evaluate_all` evaluates the provision segment before certify; new small step moves evaluated-and-failing provision entries to escalate (with the usual cycle log line). KS machinery (`_dispatch`, `_advance`, `can_contribute`) stays certify-only — enforced, not incidental.
3. **`pybb/attestation/provision.py`**: the predicate exactly as planned last turn (measurement-only term from cvm-mcp's flow, golden-rooted paths, bundle + `extract_golden_slice`, write-back, prebuilt invalidation) — unchanged by the partition; plus a `request_provision(blackboard, protocol_id, nonce=0)` helper that writes into the new partition, which is the API the external event calls.
4. **Example**: external-event demo — drop/refresh files in `golden/`, `request_provision(...)`, run; show the provision record, then a clean attestation episode against the fresh goldens.
5. **Tests**: blackboard-level (segment writes, `get_provision`, history tagging), controller-level (precedence — a provision predicate that records evaluation order proves it ran before certify; failure → escalate), plus the provision-predicate unit/integration tests from the standing plan.
6. **README**: three-segment board diagram; retire "provisioning is out of scope" for "provisioning is a first-class partition, sourced only from `golden/`".

## Two decisions for you

1. **Specific vs. generic:** I've scoped this as a dedicated `provision` segment (your words: "only hold requests for provisioning"). The alternative — generic named partitions with per-partition evaluation order — is more machinery than the current need justifies; I'd build the specific one and generalize only if a third segment kind ever appears. Confirm?
2. **Fulfilled requests stay put:** a succeeded request remains in the provision partition in good standing as the living record ("these goldens, this nonce"), rather than being removed. Re-provisioning = same key, bumped nonce. That mirrors how certify keeps passing entries. Confirm?

If both confirmations are yes, I'll start with the blackboard/controller change (small, self-contained, testable without any CVM), then layer the predicate work from the standing plan on top.

## User

Yes to both, proceed with the plan.

## Assistant

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/client.py

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/summary.py

`ProtocolDir` is a mutable model and `trust_summary` filters on `Verdict`, so the pieces fit. Starting with the blackboard partition:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/blackboard.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/blackboard.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/blackboard.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/controller.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/controller.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/controller.py

Now factor out the path-mirroring helper in `snapshot.py` so provisioning can reuse it:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/snapshot.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/snapshot.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/snapshot.py

> `[Bash]` Check copland term utility signatures

> `[Write]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/provision.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

Now the tests — partition mechanics first, then the predicate unit tests:

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/test_provision_partition.py

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/test_provision.py

> `[Bash]` Run new partition and provision predicate tests

> `[Bash]` Run full non-CVM suite for regressions

All 46 unit tests pass. Now the end-to-end integration test against the real CVM and extractor:

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_provision.py

> `[Bash]` Run provisioning integration test against real CVM

> `[Bash]` Check top-level README for partition documentation

> `[Read]` /Users/adampetz/Claude_workspace/pybb/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/README.md

Now the attestation README — replace the "out of scope" section and update the table/modules:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Write]` /Users/adampetz/Claude_workspace/pybb/examples/provision_workflow.py

> `[Bash]` Run clean provision workflow demo

> `[Bash]` Run gold-moved-ahead-of-live demo

> `[Bash]` Run full test suite including CVM integration

> `[Bash]` Commit provision partition work and push to origin

Committed as `bd62c3b` and pushed. Updating project memory with the new state:

> `[Edit]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

Done — the provision partition and provisioning predicate are built, tested, committed (`bd62c3b`), and pushed to `origin/dev`.

## What landed

**Core blackboard** ([blackboard.py](pybb/pybb/blackboard.py), [controller.py](pybb/pybb/controller.py)):
- Third segment `provision` alongside certify/escalate; `write_entry(partition="provision")`, `get_provision()`, shared history.
- The controller evaluates the provision partition **before** certify every cycle — the ordering guarantee is now structural, not insertion-order luck. Failing requests escalate immediately (no KS chains); fulfilled ones remain as the durable record. KS machinery verifiably never touches the partition.

**Provisioning predicate** ([provision.py](pybb/pybb/attestation/provision.py)):
- `request_provision(blackboard, protocol_id, nonce)` — the external-event API.
- `make_provision_predicate(client, protocols, golden_root)` — runs the measurement-only term (APPR stripped, vendored from cvm-mcp's flow) against the **golden copies**, writes the bundle to `golden/_bundles/<pid>/`, extracts slices via asp-libs' `extract_golden_slice`, installs fresh goldens into the shared `ProtocolDir` and the protocol dir on disk, and kills the stale prebuilt request. Memoized; nonce bump re-provisions.

**Verification** — 49 passed, 2 skipped (the gated multi-minute Sireum runs):
- 12 new unit tests (partition mechanics incl. evaluation-order proof; predicate term shaping, golden-rooting, error paths, memoization).
- The integration test proves the round trip: goldens re-provisioned from `golden/` are **byte-identical to the committed May fixture values**, and attestation of the live tree passes against them in the same controller run.
- [provision_workflow.py](pybb/examples/provision_workflow.py): clean mode provisions 4+28 targets and attests clean in 1 cycle; `--tamper-golden` demonstrates the new scenario this architecture unlocks — *gold moves ahead of live*: provisioning succeeds (gold is the authority), attestation then fails, l2 attributes the drift to exactly `tc_sys_aadl_305_308_targ`, and the entry escalates.

Both READMEs now document the three-segment board, and the old "provisioning is out of scope" section is replaced by the new trust story: golden values derive only from `golden/`, and only deliberate out-of-band acts write `golden/`.

Still deferred, as agreed: the provision-success → attestation nonce-bump wiring (its natural home is a small KS on the provision entry's `on_pass` chain) — that's the piece that makes *re*-provisioning mid-session force re-attestation.

## User

Let's hold off on the nonce bump for now.  I'd like to revisit how the on-pass on-fail semantics works, let's walk through that for the temp-control example.

## Assistant

Deferring the nonce bump — noted. Here's the on_pass/on_fail walkthrough for temp-control, traced against what the controller actually does, followed by the semantic fine print the trace exposes.

## The route, restated

```python
controller.route("gumbo",
    on_pass=[TierKS(protocol_id="gumbo_validation")],   # only with --validate
    on_fail=[TierKS(protocol_id="gumbo_l2")])
```

Registration does three things (controller.py:57): stores a `Route` with the two chains, clears any previous dispatch for the key, and scrubs `"gumbo"` from every chain KS's partition — all placement must be earned by a verdict. From here, everything hinges on one rule: **dispatch happens once per key, on the first verdict, and the chosen chain is fixed forever.**

## Scenario A: clean run, `--validate` (the on_pass branch)

**Cycle 1** — `_evaluate_all` runs the attestation predicate: l1 passes. `_dispatch` sees `good_standing=True` *and* a non-empty `on_pass` chain, so:

- Standing is **cleared back to False** (controller.py:85) — this is the entire meaning of "provisional": the entry holds a passing l1 Verdict yet is deliberately not in good standing.
- `"gumbo"` is appended to the validation `TierKS`'s partition; `dispatched["gumbo"] = on_pass`.
- KS phase: the validation rung `can_contribute` (standing is False), logs an attempt in `ks_history`, and rewrites the measurement to `{"protocol": "gumbo_validation", ...}` with `result=None`.

**Cycle 2** — re-evaluation runs the Sireum tools (minutes). Pass → `good_standing=True`. `_dispatch` skips (already dispatched). No KS can contribute → halt. Final state: entry rests in certify holding the *validation* Verdict; `trust_summary` reads the history trail → "gumbo_l1 passed; **confirmed by** gumbo_validation".

**Cycle 2, failure variant** — validation fails. The validation KS still owns the key, but `max_attempts=1` is exhausted, so `_advance` fires: no next KS in the on_pass chain → the entry moves to **escalate carrying the validation Verdict** and `ks_history={"tier:gumbo_validation": 1}`. Summary: "l1 passed **but confirmation failed**". Note what does *not* happen: l2 never runs — the on_fail chain became unreachable the moment dispatch chose on_pass. (Semantically right here: the hashes were intact, so per-contract hash attribution has nothing to add to a semantic failure.)

## Scenario B: clean run, no `--validate`

Cycle 1: l1 passes, `on_pass` is empty → `_dispatch` hits `continue`: **pass is final**, and — subtle — the key is *never marked dispatched*. Halt in one cycle. "All attested components intact."

## Scenario C: `--tamper` (the on_fail branch)

This is the exact trace from our runs:

```
Cycle 1: 'gumbo' failed - dispatching to on_fail chain      <- first verdict picks the branch
Cycle 1: running 'tier:gumbo_l2'                            <- rewrite measurement to gumbo_l2
Cycle 2: running 'tier:gumbo_l2'                            <- l2 verdict is in and failing...
Cycle 2: no eligible KS left for 'gumbo' - escalating       <- attempts exhausted, chain empty
Cycle 3: all entries in good standing - halting
```

Cycle 1: l1 fails → dispatch to `on_fail`, l2 rung gets the key, rewrites the measurement. Cycle 2: evaluation attests l2 (the 28 slices) — fails on `tc_sys_aadl_305_308_targ`; the rung has burned its one attempt, `_advance` finds no successor → escalate with the **l2 Verdict** (the fine-grained attribution) as the report. Had l2 *passed* (tamper outside every measured range), cycle 2 would simply end in good standing: "l2 passed after l1 failed — attested clean at finer granularity."

## The five end states

| first verdict | chain outcome | resting place | summary |
|---|---|---|---|
| l1 pass, no on_pass | — | certify | intact |
| l1 pass | validation pass | certify | intact, confirmed |
| l1 pass | validation fail | **escalate** (validation report) | passed but confirmation failed |
| l1 fail | l2 pass | certify | clean at finer granularity |
| l1 fail | l2 fail | **escalate** (l2 attribution) | ladder exhausted |

## The fine print the walkthrough surfaces

1. **The decision tree is depth-2.** The *first* verdict chooses a branch; after that the chosen chain is a linear ladder where each subsequent pass ends the episode and each failure advances. There is no re-branching — an l2 pass can't be routed onward to validation, and a validation failure can't fall back to l2. For temp-control that's semantically fine (see above), but it's a real expressiveness boundary if you ever want, say, "l2 clean → *then* confirm semantically." That would need either nested routes or chain composition — worth keeping in mind as a possible next design conversation.

2. **Multi-rung failure handoff restores the original measurement** (controller.py:114): if a chain were `[ksA, ksB]`, ksB starts from the entry's *original* l1 request, not ksA's rewrite. For `TierKS` rungs this is invisible (each rung overwrites the protocol id anyway), but any future KS that *accumulates* measurement state would need to know its predecessor's work gets rolled back on handoff.

3. **Asymmetry between "pass-final" and "dispatched":** with an empty `on_pass`, a passing entry stays *undispatched* — so if its measurement later changed (e.g. a future nonce bump) and it re-evaluated as failing, it could still dispatch to `on_fail` at that point. But once dispatched to either chain, that choice is permanent for the entry's lifetime. Today nothing re-fails a passing entry mid-run, so this is latent — it becomes live the moment we do the nonce-bump work, which is exactly when we should decide whether "re-attestation after re-provisioning" should reset the route (probably yes: fresh episode, fresh dispatch).

4. **`max_attempts=1` is doing quiet work:** a tier rung's "attempt" is one measurement rewrite; the *evaluation* happens on the controller's next cycle. The exhaustion check (`ks_history >= max_attempts` while the entry still fails) is what converts "my tier's verdict came back failing" into advancement/escalation. A rung with `max_attempts=2` would pointlessly re-write the same measurement (memoized predicate → same verdict), so 1 is the only sensible value for `TierKS` — that's an invariant worth a comment eventually, not a knob.

And to place the new partition in this picture: provision entries opt out of all of it — no routes, no dispatch, no chains. Their entire lifecycle is evaluate → rest-or-escalate, which is precisely why the partition stays simple.

Where would you like to push on this — the depth-2 boundary, the dispatch-reset question, or something else the walkthrough raised?

## User

I'm confused by the notion of "dispatch".  How does that work and who sets that flag?

## Assistant

"Dispatch" is entirely a **controller-internal bookkeeping step** — no flag lives on the entry or the blackboard at all. Let me pin down exactly what it is, where the state lives, and who writes it.

## The state: one dict on the controller

```python
class BlackboardController(BaseModel):
    routes:     dict[str, Route] = {}                    # key -> the two chains you registered
    dispatched: dict[str, list[KnowledgeSource]] = {}    # key -> the ONE chain actually chosen
```

`routes` is what *you* declare up front ("if gumbo fails, try these; if it passes, confirm with those"). `dispatched` is what the *controller* decides once evidence exists — "for this key, the chosen chain is this list." The presence of a key in `dispatched` is the "flag" you're asking about. It's controller memory about the episode, not blackboard content: entries never know they've been dispatched, and it doesn't survive into history or escalate records (except indirectly via `ks_history`).

## Who sets it: `_dispatch()`, once per key

The controller's cycle is `evaluate → escalate-failed-provision → _dispatch → _advance_ready → run KSs`. Each cycle, `_dispatch` (controller.py:72) scans every certify entry and applies this logic:

```python
route = self.routes.get(key)
if route is None or key in self.dispatched or entry.result is None:
    continue                                  # <- the three reasons to do nothing
```

So a key is only ever considered for dispatch when **all three** hold: it has a registered route, it has **not** been dispatched before, and it has a first verdict (`result` is no longer `None`). Then:

- **Failing entry** → `chain = route.on_fail`, and `self.dispatched[key] = chain`.
- **Passing entry with a non-empty `on_pass`** → standing cleared (the "provisional pass"), `chain = route.on_pass`, `self.dispatched[key] = chain`.
- **Passing entry with empty `on_pass`** → `continue` — pass is final and, notably, the key is *never* entered into `dispatched`.

Immediately after recording the choice, the controller does the one thing that connects dispatch to the KS world: `chain[0].partition.append(key)` — the first KS of the chosen chain becomes responsible for the key. (If the chosen chain is empty, the entry escalates on the spot instead: "nothing can help.")

## Who reads it: `_advance()`

When a KS exhausts its attempts on a still-failing key, `_advance` (controller.py:97) looks up `self.dispatched[key]` to find *which* chain this episode is walking, locates the current KS in that list by name, and hands the key to the next element — or escalates if there isn't one. This is why the not-chosen chain is unreachable forever: advancement only ever walks the list stored at dispatch time.

## Who clears it: `route()` — and nothing else

```python
def route(self, key, ...):
    self.routes[key] = route
    self.dispatched.pop(key, None)        # re-routing resets the episode
```

Re-registering a route for a key is the *only* thing that erases the dispatch decision (it also scrubs the key out of the chain KSs' partitions). Nothing in evaluation, advancement, or escalation ever un-dispatches. That's the source of the "dispatch is permanent for the entry's lifetime" behavior from the walkthrough — permanence isn't a deep principle, it's just that no code path pops the dict entry mid-run.

## Why it exists at all

Without `dispatched`, `_dispatch` would re-fire every cycle: a provisionally-passing entry (standing deliberately cleared) would look "failing" on cycle 2 and get shoved onto `on_fail` — the confirmation semantics would collapse. The once-only latch is what makes "the *first* verdict chooses the branch" true, and it's also what makes the pass provisional rather than paradoxical: the controller can zero out `good_standing` while remembering, in its own state, that this key is mid-confirmation rather than freshly failed.

**One-line mental model:** `routes` = the decision tree you declared; `dispatched` = the controller's one-shot record of which edge the first verdict took; set in `_dispatch`, consumed by `_advance`, reset only by re-calling `route()`. If we later want "fresh episode after re-provisioning," the clean lever already exists — re-route (or a small `reset_dispatch(key)`) rather than any new mechanism.

## User

Let's look at routes again and explain whether or not they can mention protocols

## Assistant

Short answer: **routes cannot mention protocols directly — but they do so indirectly, through the KSs they contain.** The layering is worth making exact, because it's clean and easy to misread.

## What a Route literally holds

```python
class Route(BaseModel):
    on_pass: list[KnowledgeSource] = []
    on_fail: list[KnowledgeSource] = []
```

That's the whole type (controller.py:8). A route is two ordered lists of **knowledge-source objects** — nothing else. There is no protocol field, no measurement, no predicate name anywhere in it. And the controller code that consumes routes (`_dispatch`, `_advance`) touches only three things on those KSs: `partition`, `name`, and `max_attempts`. The words "protocol," "attestation," "Verdict" appear nowhere in `controller.py` — the routing machinery is fully domain-agnostic and would work identically for the `NumberAdder` toy examples.

## Where protocols sneak in: KS configuration

The attestation layer's `TierKS` happens to *carry* a protocol id as its configuration:

```python
controller.route("gumbo",
    on_pass=[TierKS(protocol_id="gumbo_validation")],
    on_fail=[TierKS(protocol_id="gumbo_l2")])
```

So when you read this route as "the decision tree over protocols," that's true *semantically* but achieved entirely by parameterization: each rung is a generic KS whose one behavior — rewrite the entry's measurement to `{"protocol": <my id>, ...}` — is instantiated with a specific protocol name. The route mentions protocols the same way a phone book mentions people: it holds objects that carry names, without the book itself understanding names.

The full division of knowledge:

| layer | knows about protocols? | how |
|---|---|---|
| `Route` / `dispatched` / `_dispatch` / `_advance` | **no** | operate on opaque KS lists |
| `TierKS` | holds one id | writes it into the measurement; never validates or runs it |
| measurement | carries the id | `{"protocol": ..., "nonce": ...}` |
| `"attestation"` predicate | **resolves** the id | closure's `protocols` dict → `ProtocolDir` → CVM |

## The consequence: route↔protocol consistency is unchecked

Because the route layer can't see protocols, nothing at `route()` time verifies that a rung's `protocol_id` exists in the predicate's closure. `TierKS(protocol_id="gumbo_l3_typo")` registers happily; the mistake surfaces only at runtime, as data flowing through the normal machinery: the rung rewrites the measurement, the next evaluation returns `Verdict(error="unknown protocol 'gumbo_l3_typo'", passed=False)`, and the entry advances down the chain or escalates carrying that verdict. Graceful — nothing crashes, the audit trail shows exactly what happened — but the failure is *late* and looks like an attestation failure rather than a configuration error.

If that ever bites, the fix wouldn't be teaching routes about protocols (that would smear the layering); it would be a validation pass at setup time in the attestation layer — e.g. a helper that walks a route's rungs and checks each `protocol_id` against the `protocols` dict before `run()`. Cheap, optional, and keeps the controller domain-blind.

## Why the blindness is the feature

This is the same separation we mapped for predicates-vs-partitions: the controller owns *coordination* (when to evaluate, whom to hand a key, when to give up), the domain layer owns *meaning* (what a protocol is, what a verdict says). It's why the provision partition slotted in without touching routes at all, and why a future rung type — a repair KS, a nonce-bump KS — joins a chain with zero controller changes: anything satisfying the `KnowledgeSource` interface is routable, and whatever domain knowledge it needs rides along as its own configuration, exactly as `protocol_id` does on `TierKS`.

## User

Where does the l1 protocol show up?

## Assistant

Notably, **not in the route** — and that asymmetry is the interesting part of the answer. `gumbo_l1` appears in exactly these places:

## 1. The entry's initial measurement — the starting tier

```python
controller.blackboard.write_entry(
    key="gumbo", predicate="attestation",
    measurement=attestation_request("gumbo_l1"),   # <- here
)
controller.route("gumbo",
    on_pass=[TierKS(protocol_id="gumbo_validation")],
    on_fail=[TierKS(protocol_id="gumbo_l2")])
```

The route names only the **reactive** tiers — where to go *after* a verdict exists. The **first** tier is seeded by whoever writes the entry, as the initial measurement. So the complete decision tree is split across two declarations: the entry says "start at l1," the route says "on l1's pass go to validation, on l1's fail go to l2." Neither piece alone shows the whole tree — something to keep in mind when reading a setup, and arguably a small legibility cost of the current design (the tree's root and its branches live in different statements).

## 2. `original_measurement` — the preserved root

When the entry is written, `write_entry` stashes the l1 request as `original_measurement` (blackboard.py:45). This is what `_advance` restores on failure handoff between rungs — so in a hypothetical multi-rung chain, each successor starts from "the l1 request" rather than its predecessor's rewrite. The l1 descriptor thus persists as the entry's reference point for its whole lifetime, even after `TierKS` rungs have overwritten the live measurement with l2's or validation's id.

## 3. The predicate's closure — resolution and cache

`protocols = {"gumbo_l1": ProtocolDir.load(...), ...}` maps the id to the loaded fixture directory ([tests/fixtures/gumbo_l1](pybb/tests/fixtures/gumbo_l1), with its term/session/manifest/asp_args). And after cycle 1, the memo cache holds a row keyed by `'{"nonce": 0, "protocol": "gumbo_l1"}'` — the l1 verdict stays cached even while the entry's live measurement has moved on to another tier.

## 4. The audit trail — as the verdict's tag

After a tier hop, the *entry* no longer mentions l1, but history does: the first recorded state carries `Verdict(protocol="gumbo_l1", ...)`. That tag is how `trust_summary` reconstructs the trail ("gumbo_l1 passed; confirmed by gumbo_validation") — the durable record of l1's participation is the Verdict it produced, not any field on the entry or route.

## 5. The provisioning side (new, parallel)

Same id, different partition: `request_provision(bb, "gumbo_l1")` puts it in the provision request's measurement (key `provision:gumbo_l1`), and its bundle lands at `golden/_bundles/gumbo_l1/`.

**The takeaway shape:** l1 enters as *data* (the seed measurement), gets resolved through the predicate's closure, and survives as *history* (the tagged Verdict, the memo row, `original_measurement`). The route never needs to know it exists — which is consistent with the layering from last turn, but does mean "which protocol does this entry start at?" is answered by looking at `write_entry` calls, not at the route table.

## User

How might we re-design to include the l1 protocol in a route explicitly?

## Assistant

There are two honest ways to do it, at different layers. Let me lay both out, because choosing between them is really choosing *what kind of thing a route is*.

## Option 1: A domain-layer "tree declaration" helper (small, no core changes)

Keep the controller's `Route` exactly as it is, and add an attestation-layer function that owns the *entire* episode declaration — root included:

```python
def attestation_route(controller, key, start, on_pass=(), on_fail=(), protocols=None):
    """Declare one attestation entry's full decision tree: the starting
    protocol and the outcome chains, validated against the protocol map."""
    if protocols is not None:
        unknown = [p for p in (start, *on_pass, *on_fail) if p not in protocols]
        if unknown:
            raise ValueError(f"route names unknown protocols: {unknown}")
    pass_rungs = [TierKS(protocol_id=p) for p in on_pass]
    fail_rungs = [TierKS(protocol_id=p) for p in on_fail]
    for ks in (*pass_rungs, *fail_rungs):
        controller.add_ks(ks)
    controller.blackboard.write_entry(
        key=key, predicate="attestation", measurement=attestation_request(start))
    controller.route(key, on_pass=pass_rungs, on_fail=fail_rungs)
```

The example collapses to one legible statement showing the whole tree:

```python
attestation_route(controller, "gumbo",
    start="gumbo_l1",
    on_pass=["gumbo_validation"],
    on_fail=["gumbo_l2"],
    protocols=protocols)
```

What this buys beyond legibility: it's the natural home for the **declaration-time validation** we flagged as missing (a typo'd protocol id fails at setup with a `ValueError`, not at runtime disguised as an attestation failure), and later it's the natural home for "restart episode" when the nonce-bump work needs to reset dispatch. What it *doesn't* do: the controller's `Route` still doesn't contain the root — the helper is sugar that co-locates the two declarations.

## Option 2: Give `Route` a first-class start chain (core generalization)

Make the tree genuinely live in the route: `Route(on_start=[...], on_pass=[...], on_fail=[...])`, where `on_start` is an ordinary KS (a `TierKS("gumbo_l1")`) that the controller runs **once, before the entry's first evaluation**, to seed the measurement. The entry would be written bare (`measurement=None` or just a nonce), and the route would own root and branches symmetrically — still domain-blind, since the root is "a KS that writes the first measurement," not a protocol id.

This is the principled version, but the walkthrough mechanics show its real costs:

- The controller needs a **new phase and a new latch**: a "started" record parallel to `dispatched`, consulted before evaluation, so the seed runs exactly once and *before* the predicate ever sees the bare measurement (otherwise cycle 1 evaluates `{"nonce": 0}` → "unknown protocol ''" → wrongly dispatches to `on_fail`).
- **`original_measurement` semantics break subtly**: today it's captured at `write_entry` time, and `_advance` restores it on handoff. With KS-seeding, the captured original would be the *unseeded* measurement — restoring it mid-chain would hand the next rung a protocol-less request. Fixable (capture after seeding), but it's real surgery on invariants that currently hold trivially.
- Every existing caller and test that writes a seeded entry keeps working, but now there are **two blessed ways to start an entry**, which is its own confusion tax.

## My recommendation

**Option 1 now.** It delivers everything you actually asked for — the l1 protocol visible in the route declaration, plus the validation gap closed — at the cost of ~15 lines in the attestation layer and zero risk to controller invariants. Option 2 is the right shape *if* a second domain ever needs seeded starts (that's the test: when "the route owns the root" pays rent outside attestation, generalize; until then it's speculative machinery). This also matches how the codebase has consistently evolved: coordination stays minimal and blind, meaning accretes in the domain layer.

Want me to implement Option 1 (helper + validation + switch the example/tests/README to it)?

## User

As an alternative, let's consider making the "gumbo" first event be a protocol validation step.  This checks to make sure the attestation protocol exists and can run (defer more detailed checks of this for later, perhaps using cvm tools).   Then the route could use something like:  "on-pass": [L1, L3], "on-fail": [escalate].  Still tricky is how to get to L2 using this strategy.  Consider this.

## Assistant

This proposal is worth taking seriously — it fixes a real gap (config errors currently masquerade as attestation failures) — but walking it through the controller's actual semantics exposes a mismatch between what the route *looks like* it says and what it would do. Let me trace it honestly, then lay out the ways to resolve the L2 problem.

## First: what `on_pass=[L1, L3]` actually does

The intuition behind `on_pass=[L1, L3]` is "check passes → run L1, then L3." But chains aren't sequences of stages — they're **repair ladders**. Advancement from L1's rung to L3's rung happens only via *failure handoff* (`_advance` fires when a rung's attempts are exhausted and the entry still fails). A **pass anywhere in a chain ends the episode**. So the proposed route actually executes as:

```
protocol-check pass ──> L1 attests
                          ├─ L1 pass ──> DONE  (L3 never runs — no confirmation!)
                          └─ L1 fail ──> L3 attests (semantic check as fallback)
                                           ├─ pass ──> done ("modified yet still verifies")
                                           └─ fail ──> escalate
protocol-check fail ──> escalate immediately (empty on_fail — your "[escalate]" is
                        literally the empty chain today)
```

Interesting historical note: that fail-branch shape — L1 fails, then ask "does the system still semantically verify?" — is exactly the old three-tier *ladder* from the `attestation-integration` branch. So the proposal is coherent, but it silently trades away **confirmation-on-pass** (L3 as skeptical double-check of a clean L1) and, as you spotted, has no home for L2 at all. The root cause is the invariant we established two turns ago: **one entry gets one dispatch — one branch point** — and this design spends it on the protocol-check verdict instead of L1's.

## The L2 problem, and three ways out

**Resolution A — two entries, chained (my recommendation if you want the check as a blackboard event).** Give the readiness check its own entry, and let its `on_pass` chain contain a small KS whose job is to *write the attestation entry*:

```python
controller.route("gumbo", on_pass=[TierKS("gumbo_validation")],
                          on_fail=[TierKS("gumbo_l2")])          # pre-registered; entry doesn't exist yet — legal
controller.route("gumbo:ready", on_pass=[StartAttestationKS(key="gumbo", start="gumbo_l1")],
                                on_fail=[])                      # check failure escalates as CONFIG failure
bb.write_entry(key="gumbo:ready", predicate="protocol_check",
               measurement={"protocols": ["gumbo_l1", "gumbo_l2", "gumbo_validation"]})
```

Cycle 1: the check validates *every* protocol the episode could touch (ids resolve, protocol dirs complete, CVM/ASP binaries present — deferring the deeper CVM-tools checks as you said). Pass → provisional → `StartAttestationKS` writes the `gumbo` entry seeded at L1 → next cycle the check re-passes and rests, while `gumbo` begins its own episode with the **full existing tree intact**: L1 pass → L3 confirmation, L1 fail → L2 attribution. Check failure → escalate carrying a readiness report that's unmistakably "configuration", not "integrity". Each branch point gets its own entry; deeper trees = chains of entries, which is idiomatic blackboard style (knowledge sources posting new problems). Mechanically everything needed already exists — routes can be registered before their entry exists, and the starter KS needs only blackboard access. Cost: two keys per trust question (`trust_summary` should learn the linkage), one new ~10-line KS class.

**Resolution B — accept the ladder.** Keep your single entry and embrace what the chain semantics give: `on_pass=[L1, L2, L3]` — check pass → L1; L1 fail → L2 (attribution); L2 fail → L3 (semantic fallback); any pass ends. L2 is back, in pure ladder form. What you lose is confirmation-on-pass (`--validate`'s current meaning): L3 runs only after failures, never to double-check a clean pass. If confirmation matters less than you thought when we built it, this is the simplest coherent design — but it's a semantic downgrade, not a refactor.

**Resolution C — verdict-routed state machine (the real generalization).** The deep issue is that `on_pass`/`on_fail` route the *first verdict only*. The full generalization routes *every* verdict: a transition table per entry, `{("check", pass): [L1], ("l1", pass): [L3], ("l1", fail): [L2], ...}`, with the dispatch latch replaced by current-state tracking. Maximum expressiveness — the decision tree becomes an explicit state machine, and your proposal plus L2 falls out trivially — but it's a redesign of the controller's core loop and retires the pleasingly simple "first verdict picks the branch" story. I'd hold this in reserve until a *third* scenario strains the current model; two entries (A) covers the current need compositionally.

**Also worth naming — the zero-machinery variant:** fold the readiness check into the attestation predicate itself (`_attest` already returns an `unknown protocol` verdict; extending it to "protocol dir complete, binaries present" is ~10 lines). You lose the blackboard-visible event and the config/integrity distinction in escalation — which I take to be the point of your proposal — but it's the honest baseline to compare against.

## My take

The proposal's core idea — **readiness as an explicit, auditable first verdict, with config failures escalating as config failures** — is good, and Resolution A delivers it without sacrificing the L1 branch point: the check entry spends *its* dispatch on readiness, the attestation entry spends *its* dispatch on L1, and the existing tree survives untouched. B is simpler but changes what L3 means; C is the right future if trees keep deepening.

Want me to draft the concrete plan for Resolution A (the `protocol_check` predicate, `StartAttestationKS`, summary linkage, tests), or explore B or C further first?

## User

Let's plan Resolution A

## Assistant

Here's the concrete plan for Resolution A.

## New pieces

**1. `pybb/attestation/readiness.py`** — the protocol-check predicate, same idiom as the other two:

- `readiness_request(protocol_ids, nonce=0)` → `{"protocols": [...], "nonce": 0}` — one request covers **every** protocol the episode might touch (start + both chains), so a typo'd L2 surfaces up front, not mid-episode.
- `ReadinessReport` result model: `checked: [ids]`, `problems: [str]`; truthy iff no problems — `good_standing = bool(result)` as always.
- `make_readiness_predicate(protocols, config=None)` — memoized closure. Checks per id, deliberately shallow ("exists and can run"):
  - id resolves in the `protocols` dict;
  - protocol config is complete (term/session/manifest present);
  - every `goldenbytes_appr` target has a provisioned `golden_b64` (an unprovisioned protocol *runs* but can never appraise — that's a readiness fact);
  - CVM binary and ASP bin directory exist; each ASP named by the manifest has an executable.
  - **Deferred, documented:** deeper semantic checks via CVM tooling (dry-run/typecheck of the term) — the docstring names this as the extension point.

**2. `StartAttestationKS`** (in `knowledge_sources.py`, ~12 lines) — the linking rung: config `key`, `start` (protocol id), `nonce`. On execute, writes the attestation entry `write_entry(key=self.key, predicate="attestation", measurement=attestation_request(self.start, nonce))` — **idempotent** (skips if the key already exists, never clobbers a live episode). It writes nothing back to the readiness entry: the memoized check re-passes on the next cycle's evaluation and standing recovers by itself. `max_attempts=1`.

**3. Wiring pattern** (example + README become the reference):

```python
controller.route("gumbo", on_pass=[TierKS("gumbo_validation")],
                          on_fail=[TierKS("gumbo_l2")])           # pre-registered
controller.route("gumbo:ready",
                 on_pass=[StartAttestationKS(key="gumbo", start="gumbo_l1")],
                 on_fail=[])                                       # config failure -> escalate
bb.write_entry(key="gumbo:ready", predicate="protocol_check",
               measurement=readiness_request(["gumbo_l1", "gumbo_l2", "gumbo_validation"]))
```

Cycle trace: C1 evaluates readiness (pass → provisional → starter KS writes `gumbo` seeded at L1). C2: readiness re-passes and rests; `gumbo` attests L1 and dispatches on *its own* verdict — full existing tree preserved. Readiness failure → escalate with a report that is unmistakably **configuration**, before any attestation runs.

**4. `trust_summary`** — currently filters on `Verdict`, so an escalated readiness failure would be invisible. Add `ReadinessReport` handling: escalated → "protocol readiness failed — \<problems\>; attestation never started; user intervention required"; resting-in-good-standing → one quiet "protocols validated" line.

**5. Example** — `gumbo_attestation.py` switches to the readiness-first flow, plus a `--misconfigure` flag that adds a bogus protocol id to the checked set: demo shows readiness escalating as a config failure with the attestation entry never created (the new failure class this design exists to expose).

**6. Tests** — `tests/test_readiness.py`, no CVM needed:
- predicate: all-good passes (tmp-dir `CvmConfig` with fake binaries); unknown id / missing goldens / missing ASP executable each produce a named problem; memoization until nonce bump.
- flow (scripted attestation predicate): readiness pass → `gumbo` created seeded at start → L1 tree behaves as today; readiness fail → escalates, `gumbo` never exists; starter idempotency (pre-existing `gumbo` untouched).
- Existing tests unchanged — the direct `write_entry` + `route` style remains fully supported; readiness-first is a pattern on top, not a replacement.

**7. README** — new "Protocol readiness: the first verdict" section: the two-entry pattern, one-branch-point-per-entry rationale, config-vs-integrity escalation distinction, route pre-registration legality, and the deferred CVM-tools checks.

## Decisions embedded here (flag if you disagree)

- Readiness validates the **whole protocol set** in one request, not just L1.
- Goldens-provisioned counts as a readiness check (it's "can this protocol ever appraise", not a deep check).
- The starter KS is silent and idempotent; re-running an episode is a future concern (ties into the deferred nonce work).
- Verification: unit tests + both example modes against the real CVM (clean ~1s, `--misconfigure` instant).

Proceed?

## User

Yes, proceed.

## Assistant

> `[Bash]` Inspect manifest shape for ASP listing

> `[Write]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/readiness.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

Now the summary handling and exports:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/summary.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/summary.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

Now rewire the example to the readiness-first flow with `--misconfigure`:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

The example's history report needs to render readiness entries too:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/test_readiness.py

> `[Bash]` Run readiness tests

> `[Bash]` Full unit suite plus clean example run with readiness flow

> `[Bash]` Run misconfigure and tamper example modes

All three modes work. Now the README section, then full suite and commit:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Bash]` Run full suite, commit readiness work, push

> `[Edit]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

Done — commit `d52aa97` on `dev`, pushed. Summary:

## What landed

- **[readiness.py](pybb/pybb/attestation/readiness.py)** — `readiness_request([ids])`, `ReadinessReport`, and `make_readiness_predicate(protocols, config)`: checks every protocol in the tree (id resolves, config complete, every `goldenbytes` target has a provisioned golden, CVM binary + each manifest-listed ASP executable present). Memoized; the deeper CVM-tools checks are marked as the extension point in the docstring.
- **`StartAttestationKS`** ([knowledge_sources.py](pybb/pybb/attestation/knowledge_sources.py)) — the readiness→attestation link: writes the attestation entry seeded at the start tier, idempotently. It deliberately writes nothing to the readiness entry — the memoized check re-passes on the next cycle and standing recovers on its own.
- **`trust_summary`** now renders both readiness outcomes, so an escalated config failure reads as exactly that: "protocol readiness failed — gumbo_l9: unknown protocol; **attestation never started**".
- The example runs readiness-first, and the README documents the pattern with its rationale: **one dispatch per key = one branch point per entry; deeper trees chain entries.**

## Verified behavior (real CVM)

- **Clean**: `gumbo:ready` validates → starter writes `gumbo` → l1 attests intact. 2 cycles.
- **`--misconfigure`**: readiness fails on `gumbo_l9`, escalates as a configuration failure in 1 cycle, and the `gumbo` entry never comes into existence.
- **`--tamper`**: readiness passes, then the attestation entry exercises its own untouched branch point — l1 fail → l2 attributes `tc_sys_aadl_305_308_targ` → escalate, live tree restored from golden.
- Full suite: **59 passed, 2 skipped** (the gated Sireum runs).

The dev branch now has the complete arc we've been building: golden directory → provisioning partition → readiness verdict → tiered attestation with appraisal — with the nonce-bump/re-attestation wiring still parked as the next open thread whenever you want to pick it up.

## User

Discuss the nonce-bump feature and why it might be needed (or not)

## Assistant

Here's an honest assessment of the nonce bump — what it's for, what it would actually cost, and the fork in the road that decides whether we need it at all.

## What it is, precisely

The attestation predicate memoizes on the serialized measurement, so `{"protocol": "gumbo_l1", "nonce": 0}` computes exactly once per predicate lifetime. The controller re-evaluates every entry every cycle — memoization is what makes that affordable when a protocol takes minutes. The nonce is the *only* cache-busting lever: same protocol, bumped nonce → cache miss → fresh CVM run. That's all it is: **a freshness ticket for the memo table**. It has been sitting in the design since the routed rework ("a future repair KS forces fresh attestation by bumping the nonce") and we've deferred wiring anything to it.

## The three forces that would need it

1. **Repair verification.** When the repair loop lands (restore live targets from `golden/`), a repaired system must *prove* it's clean by re-attesting. The entry's l1 verdict is cached as failing; without a nonce bump, re-evaluation just replays the failure and the repair can never be confirmed.
2. **Re-provisioning invalidation** — the friction we identified in the provision-partition walkthrough. Fresh goldens make a cached attestation verdict stale (it was computed against the old ones). The provision partition's evaluate-first ordering solves this for verdicts *not yet rendered*; only a nonce bump can retract one already cached.
3. **Long-lived operation.** If the blackboard ever becomes a resident attestation manager rather than a script — provision → attest → tamper detected → repair → re-attest, all in one controller lifetime — attestation results decay with time, and periodic re-measurement needs a per-round freshness ticket.

Notice all three are variants of one thing: **re-attestation within a single predicate lifetime.**

## Why it may not be needed

The current operational model is **episodic**: every workflow is a fresh `controller.run()` with freshly built predicates. The memo cache lives in the predicate closure, so it *dies with the episode* — a new run re-attests everything from scratch, no nonce required. Your own framing when we designed the snapshot pointed the same way: "only during repair **or new runs of the workflow** should the live targets be reverted." If repair means "revert, then run the workflow again," the nonce has no job: the second run's fresh caches are the re-attestation. Everything in the codebase today is episodic; no test or example has ever needed a bump.

## The hidden cost: a bump is not a reset

This is the strongest argument for continued deferral. Walking the controller mechanics shows a nonce bump alone produces a **half-reset episode**:

- **The dispatch latch persists.** A previously dispatched entry keeps its chosen chain forever; a resting-passed entry that re-fails after a bump would walk whatever `dispatched` recorded, and `ks_history` still shows exhausted attempts — `_advance` may escalate immediately instead of retrying the ladder.
- **`original_measurement` betrays you.** Failure handoff restores the *original* measurement — which holds **nonce 0**. Mid-chain, a bumped entry can silently snap back to the old nonce and resurface the stale cached verdict it was trying to escape. That's a latent correctness bug in any naive bump-wiring.

So "re-attest this entry" honestly requires a *fresh-episode primitive* — new entry version, dispatch cleared (re-`route()`), `ks_history` reset, `original_measurement` re-seeded — of which the nonce bump is just one ingredient. Notably, `StartAttestationKS` is already ~80% of that primitive: it has a `nonce` field, and a variant allowed to overwrite plus a route reset *is* "restart the episode."

## One distinction worth keeping sharp

This nonce is **not** the attestation-security nonce. Anti-replay freshness — proving evidence was produced *now*, for *this* challenge — belongs to the CVM protocol and session layer (the stack has `check_nonce` appraisal support for exactly that). Our measurement nonce is cache bookkeeping in the verifier's own head. Conflating them would be a real design error: bumping our nonce gives you a fresh *run*, not a cryptographically fresh *proof*, and the README should say so when we eventually build this.

## My recommendation

Keep deferring — but recognize that the decision you're actually parking is *which operational model pybb is headed for*. Episodic (workflows as runs, repair triggers a re-run): the nonce stays vestigial and could even be argued out of the descriptor. Resident (a standing blackboard managing trust over time): build it, but as the **restart-episode primitive** (bump + re-route + history reset, likely a `StartAttestationKS` variant on the provision entry's or repair rung's chain), never as a raw nonce poke — the half-reset hazards above are why. The repair loop, whenever we port it from `attestation-integration`, is the natural forcing function: it's the first feature that can't be expressed without choosing.

## User

I'm still confused about what role the nonce field would have.  Is it possible to have two identical attestation entries on the blackboard at once?

## Assistant

Good question to pin down, because the answer dissolves most of the nonce confusion: **the nonce is not an identity field, and no, two entries can never collide — because identity lives in the key, not the measurement.**

## Entries are identified by key, and keys are unique

The certify segment is literally a dict: `entries: dict[str, BlackboardEntry]`. One key, one slot. Writing `"gumbo"` again doesn't create a second entry — it **replaces** the slot with a new version (and the old version, if evaluated, is already snapshotted in `history`). So "two identical attestation entries at once" is structurally impossible *per key*: the blackboard holds the current version of each question, and history holds its past.

What *is* possible is two **different keys** with identical measurements:

```python
bb.write_entry(key="gumbo",   predicate="attestation", measurement={"protocol": "gumbo_l1", "nonce": 0})
bb.write_entry(key="gumbo-2", predicate="attestation", measurement={"protocol": "gumbo_l1", "nonce": 0})
```

That's legal, and here's the telling part: the memoized predicate computes the verdict **once** and both entries receive the *same cached `Verdict` object*. Two trust questions, one protocol run. That's a feature (consistency + no duplicated minutes-long runs), and it reveals what the measurement actually is: not the entry's identity, but a **pointer into a shared table of attestation results**.

## So what the nonce actually is: a round number

Think of the predicate's cache as a table the whole blackboard shares:

| (protocol, nonce) | verdict |
|---|---|
| (gumbo_l1, 0) | pass — computed cycle 1 |
| (gumbo_l2, 0) | fail — computed cycle 2 |
| (gumbo_l1, **1**) | *would be a fresh CVM run* |

- **Key** = *which question* ("the gumbo system's trust standing")
- **`measurement.protocol`** = *which tier currently answers it*
- **`measurement.nonce`** = ***which round* of asking** — nothing more

Within one round, everything is stable: the controller can re-evaluate the entry fifty times across cycles, tiers can hop back and forth, several entries can reference the same protocol — all served from row (protocol, 0). The nonce exists solely so that a *deliberate* act ("we repaired the files — ask again for real") can address a **new row**: (gumbo_l1, 1) has no cache entry, so evaluation must run the CVM afresh. It's a version counter for *answers*, compensating for the design choice that evaluation is repeated but attestation must not be.

## Why the confusion is natural

The nonce feels like it should mean something deeper because in attestation-land "nonce" usually means a cryptographic freshness challenge. Ours doesn't — and it also does nothing *today*: every current workflow runs exactly one round of everything, so every measurement carries `nonce: 0` and the field is inert. It only acquires a job the day something wants a **second round within one predicate lifetime** — the repair-then-reverify loop, or re-attestation after re-provisioning. Until then it's a reserved seat.

And this reframing sharpens last turn's conclusion: since entries are versioned-by-key anyway, "re-attest gumbo" really means "write the next version of the `gumbo` entry pointing at the next round" — new measurement, nonce+1, dispatch and history reset. The nonce isn't a mechanism of its own; it's the row index that a proper restart-episode primitive would increment.

## User

Can we remove the nonce field entirely for now and retest the workflow?

## Assistant

Yes — it's inert today, and removing it makes the model honest: re-attestation, when it arrives, will be a fresh-episode act rather than a magic field. The user asked directly, so I'll make the change and retest everything. First, find every occurrence:

> `[Bash]` Find all nonce references outside CVM wire format

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

Now `provision.py` and `readiness.py`:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/provision.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/provision.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/provision.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/readiness.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/readiness.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/readiness.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_provision.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_readiness.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_readiness.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Bash]` Find remaining nonce mention in README

> `[Bash]` Find all remaining nonce references

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

Now retest everything — full suite, then all example workflows against the real CVM:

> `[Bash]` Run full test suite including CVM integration

> `[Bash]` Run all four example workflows against real CVM

> `[Bash]` Commit nonce removal and push

> `[Bash]` Find stale nonce mentions in project memory

> `[Edit]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

> `[Edit]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

> `[Edit]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

Done — nonce is gone, everything retested, committed as `108506a` and pushed.

## What changed

- **Request descriptors are now minimal**: `{"protocol": ...}` for attestation and provisioning, `{"protocols": [...]}` for readiness. The `nonce` parameter is removed from all three request builders, from `TierKS` (which no longer needs to carry anything forward), and from `StartAttestationKS`.
- **Docstrings and READMEs** now state the operational model the removal makes explicit: memoization is **per predicate lifetime**, episodes are runs, and a fresh workflow run re-attests/re-provisions/re-checks everything. In-session re-attestation is documented as a *future restart-episode primitive* — deliberately not a measurement field, since the `original_measurement` restore path on failure handoff would have silently reverted a bumped field mid-chain anyway.
- The three memoization tests became "memoized per lifetime" tests (the attestation one now also proves a fresh predicate re-attests).

## Retest results

- Full suite: **59 passed, 2 skipped** (gated Sireum runs), including the CVM integration tests.
- All four real-CVM workflows verified end to end: clean (readiness → l1 intact, 2 cycles), `--tamper` (l1 → l2 attribution → escalate, live tree restored from golden), `--misconfigure` (config escalation in 1 cycle, attestation never starts), and the provision workflow (4 + 28 targets provisioned from golden, live attestation clean in the same run).

Net effect on the design: the descriptor now says exactly what it means — *which protocol answers this entry* — and the door to re-attestation is a single, well-understood future feature (restart-episode: new entry version + re-route + history reset) instead of a mysterious integer riding along on every measurement.

## User

Justify how we know a re-provisioning event triggers brand new protocol runs.  Walk through this scenario with details about how the blackboard is updated.

## Assistant

This claim deserves a rigorous justification, because it rests on two different kinds of argument — one *by construction* (where the caches live and die) and one *empirical* (a demo that would fail if the claim were false). Let me give both, wrapped around the concrete scenario.

## The claim, precisely

"A re-provisioning event triggers brand-new protocol runs" means: after new files land in `golden/` and a new workflow run starts, **every** evaluation — provisioning, readiness, attestation — invokes the CVM binary afresh; nothing is answered from a stale cache, and the attestation runs consume the *newly* installed goldens.

## Part 1: Where run N's state actually lives when it ends

When the previous workflow run (run N) finishes, its state splits into two fates:

**Dies with the process:** the `BlackboardController`, the `Blackboard` (all three partitions, history), and — critically — both predicate closures *including their memo caches*. The cache is a plain `cache: Dict[str, ...] = {}` created **inside** `make_attestation_predicate` / `make_provision_predicate` at call time; it is reachable only through the closure, and pybb has no persistence layer of any kind — nothing ever writes a blackboard or a cache to disk. Cache lifetime ⊆ predicate lifetime ⊆ process lifetime.

**Survives on disk:** `golden/` (now updated by the event), `golden/_bundles/*`, and the protocol dirs — whose `asp_args.json` holds run N's goldens and whose `cvm_request.json` was deleted by run N's provisioning.

So the "memory" that could possibly serve a stale answer does not exist when run N+1 begins. That's the by-construction half: **fresh run ⇒ fresh closures ⇒ empty caches ⇒ first evaluation of every descriptor is a cache miss ⇒ `_provision`/`_attest` executes ⇒ `client.run_protocol` ⇒ a new CVM subprocess.**

## Part 2: The scenario, cycle by cycle

Setup for run N+1: the event updated `golden/.../TempControlSystem.aadl`; requests are written — `provision:gumbo_l1`, `provision:gumbo_l2` into the **provision partition**, `gumbo:ready` into certify, routes registered (attestation route pre-registered, `gumbo` entry not yet existing).

**Cycle 1, evaluation phase — provision partition first (structurally guaranteed):**
- `provision:gumbo_l1` evaluates: `'{"protocol": "gumbo_l1"}'` misses the empty cache → `_provision` runs: builds the APPR-stripped term with paths re-rooted at the **current** golden copies, launches a **new CVM subprocess**, overwrites `golden/_bundles/gumbo_l1/provision_bundle.json`, runs `extract_golden_slice` per target, and installs the **new** `golden_b64` values (hashes of the *updated* golden content — different bytes than run N's) into both the on-disk `asp_args.json` and the **in-memory shared `ProtocolDir`**, forcing `prebuilt_request = None`. Blackboard update: the provision entry gets `result=ProvisionOutcome(...)`, `good_standing=True`, and history records the act. Same for l2.
- Certify evaluates next: `gumbo:ready` runs its (also-fresh) readiness check — note it reads the *same shared `ProtocolDir` objects* just mutated, so "goldens provisioned" is checked against the new state. Passes.
- Dispatch: `gumbo:ready` passed with a non-empty `on_pass` → standing cleared (provisional), `StartAttestationKS` gets the key; KS phase writes the `gumbo` entry, `measurement={"protocol": "gumbo_l1"}`, `result=None`.

**Cycle 2:**
- Provision entries re-evaluate → cache **hits** → same outcomes instantly (this is the memoization doing its one job: the controller's per-cycle re-evaluation doesn't re-run provisioning).
- `gumbo:ready` re-evaluates → hit → standing restored; rests as the readiness record.
- `gumbo` evaluates for the first time: the attestation predicate's cache is empty this run → miss → `_attest` → `run_protocol` → `build_request()`. Here the two invalidation mechanisms matter: `prebuilt_request` is `None` (provisioning forced it) and `cvm_request.json` is gone from disk, so the request is **assembled dynamically from `protocol.asp_args`** — which the same-process, same-object mutation in cycle 1 filled with the new goldens. A **new CVM subprocess** attests the *live* tree against them. The verdict lands on the entry; dispatch routes it on its own branch point as usual.

Every blackboard write in this story is a fresh entry version through `set_entry` with a history snapshot — the audit trail for run N+1 shows, in order: two provisioning acts, a readiness validation, and an attestation verdict, all timestamped by cycle.

## Part 3: The empirical witness

The `--tamper-golden` demo is the smoking gun, because it's a scenario where stale reuse would produce the *opposite* result: we corrupt a golden copy, provision, then attest — and attestation **fails**, with l2 attributing the drift to exactly `tc_sys_aadl_305_308_targ`. That outcome is only possible if (a) provisioning genuinely measured the changed golden content in a new run, (b) the new goldens genuinely reached the attestation request, and (c) attestation genuinely re-measured the live tree and compared. Any cached verdict, surviving prebuilt request, or stale golden would have yielded a clean pass. The integration test pins the complementary direction: re-provisioning from *unchanged* golden produces byte-identical goldens and a passing attestation.

## The honest boundary of the guarantee

The justification is airtight **under the episodic model** and enforced only *by construction*, not by the runtime. Two ways to violate it, both visible from the walkthrough: embed pybb in a long-lived daemon and reuse the same predicates across events (second identical request → memo hit → **no** re-provisioning, silently); or rebuild predicates but hand-share an old `protocols` dict across runs without reloading (fresh caches, but readiness/attestation coupling assumptions shift). Today every entry point — examples, tests — constructs controller, predicates, and `ProtocolDir`s together, so the invariant holds everywhere the code can currently be exercised. The day a resident deployment appears, this is precisely the gap the restart-episode primitive must close — and this walkthrough is effectively its specification.

## User

Let's move on to add a simple repair capability.  To start, add a knowledge source for repairing L1 gumbo artifacts.  This repair KS should react to failed appraisals of the L1 artifacts, and replace them with the original (from provisioning) artifacts.  Propose changes to the workflow for this

## Assistant

Good next step — and it collides head-on with the decision we just made (no in-session re-attestation), so the design has to be honest about how a repair gets *verified*. Here's my proposed plan.

## The central design problem

A repair KS restores files, but the l1 verdict is **memoized**: re-evaluating `{"protocol": "gumbo_l1"}` after repair replays the cached failure. We deliberately removed the nonce escape hatch. So within one run, repair can only be verified by **a protocol that hasn't run yet** — and the chain already contains one: `gumbo_l2`. That observation gives a design that needs *zero* controller changes and no restart-episode primitive:

**Repair is a rung placed *before* l2 on the fail chain. Its verification is l2's fresh measurement of the repaired artifacts.**

```python
on_fail = [GoldenRestoreKS(golden_root=GOLDEN_ROOT), TierKS("gumbo_l2")]
```

## The walkthrough (with `--tamper --repair`)

- **Cycle 1**: l1 attests the tampered tree → fails. Dispatch → fail chain; `GoldenRestoreKS` gets the key. It reads the entry's failing `Verdict`, collects the **failing components' `filepath` args** (that's "react to failed appraisals of the L1 artifacts" — verdict-driven, targeted), copies each one's golden mirror over the live file, and rewrites the entry with `result=None`.
- **Cycle 2**: re-evaluation memo-hits the stale l1 failure (expected and *correct as history* — the pre-repair state truly was failing). The repair rung's one attempt is exhausted → `_advance` hands the key to `TierKS("gumbo_l2")`, which re-points the measurement.
- **Cycle 3**: l2 runs **fresh** against the now-repaired files → 28/28 slices match golden → good standing. The trail reads: l1 failed → repair fired → l2 passed. The episode ends in good standing with real, fresh evidence that the repaired artifacts match gold.

Escalate path stays intact: if repair can't fix it (e.g. a failing component with no `filepath`, like a signature failure, or golden copy missing), l2 fails too and the entry escalates with the l2 report plus a `ks_history` showing repair was attempted.

## What I'll build

1. **New `pybb/attestation/repair.py`** — `GoldenRestoreKS(golden_root)`: `max_attempts=1`, name `repair:golden-restore`; execute = restore failing-component filepaths from their golden mirrors (via `mirror_path`; golden stays strictly read-only), then `result=None`. Skips components without filepaths; restores nothing on a non-`Verdict` result.
2. **`trust_summary`** — when a passing/failing trail includes a repair rung in `ks_history`, say so: "gumbo_l1 failed; **repaired from golden**; gumbo_l2 passed on repaired artifacts" instead of the misleading "clean at finer granularity".
3. **Example** — `--repair` flag adds the rung to the fail chain; `--tamper --repair` demonstrates the full loop, and the end-of-run `golden.restore()` should find *nothing* left to revert (repair already did it — a nice self-check to print).
4. **Tests** — unit (scripted client): tamper→repair→l2-pass happy path; targeted restore (only the failing file touched); unrepairable failure → l2 still fails → escalate with repair in history. Integration (real CVM): tamper live, run with repair chain, assert file bytes restored to golden and entry in good standing via a real l2 run.
5. **README** — repair section stating the semantics and the boundaries below.

## Boundaries and trade-offs to agree on

- **Repair-before-attribution**: repairing first destroys the tampered state, so per-contract l2 attribution of *what was tampered* is never recorded (l1's verdict still names the failing *files*). The alternative — attribute first (`[l2, repair]`) — preserves the forensic detail but leaves nothing fresh to verify the repair in-run, forcing escalation or a next-run verification. For a *simple* repair capability I propose repair-first; the forensic variant can be a follow-up mode.
- **Verification is at l2's granularity** this run. The clean full-l1 pass comes from the *next* workflow run (episodic model, fresh caches) — the README will say exactly that.
- **A repair rung must be followed by a verifying tier** — repair alone at the end of a chain would exhaust and escalate even after a successful restore, since nothing fresh can vouch for it. I'll note this as a wiring rule.
- Trust direction preserved: repair reads golden, writes live — the one allowed direction; provisioning remains the only golden-writer, and only from external events.

Proceed with this?

## User

First, let's make sure this is the correct semantics for repair.  Are all the L1 artifacts supposed to be immutable in the HAMR paradigm?

## Assistant

Excellent instinct to pause here — this question cuts to exactly the spot where my proposal was on shaky ground. Let me ground the answer in the actual artifacts before arguing semantics:

> `[Bash]` Check do-not-edit markers in GumboX and component files

No — and the artifacts themselves say so explicitly. This changes the repair design. Here's what the HAMR paradigm actually declares:

## The three immutability classes in the temp-control stack

| artifact | HAMR's own declaration | measured by |
|---|---|---|
| GumboX oracles (`*_GumboX.scala`) | **"Do not edit this file as it will be overwritten if HAMR codegen is rerun"** — generated, whole-file immutable | l1 whole-file hash + l2 ranges |
| AADL models (`*.aadl`) | The design *source* — developer-edited over the lifecycle; the GUMBO contract clauses inside are the trust-relevant regions | l1 whole-file hash + l2 line-ranges (9 slices) |
| Component files (`*_tempControl.scala` etc.) | **"This file will not be overwritten so is safe to edit"** — explicitly developer-owned, *except* the codegen-managed `BEGIN/END` contract blocks | l2 marker-ranges only (deliberately **not** in l1) |

So of the four L1 artifacts, only the two GumboX oracles are paradigm-immutable. The AADL files are immutable *by baseline policy*, not by paradigm — and the existing decision tree already encodes this distinction: "l1 fail → l2 pass → **attested clean at finer granularity**" ends in *good standing*, meaning the system deliberately tolerates AADL changes outside the measured contract ranges. The enforced invariant is **l2's slice map**, not l1's whole files. l1 is a fast screen. (Even the component files' exclusion from l1 confirms it: whole-file hashing is only applied where whole-file immutability holds or is being screened.)

## Why this breaks my repair-first proposal

Whole-file restore on l1 failure would enforce the *wrong invariant*: a benign AADL edit (a comment, a new component outside any contract) fails l1, and repair-first would **clobber legitimate developer work** that the tree itself, left alone, would have judged acceptable via l2. Repairing before attribution destroys exactly the evidence l2 exists to weigh. There's also direct precedent: the old `attestation-integration` repair layer (`GoldenRestoreRepairer`) deliberately made **hash components unrepairable by design** and repaired only range/marker slices, line-wise — the previous iteration of this project already reached this conclusion.

## The corrected options

**A. Attribution-guided slice repair** — chain `[TierKS(l2), GoldenSliceRepairKS]`. l2 attributes first; repair restores **only the violated slices** (splice the golden copy's line-range / marker-block into the live file, leaving the rest of the file untouched — including legitimate edits elsewhere). This enforces precisely the invariant the system already declares, and preserves the forensic record. The catch we already know: with both protocols now cached, **in-run verification is impossible** — the honest end state is "repaired, unverified" (escalate carrying the repair record), and verification is the *next episode*, which the episodic model makes natural: the demo can simply run a second controller episode and show it coming up clean. Repair without fresh evidence *shouldn't* confer good standing anyway — that's a feature, not a workaround.

**B. Class-aware repair** — whole-file restore for the paradigm-immutable class (GumboX oracles) with l2 as in-run verifier, plus A's slice repair for contract ranges. The full-fidelity answer, but two mechanisms — not "simple" as a first step.

**C. Strict-baseline whole-file restore** (my original proposal) — only defensible if you declare an operational mode where *any* drift in watched files is unauthorized. That contradicts the tree's own "clean at finer granularity" tolerance, so adopting C would really mean *changing* the system's declared invariant, not adding repair to it.

## My recommendation

**Option A** — it matches the HAMR paradigm, the existing tree semantics, and the old repair layer's hard-won precedent; and its "verification = next episode" property aligns exactly with the episodic model we committed to when removing the nonce. The demo becomes a two-episode story: episode 1 tampers a contract line, attributes it, splices the golden slice back; episode 2 runs clean end-to-end — which is honestly a better demonstration of the architecture than an in-run shortcut.

Want me to draw up the concrete plan for A (slice-splicing repair KS, the escalate-with-repair-record semantics, the two-episode example, tests)?

## User

Before choosing an option, let's dive deeper to look at what each tier is measuring.  I'd like to know the type of HAMR files each tier is measuring and how they overlap.

## Assistant

Let me extract the exact target lists from the protocol configs and map them to the files.

> `[Bash]` Dump every measurement target of all three tiers

> `[Bash]` Dump validation args, l2 coverage stats, and sample slice contents

> `[Bash]` Extract validation tier's command targets from its term

Now I have the complete picture. Here's what each tier measures, organized by HAMR file class, with the overlap structure — and it surfaces one genuine coverage gap worth knowing about.

## Tier 1 — `gumbo_l1`: 4 whole-file hashes

| file | HAMR class | size |
|---|---|---|
| `TempControlSystem.aadl` | AADL design source (developer-owned) | 312 lines |
| `TempSensor.aadl` | AADL design source (developer-owned) | 126 lines |
| `TempControl…_GumboX.scala` | codegen oracle ("do not edit") | 296 lines |
| `TempSensor…_GumboX.scala` | codegen oracle ("do not edit") | 83 lines |

Two paradigm-immutable files, two developer-owned files. **No component files** — deliberately, because whole-file hashing a "safe to edit" file would fire on every legitimate edit; the screen can only screen files expected not to change.

## Tier 2 — `gumbo_l2`: 28 content slices

| file | HAMR class | slices | lines covered | what the slices are |
|---|---|---|---|---|
| `TempControlSystem.aadl` | AADL source | 7 line-ranges | 23 / 312 (**7%**) | GUMBO clauses: `assume` port-range contracts, the `SetPoint_Data_Invariant` (the demo's lines 305–308) |
| `TempSensor.aadl` | AADL source | 2 line-ranges | 4 / 126 (**3%**) | GUMBO `assume` clauses |
| `TempControl…_GumboX.scala` | oracle | 9 line-ranges | 61 / 296 (**20%**) | the `@strictpure` contract predicates |
| `TempSensor…_GumboX.scala` | oracle | 4 line-ranges | 13 / 83 (**15%**) | same |
| `…tempControl.scala` | component ("safe to edit") | 5 marker-blocks | `STATE VARS`, `INITIALIZES/COMPUTE MODIFIES/ENSURES` blocks | codegen-managed contract blocks inside developer code |
| `…tempSensor.scala` | component ("safe to edit") | 1 marker-block | `INITIALIZES ENSURES` | same |

l2's slice map is, in effect, **the machine-readable definition of "the immutable content"** across all three file classes — including the component files l1 can't touch.

## Tier 3 — `gumbo_validation`: 5 commands, zero file measurements

`proyek tipe` (type-check the whole `slang/` project), `proyek logika` ×2 (formally verify each GumboX module's predicates with Z3), `proyek test` ×2 (run each component's randomized GumboX unit tests). This tier measures **no bytes at all** — its evidence is tool exit codes over the live project. It overlaps the others *semantically*: logika and test exercise exactly the contract content l2 measures textually, and tipe sweeps everything, including code no other tier sees.

## The overlap structure

```
                              l1 (hash)   l2 (slices)   l3 (semantic)
AADL: GUMBO clauses (27 ln)      ✓            ✓          ✓ (via GumboX)
AADL: everything else (~95%)     ✓            —          — (models aren't compiled here)
GumboX: contract predicates      ✓            ✓          ✓ (logika proves, test executes)
GumboX: rest of generated file   ✓            —          ✓ (tipe, test harness)
Component: contract blocks       —            ✓          ✓ (test exercises them)
Component: developer code        —            —          ✓ (tipe, test)
Rest of slang project            —            —          ✓ (tipe)
```

Three observations that matter for the repair decision:

1. **The four "L1 artifacts" split cleanly**: for the GumboX oracles, l1's whole file ⊇ l2's slices and *all* of it is paradigm-immutable — whole-file restore is sound there. For the AADL files, l2 covers only 3–7%; the other ~95% is l1-screened but *not* part of the declared invariant — whole-file restore there clobbers developer-owned content. The overlap data quantifies exactly why Option C was wrong.

2. **The component contract blocks are l2-only — and l2 only runs on l1 failure.** This is the coverage gap: tamper a `BEGIN/END COMPUTE ENSURES` block and l1 passes (it doesn't watch that file), so the current tree ends the episode in good standing without l2 ever running. Only `--validate`'s semantic tier could catch it, indirectly. If contract blocks are part of the invariant — and l2's own target list says they are — then the screen doesn't screen them. Worth deciding at some point whether l2 (or a cheap hash-of-slice variant of it) should be an *always-run* tier rather than a fail-branch tier; that's a decision-tree question, separate from repair.

3. **Slice-level repair maps one-to-one onto l2's target list** — every slice is a contiguous golden region (line-range or marker-block) with a known live location, across all three file classes. So Option A's repair unit isn't an approximation; it's literally the system's declared invariant, file class by file class. And the same mechanism covers a future component-block repair for free.

This data makes me more confident in the Option A recommendation (attribution-guided slice repair), with the GumboX whole-file restore (Option B's first half) as a defensible later optimization — it's the one class where whole-file is provably safe. Want to proceed to the concrete Option A plan, or first talk through the l2 coverage-gap question this surfaced?

## User

Let's talk through the l2 coverage gap first

## Assistant

Let's frame the gap precisely, then walk the ways to close it — because the best fix turns out to interact nicely with the repair design we're circling.

## The gap, restated sharply

The system has an **invariant surface** (l2's 28 slices — the declared do-not-edit content across all six files) and a **screen** (l1's 4 whole-file hashes). The screen's file coverage is narrower than the invariant: the six component-file contract blocks live *only* in l2, and l2 only runs when l1 fails. So:

> Tamper confined to a component contract block → l1 passes → episode ends in good standing. The invariant is violated and nothing ever looked.

Two aggravating details: the exclusion of component files from l1 is *correct* (they're "safe to edit"; whole-file hashing would false-alarm on every legitimate edit — a screen can only screen stable files), so you can't fix this by "just adding the files to l1." And `--validate` is not a reliable backstop: it's opt-in, minutes-long, and a *weakened contract block* may well still type-check and pass randomized tests — semantic tools verify what the contracts *say now*, not that they say what gold says.

## Options

**1. Accept and document.** Defensible only if component blocks are second-class invariant content — but l2's own target list says they aren't. Rejected.

**2. Widen the screen: add the 6 marker-blocks to l1's protocol.** Mix six `readfile_marker_range` targets into `gumbo_l1` alongside the four hashes (~10 targets, still ~1s). Preserves the clean screen→attribute→confirm story with one entry. Costs: it's **protocol authoring** — edit `gumbo_l1`'s term/asp_args (cvm-mcp generator territory), then re-provision (which our provisioning partition can now do, at least). Heavier change, touches artifacts outside pybb.

**3. A parallel invariant entry: run l2 every episode as its own trust question.**

```python
controller.route("gumbo:contracts", on_fail=[...])           # the invariant question
bb.write_entry(key="gumbo:contracts", predicate="attestation",
               measurement=attestation_request("gumbo_l2"))
# "gumbo" keeps its existing l1 tree: the drift/baseline question
```

This reframes rather than patches: **"gumbo" asks "has the baseline drifted?" (screen semantics), "gumbo:contracts" asks "is the invariant intact?" (the thing the system actually enforces)** — two genuinely different questions, which in blackboard philosophy *should* be two entries. Component-block tamper now fails `gumbo:contracts` even while `gumbo` passes.

The killer detail is what it costs: **almost nothing, because of memoization.** Both the new entry and the l1-tree's `TierKS("gumbo_l2")` resolve to the same descriptor `{"protocol": "gumbo_l2"}` in the same predicate cache — l2 runs *at most once per episode* no matter how many entries reference it. On a tamper-in-l1-range episode, both entries fail and share the single l2 run; on a clean episode you pay one extra ~1s protocol. Zero protocol authoring, zero controller changes, readiness just adds l2 to its checked set (it already does).

**4. Invariant-first: start the single entry at l2.** Enforces exactly the invariant, catches the blocks — but discards the screen entirely: whole-file drift in the GumboX oracles (paradigm-immutable, remember) outside the slice ranges would go unseen, and you lose the "benign drift vs. violation" distinction ("clean at finer granularity") that the tree deliberately draws. Simpler, strictly less informative.

## Why I recommend Option 3

- It closes the gap **today**, with wiring, not authoring.
- It makes the architecture more honest: the current tree quietly conflates "drift detector" and "invariant enforcer" in one entry, and this gap is precisely the seam where that conflation leaks. Splitting the questions names them.
- **It gives the repair work its natural home.** Slice repair (Option A from last turn) reacts to invariant violations — so it belongs on `gumbo:contracts`' fail chain, uniformly covering AADL clauses, GumboX predicates, *and* component blocks. The `gumbo` entry stays a pure detector (its fail chain keeps l2-attribution for the forensic story, or eventually the whole-file GumboX restore where that's sound). Repair and gap-fix compose instead of competing.
- Option 2 remains available later as a refinement (a widened screen would let the *drift* entry also notice block tamper), but it's not needed for correctness once the invariant entry exists.

One consequence to accept: `trust_summary` and the demos now tell a two-line story per system ("baseline: intact / drifted-benign / violated" + "contracts: intact / violated / repaired"). I'd argue that's a better report, but it is a visible change.

If this direction sounds right, the natural sequencing is: first the `gumbo:contracts` entry (small, closes the gap, testable with a component-block tamper demo that today's tree provably misses), then the slice-repair KS attached to its fail chain. Want me to plan those as one step or two?

## User

Consider this alternative design:  decompose L1 into L1a and L1b.  L1a is the immutable whole-file hash targets.  L1b is the immutable component file slice contract targets.  Each of these would have a distinct repair:  L1a repair restores whole files, L1b restores just the offending file slice.  Given this new design, see if it would also make sense to adjust the L2 protocol to omit component file slice targets.  L2 would just be a deeper dive into L1a failure.

## Assistant

This design is better than my Option 3 — and it's better for a reason that's worth naming precisely, because it resolves the repair-semantics puzzle we've been circling for three turns.

## The principle your decomposition lands on

**Repair unit = measurement unit.** Each tier's repair restores exactly what that tier measures, so repair provably converges to that tier's pass:

- **L1a** (whole-file hashes of baseline-immutable files) → whole-file restore → next episode's L1a hash *must* match gold. Converges.
- **L1b** (contract blocks in developer-owned files) → slice splice → next episode's L1b block-read *must* match gold. Converges. And it touches nothing outside the block, which is mandatory in a "safe to edit" file.

Every earlier option mismatched these units somewhere. My slice-repair-for-L1-failures proposal had a convergence hole I hadn't fully faced: splicing only the violated slice of an AADL file leaves the *whole-file hash* failing forever — the entry would come up "clean at finer granularity" every episode until the end of time, with repair unable to ever restore L1a-pass. Your design eliminates that: whole-file tiers get whole-file repair.

It also answers my AADL objection ("whole-file restore clobbers benign edits") the *right* way, via policy rather than mechanism: in a provisioned baseline, benign edits are still drift. If a developer's edit is legitimate, the sanctioned path is **re-provisioning** — update `golden/`, run the provision partition, declare new gold — which is exactly the flow we built. Repair's job is to converge the live tree to *current* gold, not to adjudicate which drift deserves to survive. (And the chain ordering below preserves tolerance for benign drift anyway — see the walkthrough.)

## Yes to the L2 adjustment

Slimming L2 to the 22 slices inside L1a's files (dropping the 6 component-block targets) makes L2 semantically pure for the first time: **every L2 target refines some L1a target**, so "L2 is a deeper dive into L1a failure" becomes literally true rather than mostly true. The component blocks lose nothing — L1b's targets are *already* the finest granularity for them (block = the measurement = the repair unit; there is no deeper dive to take). And the coverage gap closes structurally: L1a and L1b are both always-run first tiers, and their union is the entire invariant surface.

## The new decision trees

```python
# entry "gumbo:files" — the baseline question (starts at L1a)
route("gumbo:files",
      on_pass=[TierKS("gumbo_validation")],        # --validate, as today
      on_fail=[TierKS("gumbo_l2"), WholeFileRestoreKS(golden_root)])

# entry "gumbo:contracts" — the component-contract question (starts at L1b)
route("gumbo:contracts",
      on_fail=[SliceRestoreKS(golden_root)])
```

Walk the fail paths and notice the chain ordering does real work:

- **L1a fail → L2 pass** (drift outside contract ranges): episode ends in good standing, *repair never fires* — the "clean at finer granularity" tolerance survives untouched, because a chain pass ends the episode before reaching the repair rung. Perpetually-drifting-but-tolerated files remain the signal to re-provision.
- **L1a fail → L2 fail** (confirmed contract violation): attribution is recorded *first* (forensics preserved), then `WholeFileRestoreKS` restores the L1a-failing files whole — full revert of a confirmed-compromised file, standard practice. Nothing fresh remains to verify in-run; the entry ends "repaired, unverified" and **episode 2 verifies** — the episodic model doing its job.
- **L1b fail**: no attribution needed (already block-granular) → splice the violated blocks from gold → same repaired-unverified end state → episode 2 confirms.

## What it takes (honest scope)

1. **Protocol authoring** — the first time we touch protocol definitions: split `gumbo_l2` → new `gumbo_l1b` (the 6 marker targets, same ASP set) and slimmed `gumbo_l2` (22 range targets). `gumbo_l1a` is the current `gumbo_l1`, at most renamed. Mechanical (move targets between term/asp_args files), and then — nice dogfood — **the provision partition re-provisions both changed protocols from `golden/`** on the blackboard.
2. **Two repair KSs** (`repair.py`): whole-file restore (verdict-driven: the L1a-failing filepaths) and slice restore (verdict-driven: splice golden line-ranges/marker-blocks — the line-wise splice logic has precedent in the old `GoldenRestoreRepairer`).
3. **Wiring**: two always-run entries (readiness checks all four protocol ids; memoization already dedupes any shared runs), summary learns the two-line story and the "repaired, unverified — re-run to confirm" state.
4. **Demos/tests**: component-block tamper (provably undetected by today's tree) → L1b catches → slice repair → episode 2 clean; AADL contract tamper → L1a→L2→whole-file repair → episode 2 clean; benign AADL drift → tolerated, no repair, flagged for re-provisioning.

Open decisions before I plan in detail: (a) protocol naming — `gumbo_l1a`/`gumbo_l1b`/`gumbo_l2`, or keep `gumbo_l1` for the whole-file tier? (b) should `--validate`'s confirmation also attach to the `gumbo:contracts` entry, or stay on the files entry only? (c) any appetite for repairing *benign* drift under a strict flag, or is re-provisioning the only sanctioned path (my lean)?

## User

The new proposed decision tree seems incomplete to me.  Let's walk through it in more detail.

## Assistant

You're right to push — walking it rigorously against the actual controller mechanics turns up **five real holes**, one of them a outright wiring bug. Let me enumerate the full path space first, then the gaps.

## Complete path enumeration

**`gumbo:files`** (starts at L1a, `on_pass=[validation]`*, `on_fail=[TierKS(l2), WholeFileRestoreKS]`):

| # | path | end state |
|---|---|---|
| F1 | L1a pass (no `--validate`) | certify, good standing — intact |
| F2 | L1a pass → validation pass | certify, good — intact, confirmed |
| F3 | L1a pass → validation fail | escalate (validation report) |
| F4 | L1a fail → L2 pass | certify, good — **tolerated drift** (repair correctly never fires; chain pass ends episode) |
| F5 | L1a fail → L2 fail → repair fires | **escalate** — see Gap 2 |
| F6 | L1a fail → L2 fail → repair can't act | escalate — see Gap 4 |

**`gumbo:contracts`** (starts at L1b, `on_fail=[SliceRestoreKS]`):

| # | path | end state |
|---|---|---|
| C1 | L1b pass | certify, good — contract blocks intact |
| C2 | L1b fail → slice repair fires | **escalate** — Gap 2 again |
| C3 | L1b fail → unrepairable | escalate — Gap 4 |

## Gap 1 — the starter wiring is actually broken (two episodes, one chain)

I hand-waved "readiness starts both entries." It can't, as proposed. If we write `route("gumbo:ready", on_pass=[starterA, starterB])`, the mechanics betray us: **chains are failure ladders, not sequences**. Cycle 1: readiness passes → dispatch clears standing → *only* `starterA` (chain head) gets the key → it writes `gumbo:files`. Cycle 2: readiness re-evaluates → memoized pass → good standing restored → `_advance` never fires (it only advances on failure-exhaustion) → **`starterB` never runs and `gumbo:contracts` never exists.** The same chain-semantics trap that broke `on_pass=[L1, L3]` earlier.

**Fix**: generalize the starter to write *multiple* episodes — `StartAttestationKS(episodes={"gumbo:files": "gumbo_l1a", "gumbo:contracts": "gumbo_l1b"})` as a single rung. (Per-entry readiness entries would also work but doubles the readiness bookkeeping for no benefit; one readiness check already validates all four protocols.)

## Gap 2 — "repaired, unverified" is mechanically an *escalation*

Trace F5 past the repair: repair restores files, writes `result=None`. Next cycle, evaluation memo-hits the stale L1a failure; the repair rung's one attempt is exhausted; `_advance` finds no successor → **the entry moves to escalate**, whose meaning everywhere else is "user intervention required." But the actually-required action here is *none* — just run the next episode. The tree as proposed has no vocabulary for "action taken, verification pending," so it misfiles a successful repair under human-intervention.

**Fix options**: (a) accept the mechanics but teach `trust_summary` to render an escalated entry whose `ks_history` contains a repair rung as **"repaired from golden — verification pending next episode"**, distinct from genuine intervention cases; the demo runs episode 2 to close the loop. (b) Add a terminal `RepairedKS`-style rung that parks the entry differently — new machinery, and it would have to fabricate standing it has no evidence for. I recommend (a): honest (no fresh evidence ⇒ no good standing), zero new mechanism, and the two-episode demo *is* the verification story.

## Gap 3 — repair scope on mixed drift is undecided (and which verdict does repair even see?)

Scenario: file A tampered *outside* contract ranges (benign), file B tampered *inside* one. L1a fails on both; L2 fails only on B. Does `WholeFileRestoreKS` restore both A and B (strict baseline: all L1a-failing files) or only B (only confirmed violations)? Restore-only-B leaves A perpetually in the F4 tolerated-drift loop (consistent with tolerance, converges to "clean at finer granularity" forever); restore-both reverts a benign edit because an unrelated file was compromised (strict, converges to full L1a-pass).

There's also a mechanical subtlety worth knowing: at repair-execution time, `_advance` has already restored the measurement to L1a, so the cycle's re-evaluation memo-hit means **`entry.result` is the L1a verdict again** — the repair rung sees the failing *files* for free, while the L2 verdict (failing *slices*) is only in history. So restore-all-L1a-failing is the mechanically natural policy; restore-only-confirmed requires digging the L2 verdict out of history. My lean: **restore only the L1a-failing files that L2 confirmed violated** is semantically purest, but for the *simple* first version, restore-all-L1a-failing is defensible (the episode has established compromise; conservative full revert; benign-only files still never trigger repair because F4 ends before the rung). Needs your call.

## Gap 4 — unrepairable failures and the unguarded KS loop

Failing components without filepaths (a `sig_appr` failure), a missing golden copy, an I/O error: the controller's KS loop has **no exception handling** — a raising repair KS crashes the whole run. The repair KSs must catch internally, restore what they can, and let the normal exhaust-→-escalate path produce "repair attempted, N restored, M unrestorable" via history. Wiring rule, but it must be explicit in the plan.

## Gap 5 — episodes can't see each other

Episode 1's blackboard (including the repaired-pending-verification escalation record) dies with its process; episode 2 starts blank, attests clean, and has no idea a repair ever happened. Within the current episodic model that's by design — but the *demo and summary* must own the narrative across episodes (the script runs both and prints "episode 1: violated → repaired; episode 2: verified clean"), and it's worth an explicit note that a persistent audit trail across episodes is future work (it will matter for real deployments).

## The amended tree

```python
controller.route("gumbo:ready",
    on_pass=[StartAttestationKS(episodes={"gumbo:files": "gumbo_l1a",
                                          "gumbo:contracts": "gumbo_l1b"})],   # Gap 1
    on_fail=[])
controller.route("gumbo:files",
    on_pass=[TierKS("gumbo_validation")],                                      # --validate
    on_fail=[TierKS("gumbo_l2"), WholeFileRestoreKS(golden_root)])             # Gaps 3,4 inside the KS
controller.route("gumbo:contracts",
    on_fail=[SliceRestoreKS(golden_root)])
# + trust_summary: escalated-with-repair-in-history => "repaired, verification pending"  (Gap 2)
# + demo: two-episode run                                                       (Gaps 2,5)
```

The paths F1–F6/C1–C3 all now land in a named, intended state. Two decisions are yours before I turn this into the implementation plan: **Gap 2** — accept escalate-as-repaired-pending (my recommendation) or invent a new terminal state; **Gap 3** — repair scope: all-L1a-failing files, or only-L2-confirmed files (needs history access; my lean for v1 is all-L1a-failing, documented).

## User

Let's revisit the roles of each layer in detail.  L1a, L1b, etc.

## Assistant

Here's the full layer-by-layer role map for the proposed architecture — each layer's question, evidence, trigger, and just as importantly its *boundaries* (what it cannot do, which is what forces the next layer to exist).

## The stack at a glance

| layer | question | evidence type | granularity | runs | on failure | repair unit |
|---|---|---|---|---|---|---|
| **provision** | "what does *good* mean?" | golden evidence bundle from `golden/` | per target | before everything (provision partition) | escalate (config) | n/a — it *defines* repair's reference |
| **readiness** | "can we even ask?" | config/binary existence checks | per protocol | first verdict, every episode | escalate (config) | n/a |
| **L1a** | "has any baseline file drifted?" | whole-file hashes | file | always (episode start) | refine via L2 | whole file |
| **L1b** | "are contract blocks in editable files intact?" | marker-range content | block | always (episode start) | repair directly | block splice |
| **L2** | "*where* in the drifted files — and is it invariant content?" | line-range content | contract clause | **only on L1a failure** | repair (whole-file) | — (guides L1a repair) |
| **L3** (validation) | "does the system still *mean* what the contracts say?" | tool exit codes (tipe/logika/test) | module/behavior | on L1a pass, opt-in | escalate | none — semantic failures aren't file-restorable |
| **repair KSs** | "make live match gold" | (actuation, not evidence) | = the tier's unit | on confirmed violation | exhaust → repaired-pending | — |

Note the deliberate diagonal: **granularity refines downward, cost rises rightward, and the repair unit always equals the measurement unit of the layer that triggers it.**

## Layer by layer

**Provisioning** is the *semantic ground*: it turns files in `golden/` into golden evidence (`golden_b64` per target). Every other layer's "pass" means "matches what provisioning declared." Its trust property is directional: it reads only `golden/`, written only by out-of-band acts — so no downstream failure can redefine "good." Boundary: it says nothing about the live system.

**Readiness** is *apparatus* attestation, not target attestation: ids resolve, configs complete, goldens provisioned, binaries executable. Its role in the tree is to spend the first dispatch on the config-vs-integrity distinction, so misconfiguration escalates as misconfiguration. Boundary: shallow by design — "can run," not "will produce sound evidence" (deeper CVM-tools checks are its marked extension point). It's also the *linkage* layer: its on_pass starter writes the measurement entries.

**L1a — the baseline screen.** Owns the four files whose *whole content* is baseline-fixed: the two AADL models (immutable by deployment policy) and the two GumboX oracles (immutable by paradigm — codegen overwrites). Its epistemic character: maximal sensitivity, zero diagnosis — one flipped byte anywhere fails the hash, but the verdict can't say where, or whether it matters. That's the *point* of a screen: cheap, complete-over-its-files, conservative. Boundaries: blind to the two component files (correctly — hashing editable files would false-alarm), and blind to *significance* (benign vs violation), which is exactly the judgment it delegates to L2. Repair pairing: whole-file restore — the only repair that can ever return an L1a hash to pass.

**L1b — the contract-block sentinel.** Owns the six codegen-managed `BEGIN/END` blocks inside files that are otherwise legitimately in developer motion. It's the layer your redesign *created*, and its role is structural: it covers precisely the invariant content the screen structurally cannot. Two properties distinguish it from L1a: it's **already at terminal granularity** (the block is both the measurement and the diagnosis — there is no "deeper dive," which is why slimming L2 is coherent), and it must read *content by markers*, not hash whole files, because everything around the blocks is allowed to change. Repair pairing: splice the block — and *only* the block, because the surrounding file is developer property.

**L2 — the refiner (and adjudicator).** Runs only when L1a has flagged drift, and answers two fused questions: *attribution* (which contract clause / oracle predicate changed — the forensic record) and *adjudication* (was the drift confined to non-invariant content?). The second role is the subtle one: an L2 pass after an L1a failure is the system's mechanism of **tolerance** — "drifted, but not in declared-invariant content" ends in good standing and is simultaneously the standing signal to re-provision. In the new design L2 is finally *pure*: all 22 targets refine L1a files, nothing more. Boundaries: coverage is only 3–20% of those files' lines (that's what makes tolerance possible); and it renders judgment but takes no action — repair sits behind it on the chain, firing only when L2 confirms violation.

**L3 — the semantic layer.** Different *axis*, not deeper on the same one: L1a/L1b/L2 all check "text equals gold" (syntactic identity); L3 checks "the meaning holds" — the contracts type-check, Logika proves the oracle predicates, randomized tests pass. It measures zero bytes; its evidence is behavior of the toolchain over the *live* project. This is why it confirms rather than screens (expensive, minutes), why it's the only layer that can catch what byte-identity can't (a world where identical text no longer verifies — toolchain drift, or tampering the system was never provisioned to watch), and why **no file-restore can repair it**: an L3 failure after clean L1a/L1b means the problem isn't drift, so escalation to a human is genuinely the right terminal. Boundary in the other direction: L3 passing says nothing about baseline identity — a rewritten-but-still-verifying system sails through it, which is why it can never replace the integrity layers.

**Repair** is *actuation*, not evidence — the layer that closes the loop from judgment back to the live tree, in the one permitted direction (golden → live). Its defining discipline is the unit-match rule (whole-file for L1a, block for L1b) and its defining humility is that it **cannot mint trust**: it acts, exhausts, and the entry parks as repaired-pending; only the next episode's fresh L1a/L1b evidence converts "repaired" into "verified." Boundaries: nothing without a filepath (signatures), nothing L3-shaped, and never a write to gold.

## The two questions the entry structure now encodes

- **`gumbo:files`** = "is the *baseline* intact?" — L1a screen, L2 refinement/tolerance, L3 confirmation, whole-file repair.
- **`gumbo:contracts`** = "are the *contracts in living code* intact?" — L1b sentinel, slice repair, no refinement needed.

Plus the two pre-layers (`provision:*`, `gumbo:ready`) asking "what is good?" and "can we ask?". Each entry spends its single dispatch on exactly its own question — the one-branch-point-per-entry rule that shaped this whole design.

One naming observation before we build: "L1a/L1b/L2" now encodes *history* more than structure — L1b is not a variant of L1a (different files, different granularity, different repair), and L2 is L1a's refiner only. If you ever want names that carry the roles, something like `baseline` / `blocks` / `refine` / `semantic` would let the code read the way this table does. Happy to keep the L-names for continuity with the protocol lineage — your call when we get to the protocol-authoring step.

## User

Let's revisit the gaps

## Assistant

Revisiting the five gaps with the layer roles now sharp — the layer analysis actually *changes* my recommendation on one of them (Gap 3) and firms up the others.

## Gap 1 — the starter wiring (two episodes, one chain)

Unchanged diagnosis: `on_pass=[starterA, starterB]` only ever runs the chain head — chains advance on failure, and readiness re-passes. The layer discussion confirms the fix belongs in the *linkage* role of readiness: **one readiness entry validating all four protocols, one starter rung writing all measurement entries**:

```python
StartAttestationKS(episodes={"gumbo:files": "gumbo_l1a", "gumbo:contracts": "gumbo_l1b"})
```

Idempotency per key, as today. Per-entry readiness entries stay rejected (doubled bookkeeping, no added information). **Status: resolved, mechanical.**

## Gap 2 — "repaired, pending verification" lands in escalate

The layer roles give this a cleaner justification than I offered before. Repair *cannot mint trust* — so an episode that repaired has, by definition, done everything its own machinery can do; what remains requires action from outside the episode. That is exactly what the escalate segment means, if we state its meaning honestly: **"terminal for this episode; external action required"** — where the external actor is *usually* a human but here is *the next episode*. So: keep the mechanics, upgrade the vocabulary. `trust_summary` distinguishes the two escalation species by inspecting `ks_history`: a repair rung present → "repaired from golden — verification pending next episode (re-run the workflow)"; absent → "user intervention required" as today.

I did consider the alternative our own precedent suggests — we added a *provision* partition for a similar semantic mismatch, so a "pending" segment is thinkable. I recommend against it for v1: partition proliferation is real complexity, and unlike provision requests (which needed different *evaluation* semantics), repaired-pending entries need only different *reporting*. **Status: resolved — summary vocabulary + two-episode demo; revisit a dedicated segment only if a resident deployment ever needs machine-readable pending state.**

## Gap 3 — repair scope on mixed drift (recommendation changed)

The layer analysis settles this one against my earlier lean. L2's role is *adjudication* — and adjudication is **per-file**: from L2's slice verdicts you can classify every L1a-failing file as *confirmed-violated* (≥1 failing slice) or *benign drift* (all its slices pass). The F4 path already promises benign drift is tolerated. If repair then restored *all* L1a-failing files whenever any one file was violated, tolerance would become incoherent — the same benign edit survives or dies depending on whether an unrelated file was attacked. The consistent semantics is:

> **Whole-file repair restores exactly the files L2 confirmed violated.** Benign-drift files stay tolerated (and keep signaling for re-provisioning), in every path, unconditionally.

Mechanically this means the repair KS reads the L2 verdict from history (the memo quirk hands it the L1a verdict as `entry.result`; history access is available to every KS and is legitimate blackboard idiom), with a defensive fallback to the L1a failing-file list if no L2 verdict exists. **Status: resolved — confirmed-violated files only.**

## Gap 4 — unrepairable failures and the unguarded KS loop

Unchanged: repair KSs catch everything internally, restore best-effort, and let exhaust-→-escalate carry the record ("N restored, M unrestorable" derivable from history plus the summary line). The wider question — should the *controller* wrap `ks.execute` in a guard so no KS can ever crash a run — is genuine core hardening, but it changes failure semantics for every KS and deserves its own small decision; I'd note it as a follow-up rather than smuggle it into this change. One layer-informed addition: a failure with no filepath (e.g. `sig_appr`) is *L3-shaped* — not drift, not restorable — and the summary should say so rather than just "unrepairable." **Status: resolved for v1 (KS-internal), controller guard logged as future hardening.**

## Gap 5 — episodes can't see each other

Unchanged in substance: the demo owns the cross-episode narrative (episode 1: violated → attributed → repaired; episode 2: verified clean), and a persistent audit trail is explicitly future work tied to the resident-deployment question. One new observation from the layer table: the *provisioning* layer already leaves durable traces (`golden_ts`, `_bundles/`); if we ever want minimal repair durability before building real persistence, a repair log written next to the golden tree would be the analogous cheap artifact — noted, not proposed for v1. **Status: accepted boundary, demo-narrated.**

## One gap-adjacent decision the layer discussion resolved

`--validate` placement: attach the L3 confirmation rung to **both** entries' `on_pass` chains. L3 is a different evidence axis (semantic), so it confirms L1b passes as meaningfully as L1a passes — and memoization makes the second attachment free (one validation run per episode regardless). If validation fails, both entries escalate with the same verdict — duplicated but honest, and the summary can coalesce.

## Consolidated decisions awaiting your sign-off

1. **Protocol names**: `gumbo_l1a` / `gumbo_l1b` / `gumbo_l2` (continuity), or role names (`gumbo_baseline` / `gumbo_blocks` / `gumbo_refine`)?
2. **Gap 2**: escalate-with-vocabulary (recommended) — confirm.
3. **Gap 3**: restore only L2-confirmed-violated files (recommended) — confirm.
4. **Validation on both entries** under `--validate` — confirm.

Plus one implementation note that fell out of the analysis, worth having on record before planning: the L1b/L2 split is a **pure partition of already-provisioned targets** — moving the six component targets (with their existing `golden_b64` values) out of `gumbo_l2` into a new `gumbo_l1b`, and `gumbo_l1a` is `gumbo_l1` unchanged — so the split requires **no re-provisioning**; readiness will verify the moved goldens are intact, and the provision partition stands by if we ever want to regenerate from scratch. Give me the four decisions and I'll write the full implementation plan.

## User

names l1a etc fine, 2 fine, 3 fine, 4 fine

## Assistant

All four locked in. Here's the implementation plan — I propose landing it as **two commits**: first the protocol split (which closes the coverage gap and is independently verifiable), then the repair layer on top.

## Commit 1 — protocol decomposition: `gumbo_l1a` / `gumbo_l1b` / slim `gumbo_l2`

1. **Author the fixtures** (script-generated, following the existing term structure `lseq(lseq(bseq_chain, SIG), APPR)`):
   - `gumbo_l1a/` = `gumbo_l1` renamed: same 4 whole-file hash targets, same goldens, prebuilt `cvm_request.json` kept (still valid — keeps the prebuilt code path covered).
   - `gumbo_l1b/` = new: the 6 `readfile_marker_range` component-block targets **moved out of l2 with their existing `golden_b64` values** — arrives pre-provisioned; session/manifest trimmed to marker+sig ASPs; meta updated.
   - `gumbo_l2/` = slimmed to the 22 line-range targets (all inside l1a's files); meta updated to state its role: refinement of l1a failures.
   - No re-provisioning needed (pure partition of provisioned targets); readiness will verify, and a quick CVM run of each confirms clean passes (4 / 6 / 22 components + sig).
2. **Rewire** the example and tests: readiness checks all four ids; multi-episode starter `StartAttestationKS(episodes={"gumbo:files": "gumbo_l1a", "gumbo:contracts": "gumbo_l1b"})` (Gap 1 fix — the KS gains an `episodes` dict, replacing `key`/`start`); routes as designed; `--validate` attaches the shared validation rung to both entries' `on_pass`.
3. **New demo flag + gap-closure proof**: `--tamper-block` corrupts a component contract block — under the *old* tree provably undetected; now `gumbo:files` passes while `gumbo:contracts` fails and escalates with block-level attribution. Integration test pins exactly this. Existing `--tamper` keeps its meaning (AADL contract line → files entry → l2 attribution).
4. Update `provision_workflow.py` (three provisionable protocols, 4/6/22 counts), conftest fixture names, `test_copland` counts.

## Commit 2 — the repair layer (`pybb/attestation/repair.py`)

1. **`WholeFileRestoreKS(golden_root, refined_by="gumbo_l2")`** — on the files entry's fail chain after the l2 rung. Reads the l2 verdict from history (the memo quirk hands it the l1a verdict as `entry.result` — used as the defensive fallback), classifies each l1a-failing file per-file (Gap 3: **restores only files with ≥1 failing l2 slice**; benign-drift files stay tolerated unconditionally), copies golden mirrors whole. All I/O per-file in `try/except` (Gap 4); never raises; prints what it restored.
2. **`SliceRestoreKS(golden_root)`** — on the contracts entry's fail chain. For each failing marker-block component: locate `begin/end` markers in both golden and live file, splice the golden block in, touch nothing else; markers missing in live → recorded unrestorable, no crash.
3. **`trust_summary`** (Gap 2 vocabulary): an escalated entry whose `ks_history` contains a `repair:*` rung renders as *"repaired from golden — verification pending next episode (re-run the workflow)"*; without one, "user intervention required" as today; filepath-less failures noted as not drift-repairable.
4. **Two-episode demo** (Gaps 2+5): with `--repair`, the example runs episode 1 (detect → attribute → repair → repaired-pending), then constructs a *fresh* controller/predicates in-process and runs episode 2, printing the verified-clean confirmation. Repair rungs are gated behind `--repair` so the plain `--tamper` escalation demo keeps its current meaning. The end-of-run golden-restore safety net stays for un-repaired tampers.
5. **Tests**: unit — mixed-drift scope (benign file untouched, violated file restored), no-l2-verdict fallback, marker-splice precision (only the block changes), unrepairable paths never raise; integration (real CVM) — AADL-contract tamper `--repair`-style flow ending clean in episode 2, and block tamper → slice restore → episode 2 clean.
6. **README**: the layer-roles table from our discussion, the amended tree, repair semantics (unit-match rule, confirmed-only scope, repaired-pending vocabulary, re-provisioning as the sanctioned path for legitimate edits).

Both commits verified against the full suite plus all example modes; push after each. Proceed?

## User

go

## Assistant

> `[Bash]` Inspect l2 term/session/manifest structure

> `[Write]` /private/tmp/claude-501/-Users-adampetz-Claude-workspace/e6b8cfa3-8349-4e22-8f47-cbd66ed00252/scratchpad/split_protocols.py

> `[Bash]` Generate split protocol fixtures

> `[Bash]` Attest all three split protocols against real CVM

All three attest clean — 5/7/23 components, goldens intact through the split. Now the code updates. First check `test_appraisal`'s fixture usage:

> `[Bash]` Find all references to old gumbo_l1 protocol id

`test_appraisal` is unaffected. Now the `StartAttestationKS` generalization (Gap 1 fix):

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/knowledge_sources.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/readiness.py

Now rewrite the example's core for the two-entry design:

> `[Read]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Write]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

Now the test updates — conftest, copland counts, and the three integration files:

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/conftest.py

> `[Bash]` Rename fixtures in test_copland, find count assertions

> `[Bash]` Update l2 counts and add l1b count check

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_copland.py

Now `test_integration_cvm.py` — rename ids and add the gap-closure block-tamper test:

> `[Read]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_cvm.py

Now the sireum test, provision integration test, and the two provisioning-related examples:

> `[Bash]` Update protocol ids in sireum and provision integration tests

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_provision.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_provision.py

> `[Bash]` Update remaining protocol id references

> `[Bash]` Run full suite: unit then CVM integration

> `[Bash]` Run clean, block-tamper, and AADL-tamper demos

> `[Bash]` Verify provision workflow, commit protocol split, push

Commit 1 is in (`2830550`, pushed). Now Commit 2 — the repair layer:

> `[Write]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/repair.py

Now exports and the `trust_summary` repaired-pending vocabulary:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/__init__.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/summary.py

Now the example gains `--repair` and the two-episode flow:

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/examples/gumbo_attestation.py

Now the repair unit tests:

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/test_repair.py

> `[Bash]` Run repair unit tests

> `[Bash]` Debug refinement verdict history lookup

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/repair.py

> `[Bash]` Re-run repair tests then full unit suite

> `[Write]` /Users/adampetz/Claude_workspace/pybb/tests/test_integration_repair.py

> `[Bash]` Run repair integration tests against real CVM

Integration passes. Now the demo:

> `[Bash]` Run both repair demos, two episodes each

Both repair flows verified end to end. Now the README updates:

> `[Bash]` Map README section layout

> `[Bash]` Map README sections and stale references

> `[Read]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Bash]` Fix provision example id, locate modules section

> `[Edit]` /Users/adampetz/Claude_workspace/pybb/pybb/attestation/README.md

> `[Bash]` Full suite, commit repair layer, push

Both commits are in and pushed. Updating project memory:

> `[Edit]` /Users/adampetz/.claude/projects/-Users-adampetz-Claude-workspace/memory/project_pybb_attestation.md

Done — both commits landed on `dev` and pushed. The full picture:

## Commit 1 — `2830550`: the tier decomposition

- **Fixtures**: `gumbo_l1a` (the old l1: 4 whole-file hashes, prebuilt kept), **`gumbo_l1b`** (new: the 6 component contract blocks, goldens moved intact), `gumbo_l2` slimmed to 22 slices — generated by a script whose chain-builder proved itself by reproducing the original 28-node term byte-for-byte, then verified live: all three attest clean (5/7/23 components), **no re-provisioning needed**.
- **Wiring**: two always-run entries started by the generalized `StartAttestationKS(episodes={...})` (Gap 1 fix); `--validate` attaches the shared semantic rung to both.
- **Gap closure proven twice**: an integration test and the `--tamper-block` demo both show a contract-block tamper that the old tree provably missed — `gumbo:files` passes honestly while `gumbo:contracts` escalates naming `tc_comp_compute_ens_targ`.

## Commit 2 — `b2ee15d`: the repair layer

- **[repair.py](pybb/pybb/attestation/repair.py)**: `WholeFileRestoreKS` (restores only l2-confirmed-violated files — the mixed-drift unit test proves a benign edit survives while the violated file converges to gold) and `SliceRestoreKS` (splices only the violated block — developer edits outside it preserved). Neither raises; unrestorable items go to the report.
- **Repaired-pending vocabulary** in `trust_summary`, and the **two-episode demo**: episode 1 ends "repaired from golden — verification pending next episode"; episode 2 (fresh predicates) verifies clean. Both flows exercised against the real CVM in integration tests and demos — AADL tamper via whole-file restore, block tamper via slice splice, live tree byte-identical to gold afterward.
- One real bug caught by the tests: `refine if refine else fallback` silently discarded the refinement verdict *exactly when repair had work to do* — `Verdict.__bool__` is the appraisal outcome, not presence. Now tested with `is None` and commented.

Full suite: **68 passed, 2 skipped**. The architecture now runs the complete arc end to end: readiness → provisioning from golden → two-question attestation (baseline + living-code contracts) → refinement/tolerance → class-correct repair → next-episode verification.

## User

Is it possible for repair to overwrite benign changes to files in this new workflow?

## Assistant

Yes — in exactly one scenario, and it's worth being precise about it, because the boundary is load-bearing. Let me enumerate all the cases:

## Where benign changes are safe

- **Benign-only files are never touched.** Per-file adjudication: a file whose l1a hash fails but whose l2 slices all pass is classified benign drift, repair skips it unconditionally, and the episode tolerates it ("clean at finer granularity"). This is pinned by `test_whole_file_restores_only_confirmed_violations` — the benign file's edit survives even while a *different* violated file gets restored in the same repair action.
- **Component-file edits outside contract blocks are never touched.** `SliceRestoreKS` splices only the marker-delimited span; the unit test proves a developer edit elsewhere in the file survives the splice. (Inside a block there is no "benign" category — blocks are codegen-managed invariant content; any drift there *is* a violation by definition.)

## Where benign changes are overwritten

**A benign edit co-located in the same file as a confirmed violation.** File `X.aadl` has a harmless comment edit at line 50 *and* a tampered invariant at line 306: l2 confirms `X` violated → `WholeFileRestoreKS` restores the *whole* file → the line-50 edit is gone. Since l2 measures only 3–7% of an AADL file, the reverted region is mostly unmeasured content.

I'd defend this as correct rather than merely tolerable, on security grounds: once a file contains a **confirmed violation**, its unmeasured drift no longer deserves the "benign" label — you can't distinguish an innocent comment from an attacker's staging in content nothing measures, and they arrived in the same compromised file. Conservative full revert of a compromised artifact is standard incident practice, and it's also the only repair that converges the whole-file hash back to gold. The sanctioned recovery path for the legitimate edit is unchanged: re-apply it and re-provision.

## Two caveats worth having on the record

1. **The fallback path is broader.** If `WholeFileRestoreKS` finds no l2 verdict in history, it falls back to restoring *all* l1a-failing files — including purely-benign ones. Under canonical wiring this can't happen (the repair rung sits *after* the l2 rung, so the refinement verdict always exists by the time repair fires). It only bites if someone wires `on_fail=[WholeFileRestoreKS]` without the refinement rung ahead of it. That's currently a documented-by-convention wiring rule, not an enforced one.

2. **Overwritten bytes are gone forever.** The live tree isn't git-tracked, and repair copies gold over live with no backup — destroying both the benign edit *and* the forensic evidence of the tamper itself (the l2 attribution survives in history, but the actual tampered bytes don't). A cheap improvement if you want it: repair stashes the pre-repair file to a quarantine directory (e.g. `golden/_quarantine/<timestamp>/...`) before overwriting — preserving the developer's edit for recovery *and* the tampered content for forensics, without changing any trust semantics since quarantine is write-only from repair's perspective.

So: across files, never; outside blocks, never; inside a confirmed-violated file, yes and deliberately — with the quarantine idea available if you want "deliberately, but recoverably." Want me to add it?

## User

Eventually I'd like to have meaningful changes to the AADL file trigger a re-run of HAMR AND a re-provisioning.  How does this change the picture?

## Assistant

This is the question that turns the architecture from a *tamper detector* into a *lifecycle manager* — and the striking thing is how much of the picture doesn't change, because the golden-directory design has been quietly pointing here all along. But it also exposes one genuine missing capability. Let me lay it out.

## The conceptual inversion

Today, every change is presumed attack: gold is fixed, live drift is either tolerated or reverted. With a sanctioned change pipeline, AADL edits split into two kinds with opposite fates:

- **Unauthorized drift** — what attestation exists to catch. Handled exactly as today.
- **Authorized change** — a *promotion event*: AADL edit → HAMR rerun → regenerated GumboX oracles + refreshed contract blocks → new baseline → re-provision → live converges to the *new* gold.

The trust question shifts from "does live equal gold?" to "**is live at the current baseline, where the baseline moves only through the sanctioned channel?**" Gold becomes a versioned, moving reference instead of a frozen one.

## The one non-negotiable: promotion must be gold-first

There's a tempting wrong shape here: developer edits *live*, the system notices "meaningful" drift, asks someone, then re-provisions *from live*. That is precisely the laundering path this architecture was built to make impossible — re-provisioning from a tree that just failed appraisal is indistinguishable from an attacker's dream, and no measurement can tell an intended edit from a disguised one. The trust boundary survives contact with this feature only in the **gold-first** form: the edit, the HAMR rerun, and the validation all happen on the *gold/staging side*; gold is written only by that pipeline (a genuine "external event" — the exact scenario the provision partition was designed around); and live never becomes a provisioning source. Conveniently, you already have a staging candidate in the repo: `targets/temp-control-jvm` could become the authoring workspace where HAMR reruns.

## The elegant consequence: repair *is* deployment

Once gold moves ahead of live, look at what the existing machinery does, unmodified: provisioning succeeds against new gold → live attestation *fails* (live is behind) → l2 attributes the delta to exactly the changed contracts → repair "restores" live from gold — **which is now the deployment of the update** → episode 2 verifies live at the new baseline. The `--tamper-golden` demo already exercised the detection half of this; adding repair completes a self-updating loop. Update and repair become one mechanism distinguished only by *why* gold moved — which is exactly right, because both are "converge live to current gold." Even `SliceRestoreKS` gets a second life: promotion needs to install *new* contract blocks into developer-owned component files without touching developer code — that's the block splice running in promotion's service.

## What genuinely changes / is missing

1. **Target-map regeneration — the real gap.** Our provision partition refreshes golden *values* for **fixed** targets. A meaningful AADL edit shifts line numbers: l2's `305–308` ranges and the slice map itself become wrong, not just stale. Full re-provisioning must regenerate the *target definitions* (asp_args ranges/markers, terms) from a fresh HAMR attestation report — cvm-mcp's `hamr_report_protocols.py` territory (it already does this for isolette). This is the piece the current blackboard provisioning cannot do, and the first thing to build when you go here.
2. **A codegen stage** — HAMR rerun as part of gold production (out-of-band script first, à la `capture_golden.py`; conceivably a blackboard activity later — the `sireum-hamr` tooling is even MCP-reachable from this environment).
3. **A derivation-consistency check** — new check class for readiness/validation: *is golden GumboX actually `HAMR(golden AADL)`?* Without it, a partial promotion (AADL updated, oracles stale) creates a self-inconsistent baseline that attestation would happily enforce.
4. **Validation as promotion gate** — L3 gains a second role: tipe/logika/test must pass on staging *before* gold is declared, not just confirm live afterward. "Gold must verify" becomes part of what provisioning means.
5. **Component-file promotion is a merge** — gold's component-file copies contain developer content that evolves on the live side; promotion must combine *new blocks* with *current developer code* (block-splice toward live), not blind-copy.

## Effect on the questions we just settled

The benign-drift story gets *cleaner*: tolerance existed largely because legitimate edits had no sanctioned channel. With cheap promotion, lingering benign drift in live becomes rarer and more suspicious, and you could eventually tighten to strict baseline enforcement (any drift → repair) — resolving the co-located-benign-edit concern by making "just promote it" the easy path. And the episodic model maps directly onto the lifecycle: promotion is a *sequence of episodes* (provision → attest/detect-behind → repair/deploy → verify), no resident machinery required.

**Net:** the picture doesn't invert — it completes. Detection, provisioning, repair, tolerance, and the trust boundary all keep their roles; what's new is a gold-side production pipeline (codegen + validation gate + consistency check) and, critically, **provisioning that can regenerate target maps, not just golden values**. If and when you want to start, that target-regeneration capability is the keystone piece — everything else composes from primitives already on the board.

## User

Give me a high-level summary of HAMR measurement targets, and also a summary of blackboard partitions and predicates and how they measure those targets.

## Assistant

Here's the consolidated reference, in two halves.

## Part 1 — HAMR measurement targets (temp-control-jvm)

HAMR's build model creates **three classes of artifact with different mutability**, and the measurement targets follow that taxonomy exactly:

| artifact class | files | HAMR's own declaration | what is invariant |
|---|---|---|---|
| **AADL models** (design source) | `TempControlSystem.aadl` (312 ln), `TempSensor.aadl` (126 ln) | developer-edited source; baseline-fixed *by policy* once provisioned | whole file (policy) + the 9 GUMBO clause ranges (~27 lines: `assume` port contracts, data invariants) as the declared-invariant core |
| **GumboX oracles** (codegen output) | 2 `*_GumboX.scala` (296 + 83 ln) | *"Do not edit — will be overwritten if HAMR codegen is rerun"* | the entire file (paradigm-immutable), incl. 13 `@strictpure` predicate ranges |
| **Component files** (developer code) | 2 `*_tempControl/tempSensor.scala` | *"will not be overwritten so is safe to edit"* | **only** the 6 codegen-managed `BEGIN/END` contract blocks (state vars, initializes/compute modifies/ensures) |
| **The Slang project** (semantic) | whole `slang/` tree | — | not bytes at all: that it type-checks, its contracts prove (Logika), and its GumboX unit tests pass |

These 38 concrete targets are packaged into four protocols, each with **repair unit = measurement unit**:

- **`gumbo_l1a`** — 4 whole-file hashes (AADL + oracles). Baseline screen; repair = whole-file restore.
- **`gumbo_l1b`** — 6 marker-range block reads (component files). Terminal-granularity sentinel; repair = block splice.
- **`gumbo_l2`** — 22 line-range reads, all *inside* l1a's files. Refinement of an l1a failure: attributes drift to contract content, or clears it as benign.
- **`gumbo_validation`** — 5 commands (tipe, logika ×2, test ×2). Semantic axis; no byte targets, no file repair possible.

Every target has a **golden value** (hash or content slice, `golden_b64`) provisioned from the golden directory — the clean mirror of all six files that is the single source of "what good means."

## Part 2 — Blackboard partitions, predicates, and how they measure the targets

The blackboard has **three segments**, each governed differently, plus the per-KS partitions (a KS's assigned keys — populated only by dispatch):

| partition | holds | governed by | relationship to targets |
|---|---|---|---|
| **provision** | requests written by external events (files landed in `golden/`) | the `provision` predicate only — evaluated **before** certify each cycle, no KS chains | measures the **golden copies** of the targets |
| **certify** | trust questions under active judgment | predicates + routed KS chains | measures the **live** targets |
| **escalate** | terminal outcomes needing external action | humans (or the next episode) | holds the failure/repair reports about targets |

Three **named predicates** do all the measuring — each one memoized per lifetime, so every question is answered at most once per episode:

1. **`provision`** (`provision:gumbo_l1a/l1b/l2` entries) — *"what does good mean?"* Runs each protocol's measurement-only term (APPR stripped) via the CVM **against the golden copies, never live**, writes the evidence bundle, extracts per-target `golden_b64`, installs them into the shared protocol configs. Success rests in the partition as the record of provisioned state; failure escalates as a config failure.
2. **`protocol_check`** (`gumbo:ready` entry) — *"can we ask?"* Measures the **apparatus**, not the targets: ids resolve, configs complete, every target has a golden, CVM/ASP binaries present. Its pass triggers the starter rung that writes the attestation entries; its failure escalates as configuration, before any target is touched.
3. **`attestation`** (`gumbo:files` and `gumbo:contracts` entries) — *"is live at baseline?"* Runs the protocol named in the entry's measurement against the **live tree**, appraises each component against its golden, returns a per-target `Verdict`.

The **routes** then move each entry through the target hierarchy on its own single branch point:

```
gumbo:files      l1a (4 whole files)
                   pass → [--validate: gumbo_validation confirms semantically]
                   fail → l2 (22 slices): pass = benign drift, tolerated
                                          fail → WholeFileRestoreKS restores the
                                                 confirmed-violated files from gold
gumbo:contracts  l1b (6 blocks)
                   pass → done [or validation]
                   fail → SliceRestoreKS splices the violated blocks from gold
```

Repair rungs act in the one permitted direction (gold → live), cannot mint trust, and land the entry in escalate as *"repaired from golden — verification pending next episode"*; the next episode's fresh predicates re-measure everything and convert repaired into verified.

**The whole system in one sentence:** the golden directory defines the targets' good state; the provision partition turns golden files into golden evidence; readiness proves the machinery can measure; the certify entries measure the live targets at file, block, slice, and semantic granularity; routes refine, tolerate, confirm, or repair per artifact class; and escalate holds whatever a human — or the next episode — must resolve.

## User

please export this claude session to a markdown file

## Assistant

I'll locate this session's transcript and convert it to markdown. The workspace has an established `claude_sessions/` directory — I'll export there.

> `[Bash]` Locate session transcript and check export directory

> `[Write]` /private/tmp/claude-501/-Users-adampetz-Claude-workspace/e6b8cfa3-8349-4e22-8f47-cbd66ed00252/scratchpad/export_session.py

> `[Bash]` Run export and verify output
