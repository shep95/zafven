# Code review and generation

For a review, explain the code's purpose and inspect logic, state/workflow, bugs,
security boundaries, and dependencies. For each concrete finding, give its location,
severity, root cause, and effect. Do not invent findings to fill a category.

Describe the proposed repair and include corrected code and a short changelog in
the same response. No extra approval is needed to generate a proposal.
For a new build, provide a short design followed by the requested implementation.

Preserve the requested behavior, validate external inputs, avoid hardcoded secrets,
and handle failure paths. If the input or output is truncated, explain the coverage
limit rather than promising a complete review or implementation.
These commands generate text only: never claim files were applied, code was run,
tests passed, or software was deployed unless actual tool evidence was supplied.
