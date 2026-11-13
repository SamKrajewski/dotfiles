# Explaining a finding in plain language

Every finding carries two descriptions. The technical one
(`failure_scenario`, `evidence`, `suggested_fix`) is for the person who will
fix it. The plain-language one (`explanation`) is for whoever else reads the
review: a product manager, a new teammate, the author at 2 a.m., or someone
whose expertise is in a different part of the system. Do not assume the
reader's level. Write the explanation so that a bright ten-year-old could
follow the reasoning, and keep it clearly separated so an expert can skip it.

This is not dumbing down. Breaking a bug into its basic concepts is the same
work as verifying it; if the explanation cannot be built from simple steps,
the finding is probably not traced yet.

## The method

1. **Say what the code is supposed to do**, in one sentence, with no jargon.
   "This code shortens a person's name so it fits in a box that holds 20
   characters."
2. **List the words to know.** Every technical term you are about to use gets
   one sentence and, where it helps, an everyday comparison. Define the term
   *before* using it. If you need more than five terms, the explanation is too
   deep: split the finding or simplify. These go in `explanation.concepts`.
3. **Walk through what actually happens, step by step.** Numbered steps, one
   plain sentence each, with a concrete example value, not a variable name:
   "the name is José", not "the input string". Each step should follow
   obviously from the one before. These go in `explanation.steps`.
4. **Say who gets hurt and how**, in one or two sentences. This goes in
   `explanation.why_it_matters` and should match `failure_scenario`.
5. **Keep the precise version too.** The plain explanation is in addition to
   the technical fields, never instead of them.

## Worked example: a string-semantics bug

Finding: a username is cut to 20 bytes before being stored, but the limit was
meant to be 20 characters.

**Concepts**

- **character** — one symbol you can see, like `J`, `é`, or `😀`.
- **byte** — the small box computers store things in. A plain letter like `J`
  takes one box; an accented letter like `é` takes two; an emoji can take four.
- **UTF-8** — the rule book that says how many boxes each character uses.
- **truncate** — to cut something off at a fixed length.

**Steps**

1. A user signs up with the name `José Álvarez-Peña`, which is 17 characters.
   The code checks "is this 20 or fewer?" by counting *boxes*, not characters.
   Three letters here take two boxes each, so the name takes exactly 20 boxes
   and passes.
2. Another user signs up as `Christopher Sebastián`: 21 characters, 22 boxes,
   because only the `á` takes two boxes.
3. The code keeps the first 20 boxes. Boxes 1 to 19 hold `Christopher Sebasti`
   completely; box 20 is the first half of the two-box letter `á`.
4. Half a letter is not a valid letter. When the 20 boxes are turned back into
   text, the computer stops with an error (`UnicodeDecodeError: unexpected end
   of data`), or, if it is told to be lenient, shows `�` in place of the `á`.
5. So the sign-up either fails for this user or stores a garbled name, while
   `Christopher Sebastian` without the accent would have been shortened
   cleanly.

(Checked with `python3 -c 'print("Christopher Sebastián".encode()[:20].decode())'`.
Do this for every concrete value in an explanation: a plausible example that
does not actually reproduce is worse than none.)

**Why it matters**

Anyone whose name contains an accented letter or an emoji at the wrong
position can be blocked from signing up or see a garbled name. The limit was
meant to protect the display box, so it should count characters, not boxes.

## Checklist

- [ ] First sentence states the purpose of the code without jargon.
- [ ] Every technical term is defined before it is used.
- [ ] Steps use concrete values and could be followed by someone who has never
      seen the codebase.
- [ ] Every concrete value was checked (run it, compute it); none is guessed.
- [ ] No step skips a logical hop ("and then it breaks").
- [ ] The harm is stated in terms of a person or a system the reader cares
      about.
- [ ] The technical fields still give the fixer file, line, and exact cause.

## Anti-patterns

- Using a term and then defining it, or never defining it ("the race
  condition causes a double write").
- Analogies that are cute but wrong. If the comparison breaks down in a way
  that matters to the bug, drop it.
- Explaining the fix before the problem.
- Steps that are really one step with three clauses.
- Padding. Plain does not mean long: five short steps beat two paragraphs.
