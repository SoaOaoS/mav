# Contributing to Mav

## Commit messages decide the version

Every push to `main` is released automatically with a semantic version
computed from the commit messages since the last tag
(`scripts/next-version.sh`). Write them as
[Conventional Commits](https://www.conventionalcommits.org):

```
feat(routines): weekly routines on chosen days      → minor release
fix(memory): don't store the same fact twice         → patch release
docs: explain connections                            → patch release
feat!: remove the Telegram bot                       → major release
```

A `BREAKING CHANGE:` footer also makes a major release. Preview the next
version with `scripts/next-version.sh --explain`.

## Before opening a pull request

The CI runs the same checks; run them locally first:

```bash
shellcheck -S warning install.sh get.sh run-opencode.sh scripts/mav scripts/next-version.sh tests/*.sh
python3 -m py_compile bot/*.py dashboard/server/*.py dashboard/tools/*.py
for f in dashboard/assets/js/*.js; do node --check "$f"; done
bash tests/test_next_version.sh && bash tests/test_cli.sh
python3 -m unittest discover -s tests -v
```

To work on the web app without a model, see
[dashboard/README.md](dashboard/README.md) (`dashboard/tools/fake_engine.py`).
