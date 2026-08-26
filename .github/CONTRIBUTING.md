# Contributing

Thank you for helping. Three rules keep this simple.

1. **Sign off every commit.** By contributing you certify the Developer
   Certificate of Origin (https://developercertificate.org). Sign off with
   `git commit -s`. Unsigned commits are not merged.
2. **Apache 2.0.** Every contribution is licensed under the Apache License,
   Version 2.0, the same as the rest of the repository. Add the one-line
   copyright header used in every source file if you create a new file.
3. **The scored bank is fixed and is not accepted as a contribution.**
   Do not submit evaluation cases, prompts, worlds, answer keys, or hidden
   assignments. The 600-case development bank changes only through a
   versioned proposal with new digests, never through a pull request that
   edits cases. Enforcement inputs (policy decision points behind the AuthZEN
   contract), harness fixes, tests, and documentation are welcome.

Before opening a pull request, run the suite (`cd environment_lab && pip install
-e ".[hosted-api,dev]" && python -m pytest tests`) and read the gates in
[docs/07-validation.md](../docs/07-validation.md).
Use the issue forms for reproduction failures and PDP integrations. No em
dashes anywhere in prose. Plain English; no new project vocabulary.
