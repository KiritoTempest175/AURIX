# Removing previously committed personal vault data

The current main branch removes old tracked `vault/` and `aurix_vault/` files, replacing them with a non-personal persona file at `config/LUNA.md`.

**Important:** Removing files from the current branch does **not** remove them from Git commit history, caches, forks, local clones or mirrors. Treat old user data as potentially exposed. Review it and rotate any credentials, API keys or other secrets that were included.

To fully remove sensitive material, plan a coordinated history rewrite using `git-filter-repo`, ensure all collaborators are informed, force-push protected refs only during an announced maintenance window, and remove old tags/releases as necessary. GitHub may need to purge cached references; follow its sensitive-data removal guidance. Rewriting history is intentionally **not** performed automatically by this update.

At runtime, put private memory in an operating-system-controlled user data directory (e.g. `%LOCALAPPDATA%\\AURIX\\vault`) and configure encryption/backup before enabling durable personal memory. Current code is not yet fully migrated to that location.
