# Social-vibes – Claude Instructions

## Git & PR Workflow

After pushing changes, **always open a Pull Request** targeting `main` so the user
can review and approve before anything is merged.

Steps:
1. **Before starting work**, check for an existing open PR:
   - Run `gh pr list --state open --author "@me" --json number,title,headRefName` to list open PRs.
   - If an open PR exists for related work, check it out (`git fetch origin <branch> && git checkout <branch>`) and commit new work there — do **not** create a new branch.
   - If no relevant open PR exists, create a new branch: `claude/<short-description>`.
2. Develop on the chosen branch and commit with clear, descriptive messages.
3. Push with `git push -u origin <branch>`.
4. After pushing, check if a PR already exists for the current branch:
   - Run `gh pr list --head <branch-name> --state open`.
   - If an open PR exists, **reuse it** (no action needed — new commits update it automatically).
   - If no open PR exists (e.g. it was merged or closed), open a new one with `gh pr create`.
5. Do **not** merge the PR yourself — leave that to the user.
