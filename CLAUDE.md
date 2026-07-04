# status-line

A Claude Code plugin (statusline script). Distributed via a separate marketplace repo, not a marketplace of its own.

## After pushing changes here

This repo has no `.claude-plugin/marketplace.json` — it's listed as a plugin in [kerryhatcher/plugin-marketplace](https://github.com/kerryhatcher/plugin-marketplace), which pins it to a specific commit `sha`. Whenever you push a commit here that should actually reach installed users:

1. Get the new commit hash: `git -C /home/kwhatcher/projects/status-line rev-parse HEAD`
2. In `/home/kwhatcher/projects/plugin-marketplace/.claude-plugin/marketplace.json`, update the `status-line` plugin entry's `source.sha` to that hash.
3. `claude plugin validate /home/kwhatcher/projects/plugin-marketplace`
4. Commit and push in the `plugin-marketplace` repo.

Until that pin is bumped, `claude plugin install`/`update` for `status-line@plugin-marketplace` keeps serving the old commit.
