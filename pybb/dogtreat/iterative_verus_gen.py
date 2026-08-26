import re
import sys
from enum import Enum
import hashlib
from pathlib import Path
import tempfile
import subprocess
from typing import Callable, Optional
from pydantic_ai import Agent
from pydantic import BaseModel 

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource


## Globals ##

log : list[str] = []

#############

## Helper Functions ##

def find_str_rows(verus_str: str, target_str: str) -> tuple[int, int]:
    """
    Find the start row number, and end row number of the first occurrence of target_str in verus_str.
    Row numbers are 1-indexed.
    If target_str is not found, return -1, -1.
    """
    start_row = verus_str.find(target_str)
    if start_row == -1:
        return -1, -1
    start_row = verus_str[:start_row].count("\n") + 1
    end_row = start_row + target_str.count("\n")
    return start_row, end_row

def find_pos_row(verus_str: str, target_pos: int) -> int:
    """
    Find the row number of the character at target_pos in verus_str.
    Row numbers are 1-indexed.
    If target_pos is out of bounds, return -1.
    """
    if target_pos < 0 or target_pos >= len(verus_str):
        return -1
    return verus_str[:target_pos].count("\n") + 1

def gen_tag_regex(tag: str) -> str:
    """
    Generate a regex pattern to match a Verus tag with the given tag name.
    The pattern will match the opening and closing tags, as well as any content in between.
    """
    return r'(?ms)<{tag}>[^\n]*\n(.*?)\n[^\n]*</{tag}>'.format(tag=tag)

def func_is_in(func_name: str, search_str : str) -> bool:
        func_regex = r'{func_name}\(.*\)'.format(func_name=func_name)
        return re.search(func_regex, search_str) is not None

def normalize_verus_statement(stmt: str) -> str:
    """
    Normalize a single-line Verus statement/expression for robust equality checks.
    Drops trailing semicolons, unwraps top-level assert/assume wrappers, and
    removes whitespace.
    """
    normalized = stmt.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1].strip()

    for wrapper in ("assert", "assume"):
        if normalized.startswith(wrapper):
            remainder = normalized[len(wrapper):].strip()
            if remainder.startswith("(") and remainder.endswith(")"):
                normalized = remainder[1:-1].strip()
            else:
                normalized = remainder
            break

    return re.sub(r"\s+", "", normalized)

def candidate_assumes_error(candidate: str, error_body: str) -> bool:
    """
    True when candidate is an assume statement whose inner predicate is the
    same as the current target error predicate.
    """
    if not candidate.strip().startswith("assume"):
        return False
    return normalize_verus_statement(candidate) == normalize_verus_statement(error_body)

def candidate_restates_error(candidate: str, error_body: str) -> bool:
    """
    True when candidate statement is equivalent to the current target error
    statement after normalization.
    """
    return normalize_verus_statement(candidate) == normalize_verus_statement(error_body)

def find_enclosing_scope(verus_str: str, target_row: int) -> tuple[int, int]:
    """
    Find the start and end row numbers of the enclosing scope of the target_row in verus_str.
    Row numbers are 1-indexed.
    If no enclosing scope is found, return -1, -1.
    """
    # Firstly find the position of the target_row in verus_str
    target_pos = verus_str.splitlines()[target_row - 1]
    target_pos = sum(len(line) + 1 for line in verus_str.splitlines()[:target_row - 1])  # +1 for the newline character

    # Now work backwards to find the opening brace
    open_scope_row = -1
    close_scope_row = -1
    brace_count = 0
    for i in range(target_pos, -1, -1):
        if verus_str[i] == '}':
            brace_count += 1
        elif verus_str[i] == '{':
            if brace_count == 0:
                open_scope_row = find_pos_row(verus_str, i)
                break
            else:
                brace_count -= 1

    # Now work forwards to find the closing brace
    brace_count = 0
    for i in range(target_pos, len(verus_str)):
        if verus_str[i] == '{':
            brace_count += 1
        elif verus_str[i] == '}':
            if brace_count == 0:
                close_scope_row = find_pos_row(verus_str, i)
                break
            else:
                brace_count -= 1

    return open_scope_row, close_scope_row

######################

## LLM Interaction ## 

class Instruction(BaseModel):
    instructions: str

class CandidateGen(BaseModel):
    candidates: list[str]

class LLMWrapper:
    def __init__(self, model_name: str = "openai:gpt-4.1", context: str = ""):
        self.model_name : str = model_name
        self.context : str = context

    def gen_instruction(self, loop_status : "RepairLoopStatus", prompt: str) -> str:
        agent = Agent(
            model=self.model_name, 
            output_type=Instruction,
            instructions="You are a helpful assistant that generates instructions for repairing Verus code based on the provided context and prompt."
        )
        prompt_instructions = "IMPORTANT NOTE: The instuctions should be CONCISE, and FOCUSED on ONLY providing instruction for how to prove the failed assertion."
        full_prompt = self.context + "\n" + prompt_instructions + "\n" + prompt

        loop_status.log_status("Generating Instruction", f"Full prompt for instruction generation:\n{full_prompt}")

        response = agent.run_sync(full_prompt)
        return response.output.instructions
    
    def gen_candidates(self, loop_status : "RepairLoopStatus", prompt: str) -> list[str]:
        agent = Agent(
            model=self.model_name, 
            output_type=CandidateGen,
            instructions="You generate a list of candidate Verus assume statements or proof calls based on the provided context and prompt, each candidate should be the equivalent of a single statement."      
        )
        prompt_instructions = "IMPORTANT NOTE: Each candidate should be a SINGLE statement, only ONE line, NO comments, NO extra text, NO newlines. FAVOR simpler statements first. Do NOT!!! assume the target error."
        full_prompt = self.context + "\n" + prompt_instructions + "\n" + prompt

        loop_status.log_status("Generating Candidates", f"Full prompt for candidate generation:\n{full_prompt}")

        response = agent.run_sync(full_prompt)
        candidates = response.output.candidates

        # Firstly ensure that there are no duplicate candidates
        candidates = list(dict.fromkeys(candidates))

        # Ensure no candidate is an assert statement, if so change it to an assume statement
        for i, candidate in enumerate(candidates):
            if candidate.strip().startswith("assert"):
                candidates[i] = "assume" + candidate.strip()[6:]

        # Ensure no candidate directly assumes the current working error.
        filtered_candidates: list[str] = []
        for candidate in candidates:
            if candidate_assumes_error(candidate, loop_status.current_target_error.error_body):
                continue
            filtered_candidates.append(candidate)
        candidates = filtered_candidates

        return candidates

#####################


## Verus Knowledge Graph ##

class VerusType(Enum):
    EXEC = 1
    PROOF = 2
    SPEC = 3

class fnNode:
    def __init__(self, func_str: str, start_row: int, end_row: int):
        self.start_row : int = start_row
        self.end_row : int = end_row

        self.name : str
        self.header : str
        self.type : VerusType
        self.body : str

        self.requires : str | None = None
        self.ensures : str | None = None
        self.recommends : str | None = None
        self.decreases : str | None = None

        # Group 1: spec, proof, or exec (if empty then exec)    
        # Group 2: function name
        header_regex = r'(?:pub)? *(?:closed|open)? *(spec|proof|exec)? *fn +([^\n( ]*)(?:[^\n\{]*)'
        header_match = re.search(header_regex, func_str)
        if header_match is None:
            raise Exception("Could not find function header in node string")
        
        self.type = VerusType[header_match.group(1).upper()] if header_match.group(1) is not None else VerusType.EXEC
        self.name = header_match.group(2)
        # We're assuming good input here (FIXME: add error handling for bad input)
        self.header = header_match.group(0).strip()

        # Find clauses inside <clauses> tag
        clauses = re.search(gen_tag_regex("clauses"), func_str)
        self.define_clauses(clauses)

        # Find body inside <body> tag
        body = re.search(gen_tag_regex("body"), func_str)
        self.body = body.group(1).strip() if body else None

    def define_clauses(self, clauses : re.Match[str] | None):
        if clauses:
            clauses = clauses.group(1)

            requires = re.search(r'(?s)requires(.*?)(ensures|recommends|decreases|$)', clauses)
            self.requires = requires.group(1).strip() if requires else None
            ensures = re.search(r'(?s)ensures(.*?)(requires|recommends|decreases|$)', clauses)
            self.ensures = ensures.group(1).strip() if ensures else None
            recommends = re.search(r'(?s)recommends(.*?)(requires|ensures|decreases|$)', clauses)
            self.recommends = recommends.group(1).strip() if recommends else None
            decreases = re.search(r'(?s)decreases(.*?)(requires|ensures|recommends|$)', clauses)
            self.decreases = decreases.group(1).strip() if decreases else None

class VerusKnowledgeGraph:
    def __init__(self, verus_str: str | None):
        self.nodes : list[fnNode] = []
        # Edges from some node to a proof relavent node
        self.proof_edges : dict[str, list[str]] = {}

        if verus_str is None:
            return

        function_nodes = re.findall(gen_tag_regex("vfunc"), verus_str)

        if not function_nodes:
            raise Exception("No function nodes found in Verus code, suggest running with --gen-tags or manually adding tags to code")

        for node_str in function_nodes:
            start_row, end_row = find_str_rows(verus_str, node_str)
            node = fnNode(node_str, start_row, end_row)
            self.nodes.append(node)

        # Now for every pair (ordered) of nodes, see if any of the relevance checks pass
        # If so, add an edge from the first node to the second node in the proof_edges dict
        checks : list[callable[[fnNode, fnNode], bool]] = [
            # If an exec or spec node has an exec or spec node in its clauses, then an edge
            lambda n1, n2: n1.type in (VerusType.EXEC, VerusType.SPEC) and n2.type in (VerusType.EXEC, VerusType.SPEC) and
                any(func_is_in(n2.name, clause) for clause in [n1.requires, n1.ensures, n1.recommends, n1.decreases] if clause is not None),
            # If an exec or spec node is in the ensures clause of a proof node, then an edge
            lambda n1, n2: n1.type in (VerusType.EXEC, VerusType.SPEC) and n2.type == VerusType.PROOF and
                any(func_is_in(n1.name, clause) for clause in [n2.ensures] if clause is not None),
            # If a proof node has an exec or spec node in its clauses, then an edge
            lambda n1, n2: n1.type == VerusType.PROOF and n2.type in (VerusType.EXEC, VerusType.SPEC) and
                any(func_is_in(n2.name, clause) for clause in [n1.requires, n1.ensures, n1.recommends, n1.decreases] if clause is not None),
            ]

        pairs = [(n1, n2) for n1 in self.nodes for n2 in self.nodes if n1 != n2]
        for n1, n2 in pairs:
            if any(check(n1, n2) for check in checks):
                if n1.name not in self.proof_edges:
                    self.proof_edges[n1.name] = []
                self.proof_edges[n1.name].append(n2.name)

    def relevance_sub_graph(self, target_node: fnNode | list[fnNode], depth : int) -> "VerusKnowledgeGraph":
        """
        Return a subgraph of the knowledge graph that contains only nodes that are relevant to the target_node
        up to the given depth. Depth is defined as the number of edges away from the target_node.
        """
        relevant_nodes : set[fnNode] = set()
        relevant_edges : dict[str, list[str]] = {}

        def dfs(node: fnNode | list[fnNode], current_depth: int):
            if current_depth > depth:
                return
            
            if isinstance(node, list):
                for n in node:
                    dfs(n, current_depth)
                return
            if node in relevant_nodes:
                return
            
            relevant_nodes.add(node)
            if node.name in self.proof_edges:
                for target_name in self.proof_edges[node.name]:
                    target_node = next((n for n in self.nodes if n.name == target_name), None)
                    if target_node:
                        if node.name not in relevant_edges:
                            relevant_edges[node.name] = []
                        relevant_edges[node.name].append(target_node.name)
                        dfs(target_node, current_depth + 1)

        dfs(target_node, 0)

        subgraph = VerusKnowledgeGraph(None)
        subgraph.nodes = list(relevant_nodes)
        subgraph.proof_edges = relevant_edges
        return subgraph
    
    def get_node_by_row(self, row: int) -> fnNode | None:
        """
        Return the node that contains the given row number, or None if no such node exists.
        """
        for node in self.nodes:
            if node.start_row <= row <= node.end_row:
                return node
        return None
    
    def get_names(self) -> list[str]:
        """
        Return a list of the names of all nodes in the graph.
        """
        return [node.name for node in self.nodes]
    
    def log_graph(self) -> str:
        log_str = "Nodes:\n"
        for node in self.nodes:
            log_str += f"  {node.name} ({node.type})\n"
        log_str += "Edges:\n"
        for src, targets in self.proof_edges.items():
            for target in targets:
                log_str += f"  {src} -> {target}\n"
        return log_str

    def graph_prompt(self) -> str:
        """
        Generate a prompt string that describes each node in the graph to an llm,
        including the header and clauses of each function
        """
        prompt_str = "The following is a list of possibly relevant functions:\n"
        for node in self.nodes:
            prompt_str += f"{node.header}\n"
            if node.requires:
                prompt_str += f"Requires\n {node.requires}\n"
            if node.ensures:
                prompt_str += f"Ensures\n {node.ensures}\n"
            if node.recommends:
                prompt_str += f"Recommends\n {node.recommends}\n"
            if node.decreases:
                prompt_str += f"Decreases\n {node.decreases}\n"
            prompt_str += "\n"

        return prompt_str
    

###########################

## Error Class ##

class ErrorType(Enum):
    SYNTAX_ERROR = 1
    ASSERTION_ERROR = 2
    POSTCONDITION_ERROR = 3
    UNRESOLVED_NAME = 4
    TYPE_ERROR = 5
    OTHER = 6


class RepairOutcome(Enum):
    PENDING = 1
    SUCCEEDED = 2
    FAILED = 3

class VerusError():
    def __init__(self, error : str, insertions: list[int] | None = None):
        # Snapshot of insertions at discovery time, used to project error_row forward
        # when comparing against errors from a later code revision

        # Save a copy of the current insertions not the reference to the original list

        self.insertions : list[int] = list(insertions) if insertions else []

        pattern = re.compile(
            r"(?ms)^error(?P<error_code>\[[^\]]*\])?:\s*(?P<message>.*?)\n"
            r"\s*-->\s*(?P<file>[^:\n]+):(?P<line>\d+):(?P<column>\d+)\n"
            r"\s*\|\n"
            r"(?P<src_lineno>\d+)\s*\|\s*(?P<code>.*?)\n"
            r"\s*\|\s*(?P<cause>.*?)(?=\n\n|\Z)"
        )

        match = pattern.search(error)

        self.error_body = match.group("code") if match else ""
        self.error_row = int(match.group("line")) if match else -1
        self.error_col = int(match.group("column")) if match else -1

        self.error_type = self.determine_error_type(match.group("message") if match else "", match.group("error_code") if match else "")

    def __str__(self) -> str:
        return f"ErrorType: {self.error_type}, Row: {self.error_row}, Col: {self.error_col}, Body: {self.error_body}"

    def __repr__(self) -> str:
        return self.__str__()

    def determine_error_type(self, message: str, error_code: str | None = None) -> ErrorType:
        normalized_message = message.lower()
        normalized_code = error_code.lower() if error_code else ""

        if "assertion" in normalized_message:
            return ErrorType.ASSERTION_ERROR
        elif any(keyword in normalized_message for keyword in [
            "syntax",
            "unexpected",
            "expected",
            "unknown prefix",
            "unterminated character literal",
        ]) or normalized_code in {"[e0762]"}:
            return ErrorType.SYNTAX_ERROR
        elif "postcondition" in normalized_message:
            return ErrorType.POSTCONDITION_ERROR
        elif normalized_code in {"[e0425]", "[e0433]"} or any(keyword in normalized_message for keyword in [
            "cannot find type",
            "use of undeclared type",
        ]):
            return ErrorType.UNRESOLVED_NAME
        elif normalized_code in {"[e0282]", "[e0308]", "[e0599]"} or any(keyword in normalized_message for keyword in [
            "type annotations needed",
            "cannot infer type",
            "cannot infer type of the type parameter",
            "no method named",
            "mismatched types",
        ]):
            return ErrorType.TYPE_ERROR
        else:
            return ErrorType.OTHER  

    def references(self, func_name: str) -> bool:
        """
        Check if the error references a function with the given name.
        This is done by checking if the function name appears in the error body.
        """
        func_regex = r'{func_name}\(.*\)'.format(func_name=func_name)
        return re.search(func_regex, self.error_body) is not None

    @staticmethod
    def is_present_in(target_error: "VerusError", errors: list["VerusError"]) -> bool:
        """
        Check whether target_error still occurs in a new set of errors, projecting target_error's
        error_row forward through its insertions to compensate for row shifts since it was found.
        """
        if not errors:
            return False
        
        # Firstly we only need to account for any new insertions made for the target_error
        # this corresponds to insertions beyond the length of the insertions list for the new errors
        new_insertions = errors[0].insertions[len(target_error.insertions):]
        shifted_row = target_error.error_row
        for row in new_insertions:
            if row <= shifted_row:
                shifted_row += 1

        return any(
            error.error_body == target_error.error_body and
            error.error_row == shifted_row and
            error.error_col == target_error.error_col and
            error.error_type == target_error.error_type
            for error in errors
        )

## Verus Handler ##

# A class responsible for running Verus on a given file and returning the output
# as well as keeping track of each error that occurs during the run
class VerusHandler:
    def __init__(self, verus_code: str, insertions: list[int] | None = None):
        self.verus_code = verus_code
        self.errors : list[VerusError] = []
        self.returncode: int | None = None
        # Keep track of insertions made to the code, in the same manner as we have
        # done in RepairLoopStatus 
        self.insertions : list[int] = insertions if insertions is not None else []

    def run_verus(self):
        # Run Verus on the file and capture the output
        # If there are errors, add them to self.errors and return False
        # If there are no errors, return True
        
        with tempfile.NamedTemporaryFile(suffix=".rs", mode="w", delete=False) as temp_file:
                temp_file.write(self.verus_code)
                temp_file.flush()  # Ensure all data is written to the file

                # Run Verus on the temporary file
                result = subprocess.run(
                    ["verus", temp_file.name, "--multiple-errors", "10"],  # Pass the temporary file to Verus
                    text=True,
                    capture_output=True
                )

                self.returncode = result.returncode

                # Find all Rust/Verus error blocks in the stderr output, including
                # both "error:" and coded forms like "error[E0762]:".
                error_blocks = re.findall(r"(?ms)^error(?:\[[^\]]+\])?: .*?(?=^\s*$|\Z)", result.stderr)
                # If there are errors, create VerusError objects and add them to self.errors
                for error_block in error_blocks:
                    verus_error = VerusError(error_block, insertions=self.insertions)
                    self.errors.append(verus_error)

    # Return the list of errors that we can attempt to repair
    def get_repairable_errors(self) -> list[VerusError]:
        # Tuple of qualifying error types that we can attempt to repair 
        qualifying_error_types = (ErrorType.ASSERTION_ERROR, ErrorType.POSTCONDITION_ERROR)
        return [error for error in self.errors if error.error_type in qualifying_error_types] 

    def has_overriding_error(self) -> bool:
        '''
        Checks if there is any overriding error (e.g., syntax error) in the list of errors.

        Returns:
            bool: True if there is an overriding error, False otherwise.
        '''
        return any(
            error.error_type == ErrorType.SYNTAX_ERROR or 
            error.error_type == ErrorType.UNRESOLVED_NAME or
            error.error_type == ErrorType.TYPE_ERROR
            for error in self.errors
            )


class IterativeVerusResult(BaseModel):
    """Blackboard verdict produced by the iterative Verus checker."""

    file: str
    passed: bool
    errors: list[VerusError] = []
    error: str = ""

    model_config = {"arbitrary_types_allowed": True}

    def __bool__(self) -> bool:
        return self.passed

    def summary(self) -> str:
        if self.error:
            return self.error
        return "no Verus errors" if self.passed else \
            f"{len(self.errors)} Verus error(s)"


def file_digest(path: str | Path) -> str:
    """Return the current SHA-256 digest, or an empty digest if unreadable."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def source_measurement(path: str | Path) -> dict[str, str]:
    """Describe the source artifact watched by a blackboard entry."""
    return {"file": str(path), "sha256": file_digest(path)}


def make_verus_predicate() -> Callable[[dict], IterativeVerusResult]:
    """Build a predicate that verifies the file named by a measurement."""
    cache: dict[tuple[str, str], IterativeVerusResult] = {}

    def predicate(measurement: dict) -> IterativeVerusResult:
        path = (measurement or {}).get("file", "")
        key = (path, file_digest(path))
        if key in cache:
            return cache[key]
        try:
            source = Path(path).read_text()
            handler = VerusHandler(source)
            handler.run_verus()
            result = IterativeVerusResult(
                file=path,
                passed=handler.returncode == 0 and not handler.errors,
                errors=handler.errors,
                error=(f"verus exited with code {handler.returncode}"
                        if handler.returncode != 0 and not handler.errors
                        else ""),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            result = IterativeVerusResult(
                file=path, passed=False, error=str(exc))
        cache[key] = result
        return result

    return predicate


class IterativeVerusGenKS(KnowledgeSource):
    """Run the iterative Verus generator for failed file entries."""

    name: str = "repair:iterative-verus-gen"
    partition: list[str] = []
    max_attempts: int = 1
    repair_fn: Optional[Callable[[str], str | None]] = None
    allow_llm: bool = False

    model_config = {"arbitrary_types_allowed": True}

    def execute(self, blackboard: Blackboard, keys: list[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if entry is None or not isinstance(entry.measurement, dict):
                continue
            path = entry.measurement.get("file")
            if not path:
                continue
            if self.repair_fn is None and not self.allow_llm:
                print(f"  {self.name}: refusing LLM-backed repair of "
                      f"{Path(path).name} - allow_llm is not set")
                continue
            try:
                repaired = self.repair_fn(path) if self.repair_fn else \
                    run_repair_process(path)
                if repaired is None:
                    print(f"  {self.name}: no repair for {Path(path).name}")
                    continue
                Path(path).write_text(repaired, newline="")
                blackboard.write_entry(
                    key=key,
                    predicate=entry.predicate,
                    measurement=source_measurement(path),
                    result=None,
                )
                print(f"  {self.name}: repaired {Path(path).name}")
            except Exception as exc:
                print(f"  {self.name}: repair failed on "
                      f"{Path(path).name} - {exc}")

###################

## Repair Process ##

# Object to track the status of the repair loop, 
# including the # of iterations, # of failed attempts, max failed attempts, whether the repair was successful,,
# the current target error, the "base" verus code, and the "repaired" verus code
class RepairLoopStatus():
    def __init__(self, verus_code: str, target_errors: list[VerusError], max_failed_attempts: int = 2, max_depth: int = 4):
        if not target_errors:
            raise ValueError("RepairLoopStatus requires at least one target error")

        self.iterations : int = 0
        self.failed_attempts : int = 0
        self.max_failed_attempts : int = max_failed_attempts
        self.cur_depth : int = 0
        self.max_depth : int = max_depth
        self.current_target_index : int = 0

        self.target_errors : list[VerusError] = target_errors
        self.working_target_error : VerusError = target_errors[0]
        self.target_outcomes : list[RepairOutcome] = [RepairOutcome.PENDING for _ in target_errors]
        self.base_verus_code : str = verus_code
        self.candidate_verus_code : str = verus_code
        self.knowledge_graph : VerusKnowledgeGraph = VerusKnowledgeGraph(verus_code)

        # Tracks rows where a new line has been permanently accepted into base_verus_code
        self.accepted_line_insertions : list[int] = []
        # Tracks rows inserted by the current, not-yet-accepted candidate
        self.candidate_line_insertions : list[int] = []

    @property
    def current_target_error(self) -> VerusError:
        return self.working_target_error

    @property
    def current_target_outcome(self) -> RepairOutcome:
        return self.target_outcomes[self.current_target_index]

    def log_status(self, title : str, content: str):
        log.append(
            f"Target {self.current_target_index + 1}/{len(self.target_errors)}, "
            f"Iteration {self.iterations}, Depth {self.cur_depth}, Failed Attempts {self.failed_attempts}: {title}\n"
            f" Current Target Error: {self.current_target_error}\n"
            f" Current Line Insertions: {self.line_insertions}\n"
            f" Current Target Outcome: {self.current_target_outcome.name}\n"
            f" {content}"
        )

    def log_graph(self):
        self.log_status("Logging Knowledge Graph", f"Current state of the knowledge graph: {self.knowledge_graph.log_graph()}")
        
    def increment_iterations(self):
        self.iterations += 1

    def increment_failed_attempts(self):
        self.failed_attempts += 1

    def reset_failed_attempts(self):
        self.failed_attempts = 0

    def increment_depth(self):
        self.cur_depth += 1

    def reset_depth(self):
        self.cur_depth = 0

    def set_successful_repair(self):
        self.target_outcomes[self.current_target_index] = RepairOutcome.SUCCEEDED

    def set_failed_repair(self):
        self.target_outcomes[self.current_target_index] = RepairOutcome.FAILED

    def should_continue(self) -> bool:
        if not self.has_current_target():
            return False

        target_already_resolved = self.current_target_outcome != RepairOutcome.PENDING
        failed_attempts_exceeded = self.failed_attempts >= self.max_failed_attempts
        return not (target_already_resolved or failed_attempts_exceeded)
    
    def set_current_working_error(self, error: VerusError):
        self.working_target_error = error

    def has_current_target(self) -> bool:
        return 0 <= self.current_target_index < len(self.target_errors)

    def advance_target(self) -> bool:
        self.current_target_index += 1
        self.failed_attempts = 0
         
        self.reset_depth()
        self.reset_failed_attempts()

        if not self.has_current_target():
            return False
        self.working_target_error = self.target_errors[self.current_target_index]
        return True

    def record_line_insertion(self, row: int):
        """
        Record that a new line was inserted before the given row (1-indexed,
        relative to base_verus_code) while building candidate_verus_code.
        """
        self.candidate_line_insertions.append(row)

    @property
    def line_insertions(self):
        return self.accepted_line_insertions + self.candidate_line_insertions

    def apply_candidate(self, candidate: str, target_error: VerusError):
        """
        Locate the first occurrence of target_error's body at or after its original
        row/column in candidate_verus_code via regex, then insert candidate above it
        matching its indentation.
        """
        lines = self.candidate_verus_code.splitlines(keepends=True)
        shift = sum(1 for row in self.line_insertions if row <= target_error.error_row)
        anchor_row = target_error.error_row + shift
        error_line_pos = sum(len(line) for line in lines[:anchor_row - 1])
        error_pos = error_line_pos + max(target_error.error_col - 1, 0)

        indent = self.candidate_verus_code[error_line_pos: error_pos]
        # extract only the whitespace at the beginning of the line for indentation
        match = re.match(r'\s*', indent)
        indent = match.group(0) if match else ""
        
        self.candidate_verus_code = (
            self.candidate_verus_code[:error_line_pos] +
            indent + candidate + "\n" +
            self.candidate_verus_code[error_line_pos:]
        )
        self.record_line_insertion(anchor_row)
        return

    def accept_candidate_code(self):
        """
        Commit candidate_verus_code as the new base_verus_code, folding its
        insertions into the permanent accepted_line_insertions history.
        """
        self.base_verus_code = self.candidate_verus_code
        self.accepted_line_insertions.extend(self.candidate_line_insertions)
        self.candidate_line_insertions = []

    def reject_candidate_code(self):
        """
        Discard candidate_verus_code and its insertions, reverting to base_verus_code
        while leaving accepted_line_insertions untouched.
        """
        self.candidate_verus_code = self.base_verus_code
        self.candidate_line_insertions = []

# Gather the nessecary context, and generate candidate solutions for the current error using the LLM
def generate_candidates(loop_status: RepairLoopStatus, target_error: VerusError) -> list[str]:
    # Firstly get the node that contains the current target error
    target_node = loop_status.knowledge_graph.get_node_by_row(target_error.error_row)
    if target_node is None:
        loop_status.log_status("No Function Node Found", f"No function node found for error at row {target_error.error_row}, cannot generate repair candidates")
        loop_status.set_failed_repair()
        return []

    # Get the subgraph of relevant nodes for the target node
    relevant_nodes = [fn_node for fn_node in loop_status.knowledge_graph.nodes if func_is_in(fn_node.name, target_error.error_body)]
    relevant_subgraph = loop_status.knowledge_graph.relevance_sub_graph(relevant_nodes, depth=2)
    loop_status.log_status("Relevant Subgraph", f"The relevant subgraph for the target node '{target_node.name}' is:\n{relevant_subgraph.log_graph()}")

    # Generate the context for the LLM based on the relevant subgraph
    llm_context = relevant_subgraph.graph_prompt()
    loop_status.log_status("LLM Context", f"{llm_context}")

    # Generate the function level instructions for the LLM based on the target node
    llm_wrapper = LLMWrapper(context=llm_context)
    instruction_prompt = f"Generate a list of instructions for repairing the function '{target_node.name}':\n{target_node.header}\n{target_node.body}, with a focus on proving the target {target_error.error_body}"
    instructions = llm_wrapper.gen_instruction(loop_status, instruction_prompt)
    
    loop_status.log_status("LLM Function Level Instructions (LLM Result)", f"{instructions}")

    # Now check if the enclosed scope of the target error is deeper than the function level
    # If so, generate the statement level instructions for the LLM based on the enclosed scope
    # TODO: Check if we should find the enclosing scope of the target in the candidate_verus_code instead of the base_verus_code, since the candidate may have shifted the error row
    scope_instructions = ""
    open_scope_row, close_scope_row = find_enclosing_scope(loop_status.base_verus_code, target_error.error_row)
    if open_scope_row != -1 and close_scope_row != -1 and (open_scope_row > target_node.start_row or close_scope_row < target_node.end_row):
        enclosed_scope_str = "\n".join(loop_status.base_verus_code.splitlines()[open_scope_row - 1:close_scope_row])
        scope_level_prompt = f"Generate a list of instructions for repairing the enclosed scope of the function '{target_node.name}':\n{enclosed_scope_str}, with a focus on the failure {target_error.error_body}"

        scope_instructions = llm_wrapper.gen_instruction(loop_status, scope_level_prompt)

        loop_status.log_status("LLM Scope Level Instructions (LLM Result)", f"{scope_instructions}")

    # Now generate candidate solutions based on the function level and scope level instructions
    candidate_prompt = f"Generate a list of candidate Verus code snippets for repairing the function '{target_node.name}' based on the following instructions:\nFunction Level Instructions:\n{instructions}\nScope Level Instructions:\n{scope_instructions}"
    candidates = llm_wrapper.gen_candidates(loop_status, candidate_prompt)
    
    loop_status.log_status("LLM Candidates (LLM Result)", f"{candidates}")

    # Remove candidates that merely restate the target error.
    candidates = [candidate for candidate in candidates if not candidate_restates_error(candidate, target_error.error_body)]

    # Ensure no candidate is an assert statement, if so change it to an assume statement
    for i, candidate in enumerate(candidates):
        if candidate.strip().startswith("assert"):
            candidates[i] = "assume" + candidate.strip()[6:]

    return candidates

# Run the repair process for a given error
def repair_error(loop_status: RepairLoopStatus, target_error: VerusError) -> RepairOutcome:
    # Check if we have reached the max depth, if so return False
    if(loop_status.cur_depth >= loop_status.max_depth):
        loop_status.log_status("Max Depth Reached", f"Max depth {loop_status.max_depth} reached, could not repair error with {loop_status.max_depth} assertions")
        # We return PENDING here to indicate that the repair process was not completed due to depth limit, but it is not a definitive failure
        return RepairOutcome.PENDING
    else: 
        loop_status.increment_depth()

    # Loop on the current error for max_failed_attempts number of times, if we cannot repair the error, return False
    while(loop_status.failed_attempts < loop_status.max_failed_attempts):
        # Firstly call the LLM to generate candidate solutions for the current error
        candidates = generate_candidates(loop_status, target_error)

        if(not candidates):
            loop_status.log_status("No Candidates Generated", f"No candidates generated for error at row {target_error.error_row}, cannot repair")
            return RepairOutcome.FAILED

        # Now apply each candidate solution to the base verus code and run Verus on the modified code
        for candidate in candidates:
            loop_status.apply_candidate(candidate, target_error)
            verus_handler = VerusHandler(loop_status.candidate_verus_code, insertions=loop_status.line_insertions)
            verus_handler.run_verus()

            if verus_handler.has_overriding_error():
                loop_status.log_status("Syntax Error", f"Candidate introduced a syntax error, rejecting candidate: {candidate}")
                loop_status.reject_candidate_code()
                continue

            # Now check if the current target error is still present in the new errors, 
            # if not, we have repaired the error
            # If yes, we must check if the candidate was an assume statement, 
            #         and then check again as an assert
            new_errors = verus_handler.get_repairable_errors()

            loop_status.log_status("Checking New Errors", f"New errors after applying candidate {candidate}:\n {new_errors}")

            if VerusError.is_present_in(target_error, new_errors):
                # If it is still present, we have failed to repair the error, so we log the failure and reject the candidate code
                loop_status.log_status("Candidate Failed to Repair", f"Candidate did not repair error {target_error.error_body} at row {target_error.error_row}")
                loop_status.reject_candidate_code()
                # Then test a new candidate
                continue
            else:
                # If the error is not present, we have successfully repaired the error
                # However we must check if the candidate was an assume statement, and then check again as an assert
                if candidate.strip().startswith("assume"):
                    # If it was an assume statement, we must check if the new statement causes an error
                    loop_status.reject_candidate_code()
                    # So we replace the assume with an assert and run Verus again
                    candidate_assert = candidate.replace("assume", "assert", 1)
                    loop_status.apply_candidate(candidate_assert, target_error)
                    loop_status.accept_candidate_code()

                    loop_status.log_status("Candidate Repaired but was Assume", f"Candidate {candidate} repaired error {target_error.error_body} at row {target_error.error_row}, but it was an assume statement, \nchecking if {candidate_assert} causes a new error")

                    verus_handler = VerusHandler(loop_status.base_verus_code, insertions=loop_status.line_insertions)
                    verus_handler.run_verus()
                    new_errors = verus_handler.get_repairable_errors()

                    loop_status.log_status("Checking errors from Candidate as Assert", f"Resulting errors: {new_errors}")

                    # Now check if our candidate_assert has caused a new error,
                    # If so we attempt to repair the new error, if not we have successfully repaired the original error
                    # To check we will see if any of the new errors row numbers are the same as the candidate_assert row number
                    candidate_error = next((error for error in new_errors if error.error_row == target_error.error_row), None)
                    if candidate_error is not None:
                        loop_status.log_status("Candidate Assert Needs to be Proven", f"Candidate assert {candidate_assert} caused a new error at row {target_error.error_row}, attempting to repair new error")
                        # We will create a new VerusError for the new error and attempt to repair it     
                        loop_status.set_current_working_error(candidate_error)
                        return repair_error(loop_status, candidate_error)
                    else:
                        # Else we have successfully repaired the original error, so we log the success and accept the candidate code
                        loop_status.log_status("Successfully Repaired with Assert", f"Successfully repaired error {target_error.error_body} at row {target_error.error_row} with candidate:\n{candidate_assert}")
                        return RepairOutcome.SUCCEEDED
                else:
                    # If the candidate was not an assume statement, we have successfully repaired the original error, so we log the success and accept the candidate code
                    loop_status.log_status("Successfully Repaired", f"Successfully repaired error {target_error.error_body} at row {target_error.error_row} with candidate:\n{candidate}")
                    loop_status.accept_candidate_code()
                    return RepairOutcome.SUCCEEDED

        # If we have exhausted all candidates then increment the failed attempts and log the failure
        loop_status.increment_failed_attempts()
        loop_status.log_status("Failed to Repair, Trying Again", f"Failed to repair error {target_error.error_body} at row {target_error.error_row} on the {loop_status.failed_attempts} attempt")

    # If we have exhausted all attempts to repair the error, we log the failure and return False
    loop_status.log_status("Failed to Repair", f"Exhausted all attempts to repair error {target_error.error_body} at row {target_error.error_row}")
    return RepairOutcome.FAILED
 
# Run the repair process loop, if succesful return the repaired file as a string, else return None
def run_repair_process(verus_file: str) -> str | None:
    # Firstly, read the contents of the provided Verus file
    with open(verus_file, 'r') as file:
        verus_code = file.read()

    # Then run Verus, and keep track of any errors
    verus_handler = VerusHandler(verus_code)
    verus_handler.run_verus()

    # If no repairable errors, we're done
    repair_candidates : list[VerusError] = verus_handler.get_repairable_errors()
    if not repair_candidates:
        log.append("No repairable errors found, cannot run repair process:\n" + "\n".join([f"Row: {error.error_row}, Col: {error.error_col}, Type: {error.error_type},\n Error: {error.error_body}," for error in verus_handler.errors]))
        # No repairs possible, return None
        return None
    
    # Else set the loop status with all repair candidates and track each candidate's outcome.
    loop_status = RepairLoopStatus(verus_code, repair_candidates)
    loop_status.log_graph()

    # Now we enter the repair loop, where we attempt to repair each of our original errors
    while loop_status.should_continue():
        loop_status.increment_iterations()
        target_error = loop_status.current_target_error
        loop_status.log_status("Beginning Repair Attempt", f"Attempting to repair error {target_error.error_body} at row {target_error.error_row}")
        success = repair_error(loop_status, target_error)
        if success == RepairOutcome.SUCCEEDED:
            loop_status.set_successful_repair()
            
        elif success == RepairOutcome.PENDING:
            pass

        elif success == RepairOutcome.FAILED:
            loop_status.set_failed_repair()
            
        # Move on to the next error
        loop_status.advance_target()

    # After the repair loop, we log the final status of each target error
    final_status_log = "Final Repair Status:\n"
    for i, outcome in enumerate(loop_status.target_outcomes):
        # Log the final status of each target error
        target_error = loop_status.target_errors[i]
        final_status_log += f"Error {target_error.error_body} at row {target_error.error_row}: {outcome.name}\n"

    log.append(final_status_log)

    # If any of the target errors were successfully repaired, we return the final base_verus_code, else we return None
    if any(outcome == RepairOutcome.SUCCEEDED for outcome in loop_status.target_outcomes):
        return loop_status.base_verus_code
    else:
        return None


####################

def main():

    # Check for a rust file as cmd line argument, if none quit
    # check for a -log flag and an output file name to print log to, if none provided, print log to stdout
    # quit if no file provided
    verus_file = ""
    output_log : bool = False
    output_log_file : str | None = None
    output_repaired_file : bool = False
    output_repaired_file_name : str | None = None

    if len(sys.argv) < 2:
        print("Please provide a Verus file as a command line argument")
        return
    else:
        for arg in sys.argv:
            if arg == "-log":
                output_log = True
            elif output_log and output_log_file is None:
                if arg[0] == "-":
                    output_log_file = ""
                else:
                    output_log_file = arg
            elif arg == "-out":
                output_repaired_file = True
            elif output_repaired_file and output_repaired_file_name is None:
                if arg[0] == "-":
                    output_repaired_file_name = ""
                else:
                    output_repaired_file_name = arg
            else:
                verus_file = arg

    if verus_file == "":
        print("No Verus file provided")
        return
    elif verus_file[-3:] != ".rs":
        print("Provided file is not a Rust (.rs) file")
        return
    elif output_repaired_file and output_repaired_file_name == "":
        print("No output file provided")
        return
        
    repaired_file_string = run_repair_process(verus_file)

    # If the log flag was provided, print the log to stdout or to the provided output file
    if output_log:
        output = ("\n\n"+("#"*30)+"\n\n").join(log)
        if output_log_file:
            with open(output_log_file, 'w') as log_file:
                log_file.write(output)
        else:
            print(output)

    # If the repair process was successful, print the repaired file string to stdout or to the provided output file
    if repaired_file_string is not None:
        if output_repaired_file:
            with open(output_repaired_file_name, 'w') as output_file:
                output_file.write(repaired_file_string)
        else:
            print(repaired_file_string)
    else:
        print("Repair process failed, no repaired file to output")

if __name__ == "__main__":
    main()