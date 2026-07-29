# AAAI-27 submission rules and build checklist

**Conference:** AAAI 2027 Main Technical Track
**Last checked:** 2026-07-29
**Scope:** AgentProof Paper 1 main paper, reproducibility checklist,
supplementary PDF, and anonymous code/data package

This checklist adapts the submission rules used by the read-only
`principled-bestofk` reference to AgentProof. Recheck the official pages
immediately before submission:

- <https://aaai.org/conference/aaai/aaai-27/main-technical-track-call/>
- <https://aaai.org/conference/aaai/aaai-27/submission-instructions/>
- <https://aaai.org/conference/aaai/aaai-27/supplementary-material/>
- <https://aaai.org/aaai-publications/aaai-publication-policies-guidelines/>

## 1. Deadlines

- [ ] Submit the main paper by **July 28, 2026 at 23:59 UTC-12**.
  Stockholm time: **July 29 at 13:59 CEST**.
- [ ] Submit supplementary material and code by **July 31, 2026 at 23:59
  UTC-12**. Stockholm time: **August 1 at 13:59 CEST**.
- [ ] Assume there is no extension.
- [ ] After the main-paper deadline, do not change the main paper; update only
  permitted supplementary uploads during the supplementary window.

## 2. Main-paper format

- [ ] Use the unmodified official AAAI-27 style and bibliography files.
- [ ] Use US Letter: 612 by 792 points.
- [ ] Use no more than 7 pages of technical content and 9 pages total.
- [ ] Pages 8 and 9, if present, contain references only.
- [ ] Do not put appendices, acknowledgments, proofs, figures, tables, or
  other technical content on reference-only pages.
- [ ] Do not alter margins, spacing, fonts, headings, or column widths to fit
  content.
- [ ] The main PDF is self-contained; essential evaluation must not depend on
  reviewers opening optional material.
- [ ] All fonts are embedded Type 1 or TrueType, never Type 3.
- [ ] The PDF is unencrypted and contains no embedded file, JavaScript, or
  unexpected annotation.

Current source: `papers/paper1/aaai/main.tex`.

## 3. Double-blind anonymity

- [ ] The source author line is `Anonymous Submission`; affiliations are
  empty.
- [ ] Omit acknowledgments, funding IDs, compute allocations, laboratory
  names, and institution-specific descriptions.
- [ ] Remove author names, usernames, email addresses, home paths, account
  names, repository identifiers, and identifying PDF metadata.
- [ ] Refer to author work in the third person and suppress any citation that
  would reveal authorship.
- [ ] Do not include author-owned web links, including anonymous repositories,
  in the paper, supplement, checklist, or code/data package.
- [ ] Third-party public-data provenance may remain where scientifically
  necessary.
- [ ] Scan every ZIP member name and content, including Markdown, JSON,
  comments, shell scripts, metadata, logs, and notebook output.

Identity scan terms must cover at least the author names, organization and
repository slugs, local paths, account names, and the related preprint
identifier. These terms belong only in local operator checks, not upload
artifacts.

## 4. Paper-specific scientific claims

- [ ] Map every headline claim to the paper, supplement, committed JSON, or an
  executable analysis.
- [ ] Follow `papers/paper1/aaai/CLAIMS_AUDIT.md` and
  `papers/paper1/aaai/HUMAN_GATE_POLICY.md`.
- [ ] Describe the 922 items as extracted **file-level graphs**, not 922
  deployed systems or independent repositories.
- [ ] Describe the 119-graph audit as quota-selected and non-random; its
  proportions characterize this audit, not a population.
- [ ] Describe 184 of 186 findings as LLM-assisted exploratory labels pending
  independent human validation.
- [ ] Keep extraction fidelity, policy applicability, checker behavior, and
  abstraction coverage distinct.
- [ ] State that `safe` requires an authored event-complete abstraction;
  mined graphs receive `inconclusive`, not `safe`.
- [ ] Do not present zero firings from the declaration-sensitive rule as proof
  that mined workflows are safe: the mined graphs expose no sensitive
  bindings.
- [ ] Preserve the reverse-audit result: all 12 source-audited human-gate
  violations escape the mined pipeline, only one is recovered by a
  source-reconstructed graph, and nine regulated effects are absent from the
  graph vocabulary.
- [ ] Preserve negative results, caveats, missing source snapshots, incomplete
  human worksheets, protocol limitations, and non-reproducible-frame
  disclosures.
- [ ] Do not imply production validity, population prevalence, universal
  soundness, or complete semantic coverage.

## 5. References and attribution

- [ ] Every citation resolves and every bibliography item is cited or
  intentionally retained.
- [ ] Central prior-art and theoretical statements use primary sources.
- [ ] Self-citations use the third person and are anonymized when needed.
- [ ] No AI system is an author or a citable scientific authority.
- [ ] Search final PDFs, generated bibliography, supplement, README, and ZIP
  for stale identifying self-citations or author-owned links.

## 6. Generative-AI policy

- [ ] The manuscript accurately documents generative-AI assistance.
- [ ] Every author approves the disclosure.
- [ ] Human authors verify all text, claims, citations, code, and results and
  accept responsibility for the submission.
- [ ] No AI system is listed as an author or scientific source.

Current disclosure:

> Generative AI tools assisted with language editing, software and claim
> review, source-triage labels, and submission-compliance auditing. The
> authors verified all text, citations, code, and results, take responsibility
> for the complete submission, and list no AI system as an author or
> scientific source.

Update it before submission if it is incomplete or inaccurate.

## 7. Ethics and submission integrity

- [ ] No plagiarism, fabrication, falsification, misleading selection,
  duplicate/near-duplicate archival submission, hidden reviewer instruction,
  prompt injection, or invisible manipulative content.
- [ ] No confidential, private, improperly licensed, or unnecessary personal
  data.
- [ ] Public-repository provenance and derived-data redistribution match the
  paper's ethical statement.
- [ ] Findings are disclosed as promised without naming maintainers.
- [ ] Protocol deviations and negative results remain visible.

## 8. Author-only requirements

These require author knowledge and cannot be certified by repository checks.

- [ ] The work and substantially overlapping work are not under review,
  accepted, or published at another archival venue.
- [ ] Every author approves the submission, author list, and order.
- [ ] Every author has a complete OpenReview profile and correct conflicts.
- [ ] Reviewer-availability requirements are satisfied.
- [ ] The author-specific maximum of 10 Main Technical Track submissions is
  satisfied.

## 9. Reproducibility checklist

- [ ] Upload the checklist separately in the designated field.
- [ ] Every answer matches the exact paper, archive, scripts, data, and
  release plan.
- [ ] Do not answer `yes` where data, source snapshots, seeds, dependencies,
  or preprocessing are only partially included.
- [ ] Report the non-random sample design, public-source frame, unavailable
  third-party snapshots, incomplete human validation, and correct replication
  units honestly.

Current source: `papers/paper1/aaai/ReproducibilityChecklist.tex`.

## 10. Supplementary PDF

- [ ] Upload it separately from the main paper and keep it anonymous.
- [ ] Do not link to author-owned web material.
- [ ] Do not rely on it to repair an incomplete main-paper argument.
- [ ] Keep counts, terminology, paths, theorem conditions, and limitations
  synchronized with the main paper and artifact.
- [ ] Include supporting methods, extended tables, protocols, negative
  results, and implementation details—not internal governance or repository
  history.

Current source: `papers/paper1/aaai/supplement.tex`.

## 11. Anonymous code/data ZIP

- [ ] Upload it in the code/data field.
- [ ] Include an anonymous reviewer-facing README with environment, test, and
  reproduction commands.
- [ ] Include the code and derived data required by every advertised command.
- [ ] Test advertised commands after clean extraction.
- [ ] Exclude site launchers, private paths, raw secrets, `.env`, `.git`,
  hidden files, caches, bytecode, symlinks, and identifying metadata.
- [ ] Scan both member names and file contents for identity.
- [ ] Preserve scientifically necessary third-party provenance while removing
  author-owned URLs.
- [ ] Confirm the live OpenReview form accepts the ZIP size.

Rebuild from repository root:

```bash
env TMPDIR=/home/midhun/Documents/MX/local_tmp \
  .venv/bin/python papers/paper1/aaai/artifact/build_artifact.py
```

## 12. Build the three PDFs

From the repository root:

```bash
podman run --rm \
  -v "$PWD:/repo:Z" \
  -w /repo/papers/paper1/aaai \
  localhost/agentproof-tex:latest \
  sh -lc 'latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex &&
          latexmk -pdf -interaction=nonstopmode -halt-on-error supplement.tex &&
          latexmk -pdf -interaction=nonstopmode -halt-on-error ReproducibilityChecklist.tex'
```

Required outputs:

- `papers/paper1/aaai/main.pdf`
- `papers/paper1/aaai/ReproducibilityChecklist.pdf`
- `papers/paper1/aaai/supplement.pdf`

## 13. Automated PDF checks

```bash
manuscript=papers/paper1/aaai
for pdf in main ReproducibilityChecklist supplement; do
  pdfinfo "$manuscript/$pdf.pdf"
  pdffonts "$manuscript/$pdf.pdf"
  pdfdetach -list "$manuscript/$pdf.pdf"
done

rg -n \
  'Overfull|LaTeX Error|undefined references|Citation.*undefined|Warning.*undefined' \
  "$manuscript/main.log" \
  "$manuscript/ReproducibilityChecklist.log" \
  "$manuscript/supplement.log"
```

Expected: the final `rg` prints nothing; PDFs are US Letter, unencrypted, use
only embedded Type 1/TrueType fonts, and have zero embedded files.

Use `/home/midhun/Documents/MX/local_tmp`, not `/tmp`, for extracted-text and
archive scans. Confirm main page 1 is anonymous and main page 8 contains
references only.

## 14. Scientific and archive verification

Minimum gates:

```bash
.venv/bin/python -m pytest -q
git diff --check

extract_root=$(mktemp -d -p /home/midhun/Documents/MX/local_tmp \
  agentproof-review.XXXXXX)
unzip -q papers/paper1/aaai/artifact/agentproof-anonymized.zip \
  -d "$extract_root"
cd "$extract_root/workflow_verifier"
env PYTHONPATH=src \
  /home/midhun/Documents/MX/Research/AgentProof/.venv/bin/python \
  -m pytest tests/ -q
```

Also run every command advertised by `ARTIFACT_README.md`. Record failures
honestly; do not report interrupted or unrun checks as passing.

## 15. OpenReview fields

- [ ] Title and abstract exactly match `main.tex`.
- [ ] TL;DR is conservative and no broader than the evidence.
- [ ] Topics accurately describe the work.
- [ ] Author list, order, conflicts, and declarations are correct.
- [ ] Reviewer-visible anonymous fields contain no identifying text.

Operator copy: `submission/upload_ready/OPENREVIEW_FIELDS.md`.

## 16. Upload mapping

Upload only these files from `submission/upload_ready/`:

1. `01_main_anonymous.pdf` — main-paper field.
2. `02_reproducibility_checklist.pdf` — designated checklist field.
3. `03_supplement_anonymous.pdf` — supplementary-document field.
4. `04_code_data_anonymous.zip` — code/data field.

Do not upload `SUBMISSION_RULES.md`, helper Markdown, `SHA256SUMS.txt`, TeX
sources, logs, repository history, or any other local file.

Regenerate the folder only after rebuilding all source artifacts:

```bash
.venv/bin/python papers/paper1/aaai/submission/make_upload_ready.py
```

## 17. Final pre-submit gate

- [ ] Rebuild and revalidate every deliverable from final source.
- [ ] Regenerate `upload_ready/` and verify `SHA256SUMS.txt`.
- [ ] Visually inspect first and last pages of each PDF.
- [ ] Confirm the main paper's page 8 contains references only.
- [ ] Confirm anonymity in all PDFs and the archive.
- [ ] Complete author-only declarations.
- [ ] Upload only the four numbered deliverables.
- [ ] Download each uploaded file, open it, and compare its hash.
- [ ] Recheck all OpenReview fields and save the submission ID.

## 18. Current verified status

As of 2026-07-29:

- Main paper: 8 US-Letter pages; page 8 contains references only.
- Checklist: 2 US-Letter pages.
- Supplement: 33 US-Letter pages.
- All PDFs are unencrypted, contain zero embedded files, and use embedded
  Type 1 fonts with no Type 3 fonts.
- PDF text and metadata identity scans pass.
- Logs have no LaTeX errors, overfull boxes, undefined citations, or undefined
  references.
- Full-checkout suite: 424 passed, 1 skipped. Anonymous archive advertised
  suite: 422 passed, 3 skipped after clean extraction; two additional skips
  require third-party source snapshots deliberately omitted from the archive.
  All three advertised analyses exit zero.
- Archive member-name/content scans pass; no symlinks, hidden files, caches,
  bytecode, repository history, author-owned URL, author identity, or private
  path was detected.
- `upload_ready/` hashes verify.

Author-only attestations and live OpenReview upload-size acceptance remain
open.
