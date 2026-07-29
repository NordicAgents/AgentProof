# AAAI-27 upload checklist

This file and `OPENREVIEW_FIELDS.md` are operator notes. Do **not** upload
either Markdown file.

## Deadlines

- Main paper: July 28, 2026 at 23:59 UTC-12 (July 29 at 13:59 CEST).
- Supplementary material and code: July 31, 2026 at 23:59 UTC-12 (August 1 at
  13:59 CEST).
- After the main-paper deadline, do not change the main paper; update only
  permitted supplementary uploads during the supplementary window.

## Upload mapping

1. Upload `01_main_anonymous.pdf` as the main paper.
2. Upload `02_reproducibility_checklist.pdf` in the designated checklist
   field.
3. Upload `03_supplement_anonymous.pdf` as the supplementary document.
4. Upload `04_code_data_anonymous.zip` as the code/data package.
5. Do not upload this checklist, `OPENREVIEW_FIELDS.md`, `SHA256SUMS.txt`,
   TeX sources, logs, repository history, or other local files.

## Verified locally on 2026-07-29

- Main paper: 8 US-Letter pages; technical content and the conclusion end on
  page 7, while page 8 contains references only.
- Supplement: 33 US-Letter pages.
- Reproducibility checklist: 2 US-Letter pages.
- All PDFs are unencrypted, use embedded Type 1 fonts, contain no embedded
  files, and have no detected author identity in extracted text or metadata.
- The logs have no LaTeX errors, overfull boxes, undefined references, or
  undefined citations.
- The anonymous archive contains no symlinks, hidden files, caches, compiled
  bytecode, repository history, secrets, author-owned URL, author name, or
  local absolute path detected by the submission scan.
- The full checkout passes 424 tests with 1 skipped. The extracted archive's
  advertised clean-room command passes 422 tests with 3 skipped; two extra
  skips explicitly require third-party source snapshots that are not
  redistributed. Its three advertised analysis commands also exit
  successfully.
- The manuscript contains a generative-AI-use disclosure.

## Author-only checks before Submit

- [ ] Every author has approved the exact title, abstract, TL;DR, topics,
  author list, and author order.
- [ ] Every author has a complete OpenReview profile and correct conflicts.
- [ ] Reviewer-availability requirements are satisfied.
- [ ] No same or substantially overlapping work is under review at another
  archival venue, and the per-author submission limit is satisfied.
- [ ] The generative-AI disclosure accurately describes all assistance and
  has author approval.
- [ ] The ethics declaration is accurate: no plagiarism, fabrication,
  duplicate/near-duplicate submission, hidden reviewer instructions, prompt
  injection, or other prohibited manipulation.
- [ ] The reproducibility-checklist answers match the exact submitted
  artifact and the authors can honor every release promise.
- [ ] OpenReview accepts the ZIP size. If it does not, revise and completely
  revalidate the archive rather than silently omitting files.

## Final local checks

From this directory:

```bash
sha256sum -c SHA256SUMS.txt
```

- [ ] Open the first and last page of every PDF.
- [ ] Confirm page 1 of the main paper says `Anonymous Submission`.
- [ ] Confirm page 8 of the main paper contains references only.
- [ ] Confirm the title and abstract in OpenReview match
  `OPENREVIEW_FIELDS.md`.
- [ ] Confirm only the four numbered deliverables are uploaded.

## After upload

- [ ] Download all four files from OpenReview and open them.
- [ ] Verify the downloaded files against `SHA256SUMS.txt`.
- [ ] Recheck title, abstract, TL;DR, topics, authors, conflicts, and
  declarations in OpenReview.
- [ ] Save the submission ID and confirmation.
