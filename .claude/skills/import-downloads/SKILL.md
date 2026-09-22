---
name: import-downloads
description: Only for explicit invocation via /import-downloads when the user says a new batch of files has been downloaded into the repo's drop folder and needs sorting. Do not invoke this autonomously based on other context — file routing only happens when the user asks for it.
---

# Import downloads

Route a newly downloaded batch of project files from the repo's drop folder into their correct locations, then clear the folder for reuse.

The drop folder is a persistent landing zone, not a one-time staging area — it is never deleted, only emptied.

## Steps

1. **Locate the drop folder.** Look for a consistently-named folder in the working directory used for this purpose before (check recent context or ask if this is the first run and no convention exists yet). Confirm before proceeding if there's any ambiguity — do not guess between multiple candidates.

2. **Extract if needed.** If there's a `files.zip` (or similarly named archive) in the drop folder, extract it into a temporary subfolder first rather than directly into the repo, so nothing collides before it's been checked.

3. **Identify every file by its own content — never by filename or current location alone.** A batch may mix skills, agents, docs, and root-level files together, and a zip's folder structure may have partially flattened during download.
   - Every file matching `SKILL*.md` — this includes OS-renamed duplicates like `SKILL (1).md`, `SKILL (2).md`, which happen whenever a browser downloads multiple same-named `SKILL.md` files into one folder in the same batch. The suffix is disk noise, not identity — read the file's YAML frontmatter `name:` field, which is unaffected by what the OS renamed the file to, and move to `.claude/skills/<name-from-frontmatter>/SKILL.md`. Quote every filename in any shell command — a bare `mv $file $dest` breaks on spaces and parentheses.
   - `CLAUDE.md`: always an intentional update. Read both incoming and current repo-root versions — if the current one has content the incoming one lacks (edited directly since), merge that in rather than overwriting blindly.
   - `CHANGELOG.md`: same merge check as CLAUDE.md.
   - Any other `.md` file whose frontmatter has a `tools:` field: it's an agent. Move to `.claude/agents/<filename>.md`, flat, no subfolder.
   - `acme-corp-*.md` or `acme-corp-*.pptx`: move to `docs/`.
   - Anything not matching one of the above: stop and ask what it is rather than guessing a destination.

4. **Never silently overwrite a differing file.** If a destination file already exists and differs from the incoming version, show a diff summary and ask which should win. If identical, just confirm and move on.

5. **Report a full inventory** — what was found and where it was placed — checked against the expected set below. Absence is not an error, just note it:
   - Skills: `generate-gtm-data`, `validate-gtm-data`, `sync-portfolio-docs`, `dbt-conventions`, `analytics-engineering-conventions`, `external-repo-conventions`, `import-downloads`
   - Agents: `dbt-model-writer`, `dbt-test-runner`, `dbt-docs-writer`, `semantic-layer-builder`, `semantic-layer-validator`, `repo-audit`
   - Root: `CLAUDE.md`, `CHANGELOG.md`

6. **Clear the drop folder's contents** — delete `files.zip`, any temporary extraction subfolder, and every file that was moved out of it. **Do not delete the drop folder itself.** It stays in place, empty, ready for the next batch.

7. **Re-read `CLAUDE.md` and any changed `docs/` files in full** if this import changed either, before doing anything else in the session.
