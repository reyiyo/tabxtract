## What this changes

<!-- One or two sentences. -->

## What you observed

<!-- For pipeline changes, describe the behaviour, not just the diff.
     "This video produced 6 pages instead of 10" beats "improved dedup". -->

## Verification report

<!-- Pipeline changes: paste before/after reports. Delete this section if not applicable. -->

## Checklist

- [ ] Tests pass (`pytest` and `npm test`)
- [ ] The **identical-pages regression test** still passes (guards against silent page loss)
- [ ] No per-instrument branching added
- [ ] No new magic numbers — thresholds calibrate from the data, or the constant is justified in a comment
- [ ] `tabxtract/` still imports nothing from `server/` or `src-tauri/`
- [ ] New failure modes surface in the verification report
- [ ] Linted (`ruff`, `mypy`, `eslint`, `tsc`)
- [ ] I agree to license this contribution under GPL-3.0
