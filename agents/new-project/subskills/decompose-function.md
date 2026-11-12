# Subskill — Decompose a Function

**Use when:** a function in Step 7.4 is too big to specify in one entry. Signs: its behaviour will not fit in about 15 lines, it has more than one kind of side effect, it mixes decisions with input/output, or it branches on more than three conditions.
**Produces:** a short orchestrating function plus contract entries for each helper.

A large function is where a low-power model goes wrong, and where a mistake is hardest to locate. Splitting it during planning moves the hard thinking to the strong model and leaves each implementer a small, checkable job.

## Procedure

1. **Write the behaviour as numbered plain-language steps.** Include the failure paths, not only the happy path.
2. **Group the steps.** Steps that share data and purpose belong together. Each group is a candidate helper.
3. **Separate deciding from doing.** Put logic in pure functions (data in, data out) and keep input/output in thin functions around them. Pure functions are the easiest to implement and to test.
4. **Extract a helper when the group:**
   - has inputs and outputs you can name without mentioning the parent,
   - can be tested on its own, and
   - is more than a line or two.
5. **Reuse before creating.** Check the contract for an existing function that already does the job, or would with a small generalization.
6. **Write a full contract entry for each helper,** using the Step 7.4 template.
7. **Rewrite the parent as orchestration.** Its entry now states:
   - the calls it makes, in order;
   - what data passes from each call to the next;
   - for each call, what happens on failure: propagate, translate to another error, retry, or undo earlier steps;
   - where a transaction begins and ends.
8. **Repeat** on any helper that is still too big. Stop when every function passes the cold-implementer test: a model with only this entry, and the signatures of what it calls, would get it right.

## When to stop

- Do not extract one-liners. A helper should earn its name.
- A helper needing more than about five parameters usually means the cut is in the wrong place. Regroup.
- More than three levels of nesting usually means a component is missing. Go back to Step 7.3.

## Example: a generic endpoint handler

Before, one function: *handle a request* (read the caller's identity, parse the body, check permission, run the operation in a transaction, format the response, turn any error into the right status code).

After:

| Function | Kind | Job |
|----------|------|-----|
| `authenticate(request) -> Principal` | I/O | Identify the caller, or raise `Unauthenticated` |
| `parse_command(request, schema) -> Command` | pure | Validate the body against the schema, or raise `InvalidInput` |
| `authorize(principal, command) -> None` | pure | Raise `Forbidden` unless this caller may run this command on this record |
| `execute(command, tx) -> Result` | I/O | Perform the operation inside the transaction it is given |
| `render(result) -> Response` | pure | Shape the success response |
| `error_response(error) -> Response` | pure | Map each error type to a status code and body |
| `handle(request) -> Response` | orchestration | Call the above in order |

The parent's entry then reads: call `authenticate`, `parse_command`, `authorize` in that order; open a transaction, call `execute`, commit; return `render(result)`. Any error raised before the commit rolls the transaction back and returns `error_response(error)`. Nothing is written if authorization fails.

Six of the seven are now `standard`. Only `handle` might stay `complex`, and its entry spells out the order and the failure policy.

## Custom instructions

<!-- Add your own rules for this subskill below. They override the defaults above. -->
