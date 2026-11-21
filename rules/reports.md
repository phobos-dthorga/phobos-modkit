# Reports to other authors

How a fault in another author's mod, tool or framework is reported, in every game (owner, 22 Nov 2026: "We'll make this the
handling of issue reports to all third-party authors, moving forward", after Vehicle Framework's turret-queue report,
[issue #390](https://github.com/SmashPhil/Vehicle-Framework/issues/390)). Read it before drafting a report, and again when the
owner says one is posted. Whether to patch the fault ourselves is each repository's own rule; this file is only the report.

## Before drafting

- **Find the fault with the tools, and carry what they showed**: the log lines word for word, the saved data, the chain that
  leads to the fault, and the author's own source lines with file and line number. Never a guess from reading alone.
- **Check the fault is still in the author's newest public source** (their default branch, not only the build installed), and
  say which build and which date the report was checked against.
- **Look for an existing report first, and say where you looked**: every issue and pull request in the author's repository,
  listed in full (GitHub's search can return nothing even where there are matches), and the mod page's comments or discussions.
  Where one exists, the draft is a comment on it with what is new, never a second report.

## The draft

- **It goes in the owner's private report tracker** (a claude.ai page, "Mod Author Reports", its `reports` collection), never
  in a public repository: some authors take badly to any AI part in a report. Status "drafted", one entry per fault.
- **Plain and factual, short sentences**: the versions; what goes wrong for a player; the code line at fault; the exact error;
  what is lost; how it was seen; a suggested fix where one is clear; "log available on request". No polish, no blame.
- **Ready to paste as it stands** (learnt from #390, which the owner had to tidy by hand):
  - **the title on its own** (the entry's `title`), never as a "Title:" line inside the body;
  - **code, errors and stack lines in fenced code blocks**;
  - **any name holding `<`, `>`, `_` or `*` in backticks**: GitHub hides `<turretQueue />` as an unknown tag, leaving a gap;
  - **the label to choose** (Bug, where the tracker has one).
- **Its `checkFirst` says how to tell whether the fault is gone**, so it can be checked again before posting, and `patch` names
  our own workaround where there is one.

## Posting and after

- **Agents never post, comment, react or follow up on another author's page.** The owner posts, on the author's own channel
  (GitHub issues where they exist), and decides which reports to post.
- **Once the owner says it is posted, check how it shows**: read the posted text as the page renders it (for GitHub, the
  issue's HTML), and tell the owner of anything hidden or broken, with the fix to make.
- **Then mark it posted everywhere it is recorded, in one go**: the tracker entry (`posted`, the date, the link), the
  repository's register of patches for other authors' faults, and any design record that names the report.
- **When the author's mod next updates, check whether the fault is gone** (the `checkFirst`), mark it `fixed`, and retire our
  workaround under the repository's own rules. Never ask the owner whether a report went out, and never chase the author.
