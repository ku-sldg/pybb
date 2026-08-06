from typing import Callable, Optional

from pydantic import BaseModel, Field

from .blackboard import Blackboard
from .knowledge_source import KnowledgeSource

class Route(BaseModel):
    """Outcome-routed KS chains for one entry key.

    on_fail: chain tried when the entry evaluates out of good standing (the
             classic repair ladder; route(key, chain) is shorthand for this).
    on_pass: confirmation chain tried once when the entry evaluates as
             passing -- the pass is provisional until the chain's work
             re-evaluates. Empty means a pass is final.
    """
    on_pass: list[KnowledgeSource] = []
    on_fail: list[KnowledgeSource] = []

    model_config = {"arbitrary_types_allowed": True}

class BlackboardController(BaseModel):
    """
    for each cycle:
      0. process restart requests (restart-episode primitive): each requested
         key gets a FRESH episode — predicate memo forgotten for its episode
         measurements, entry reset to its original measurement with a fresh KS
         budget, dispatch latch and chain partitions cleared. requests are
         written by knowledge sources (pull-only; the controller never
         initiates) and capped per key by max_restarts_per_key
      1. eval all entries: provision partition FIRST, then certify
        a. run predicate (or component conditions) from registry
        b. set good_standing based on result
        c. a provision request that evaluated and failed moves straight to
           the escalate segment (no KS chains for the provision partition);
           a passing one stays as the record of provisioned state
      2. dispatch each routed key onto a chain once its first result exists
        a. failing entry -> its route's on_fail chain
        b. passing entry with an on_pass chain -> that chain (standing cleared;
           the pass is provisional until re-evaluation after the chain runs)
        c. the chosen chain's first KS receives the key in its partition
      3. success-driven handoff for component-scoped KSes (_advance_ready)
      4. run all KS that can_contribute on their bad keys
         a. a KS that exhausted max_attempts on a key hands it to the next KS
            in the dispatched chain (measurement restored); when no KS remains
            the entry moves to the escalate segment
    stop when no KS can contribute or max_cycles is reached.
    """

    blackboard: Blackboard = Field(default_factory=Blackboard)
    knowledge_sources: list[KnowledgeSource] = []
    predicate_registry: dict[str, Callable] = {}
    routes: dict[str, Route] = {} # entry key -> outcome-routed KS chains (controller-owned)
    dispatched: dict[str, list[KnowledgeSource]] = {} # entry key -> chain chosen by first evaluated outcome
    max_cycles: int = 100
    max_restarts_per_key: int = 10 # halting safety net for restart requests; requesters' own budgets are policy, this cap is law
    cycle_count: int = 0

    model_config = {"arbitrary_types_allowed": True}

    def register_predicate(self, name: str, fn: Callable) -> None:
        self.predicate_registry[name] = fn

    def add_ks(self, ks: KnowledgeSource) -> None:
        self.knowledge_sources.append(ks)

    def route(self, key: str, ks_chain: Optional[list[KnowledgeSource]] = None, *,
              on_pass: Optional[list[KnowledgeSource]] = None,
              on_fail: Optional[list[KnowledgeSource]] = None) -> None:
        """register outcome-routed chains for key. route(key, chain) is shorthand for
        route(key, on_fail=chain). placement onto a chain (_dispatch) happens after the
        entry's first evaluation, since the branch depends on the outcome"""
        if ks_chain is not None:
            on_fail = ks_chain
        route = Route(on_pass=list(on_pass or []), on_fail=list(on_fail or []))
        self.routes[key] = route
        self.dispatched.pop(key, None)
        for ks in [*route.on_pass, *route.on_fail]:
            if key in ks.partition:
                ks.partition.remove(key)

    def _process_restarts(self) -> None:
        """open a fresh episode for each requested key (restart-episode primitive):
        forget the predicate's memoized verdicts for the entry's episode measurements,
        reset the entry to its original measurement with a fresh KS budget, clear the
        dispatch latch and chain partitions, and count the restart. runs at the TOP of
        the cycle so the fresh entry evaluates (re-attests) the same cycle. requests
        are PULL-ONLY (written by knowledge sources; the controller never initiates),
        capped per key by max_restarts_per_key regardless of who asks, and dropped
        stale when the entry has escalated or vanished"""
        for key, reason in list(self.blackboard.restart_requests.items()):
            del self.blackboard.restart_requests[key]
            entry = self.blackboard.entries.get(key)
            if entry is None:
                print(f"Cycle {self.cycle_count}: restart request for '{key}' dropped - no live certify entry")
                continue
            used = self.blackboard.restarts.get(key, 0)
            if used >= self.max_restarts_per_key:
                print(f"Cycle {self.cycle_count}: restart request for '{key}' dropped - max_restarts_per_key ({self.max_restarts_per_key}) reached")
                continue
            # memo invalidation: every measurement this entry used during the episode
            measurements = [entry.measurement, entry.original_measurement]
            measurements += [e.measurement for k, e in self.blackboard.history if k == key]
            fn = self.predicate_registry.get(entry.predicate) if entry.predicate else None
            forget = getattr(fn, "forget", None)
            if forget is not None:
                seen = set()
                for m in measurements:
                    marker = repr(m)
                    if marker not in seen:
                        seen.add(marker)
                        forget(m)
            self.blackboard.reset_entry(key)
            self.dispatched.pop(key, None)
            for ks in self.knowledge_sources:
                if key in ks.partition:
                    ks.partition.remove(key)
            self.blackboard.restarts[key] = used + 1
            note = f" ({reason})" if reason else ""
            print(f"Cycle {self.cycle_count}: restarting episode for '{key}'{note} - fresh measurement, fresh KS budget (episode {used + 2})")

    def _dispatch(self) -> None:
        """place each routed key onto a chain once its first verdict exists: failing ->
        on_fail; passing with a confirmation chain -> on_pass (standing cleared until the
        chain's work re-evaluates). one dispatch per key; escalate when the chain is empty"""
        for key in list(self.blackboard.entries):
            entry = self.blackboard.entries[key]
            route = self.routes.get(key)
            if route is None or key in self.dispatched or entry.result is None:
                continue
            if entry.good_standing:
                if not route.on_pass:
                    continue # pass is final
                chain = route.on_pass
                self.blackboard.set_entry(key, entry.model_copy(update={"good_standing": False}))
                print(f"Cycle {self.cycle_count}: '{key}' passed - dispatching to confirmation chain")
            else:
                chain = route.on_fail
                print(f"Cycle {self.cycle_count}: '{key}' failed - dispatching to on_fail chain")
            self.dispatched[key] = chain
            if chain:
                chain[0].partition.append(key)
            else:
                self.blackboard.escalate[key] = self.blackboard.entries.pop(key)
                print(f"Cycle {self.cycle_count}: no eligible KS for '{key}' - escalating with history")

    def _advance(self, key: str, current: KnowledgeSource, restore: bool = True) -> None:
        """move key to next eligible KS. restore=True (failure: current KS exhausted max attempts) restores the
        measurement current KS worked on; restore=False (success: current KS's component passed) preserves its work.
        moves to escalate if no available KS remains"""
        if key in current.partition:
            current.partition.remove(key)
        chain = self.dispatched.get(key, [])
        names = [ks.name for ks in chain]
        idx = names.index(current.name) if current.name in names else -1
        nxt = chain[idx + 1] if 0 <= idx and idx + 1 < len(chain) else None
        if nxt is not None:
            if restore:
                entry = self.blackboard.entries.get(key)
                if current.component is not None and entry is not None and isinstance(entry.measurement, dict):
                    self.blackboard.restore_component(key, current.component) # scoped restore keeps other components' fixes
                    print(f"Cycle {self.cycle_count}: '{current.name}' exhausted on '{key}' - restoring component '{current.component}', handing to '{nxt.name}'")
                else:
                    self.blackboard.restore_original(key)
                    print(f"Cycle {self.cycle_count}: '{current.name}' exhausted on '{key}' - restoring original measurement, handing to '{nxt.name}'")
            else:
                print(f"Cycle {self.cycle_count}: '{current.name}' satisfied component '{current.component}' on '{key}' - handing to '{nxt.name}'")
            nxt.partition.append(key)
        else:
            self.blackboard.escalate[key] = self.blackboard.entries.pop(key)
            print(f"Cycle {self.cycle_count}: no eligible KS left for '{key}' - escalating with history")

    def _advance_ready(self) -> None:
        """success-driven handoff: advance keys whose current component-scoped KS has satisfied its component"""
        for key, chain in list(self.dispatched.items()):
            entry = self.blackboard.entries.get(key)
            if entry is None or entry.good_standing or entry.conditions is None: # None covers already-escalated keys
                continue
            owner = next((ks for ks in chain if key in ks.partition), None)
            if owner is None or owner.component is None:
                continue
            if entry.component_good(owner.component):
                self._advance(key, owner, restore=False) # preserve the fix; escalates if no next KS

    def _evaluate_entry(self, key: str, partition: str = "certify") -> None:
        segment = self.blackboard.provision if partition == "provision" else self.blackboard.entries
        entry = segment.get(key)
        if entry is None:
            return
        if entry.conditions is not None:
            fns = {c: self.predicate_registry.get(p) for c, p in entry.conditions.items()}
            if any(fn is None for fn in fns.values()):
                return
            result = {c: bool(fn(entry.measurement.get(c))) for c, fn in fns.items()}
            good = all(result.values())
        else:
            if entry.predicate is None:
                return
            fn = self.predicate_registry.get(entry.predicate)
            if fn is None:
                return
            result = fn(entry.measurement)
            good = bool(result)
        self.blackboard.set_entry(key, entry.model_copy(update={"result": result, "good_standing": good}), partition=partition)

    def _evaluate_all(self) -> None:
        # provision requests evaluate before certify entries, so attestation
        # in the same cycle always sees freshly provisioned state; within
        # the partition, requests evaluate in write order (promotion before
        # the provisioning it enables — see request_promotion)
        for key in list(self.blackboard.provision):
            self._evaluate_entry(key, partition="provision")
        for key in list(self.blackboard.entries):
            self._evaluate_entry(key)

    def _escalate_failed_provision(self) -> None:
        """provision requests have no KS chains: first failure escalates with the outcome as report"""
        for key in list(self.blackboard.provision):
            entry = self.blackboard.provision[key]
            if entry.result is not None and not entry.good_standing:
                self.blackboard.escalate[key] = self.blackboard.provision.pop(key)
                print(f"Cycle {self.cycle_count}: provisioning request '{key}' failed - escalating")

    def run(self) -> Blackboard:
        for i in range(self.max_cycles):
            self.cycle_count = i + 1
            self._process_restarts()
            self._evaluate_all()
            self._escalate_failed_provision()
            self._dispatch()
            self._advance_ready()
            active = [ks for ks in self.knowledge_sources if ks.can_contribute(self.blackboard)]
            if not active:
                print(f"Cycle {self.cycle_count}: all entries in good standing - halting")
                break
            for ks in active:
                bad_keys = []
                print(f"Cycle {self.cycle_count}: running '{ks.name}'")
                for key in list(ks.partition): # snapshot of partition. _advance changes partitions
                    entry = self.blackboard.entries.get(key)
                    if entry is None or not ks._needs_work(entry):
                        continue
                    if ks.max_attempts is not None and entry.ks_history.get(ks.name, 0) >= ks.max_attempts:
                        self._advance(key, ks)
                    else:
                        self.blackboard.add_ks_history(key, ks.name)
                        bad_keys.append(key)
                ks.execute(self.blackboard, bad_keys)
        return self.blackboard

    def status(self) -> dict:
        return {
            "cycles_run": self.cycle_count,
            "entries": self.blackboard.get_all_entries()
        }
    
