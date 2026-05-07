# test1 sync marker

Diagnostic file. Sole purpose: be obvious in the Databricks file tree
once the workspace folder has actually pulled the `test1` branch.

If this file is visible in
`/Workspace/Users/ethan.hall@kentro.us/ts-rnd-explainable-ai/`, the
Databricks Repos sync is working — at minimum for new files. If the
file is NOT visible after switching the Repos folder to `test1` and
clicking Pull, the workspace is not actually pulling the branch you
think it is (Repos pinned to a different commit, or pointed at a
different remote).

Created: 2026-05-04 (paired with debugging the
`_extract_embeddings` cached-module issue on Pandas/EmbedParser).
Safe to delete after the diagnostic is done.
