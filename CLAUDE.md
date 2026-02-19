# Social-vibes – Claude Instructions

## Git & PR Workflow

After pushing changes, **always open a Pull Request** targeting `main` so the user
can review and approve before anything is merged.

Steps:
1. Develop on a dedicated feature branch (e.g. `claude/<short-description>`).
2. Commit with clear, descriptive messages.
3. Push the branch with `git push -u origin <branch>`.
4. Open a PR with `gh pr create` targeting `main`, with a short title and a summary
   of what changed and why.
5. Do **not** merge the PR yourself — leave that to the user.
