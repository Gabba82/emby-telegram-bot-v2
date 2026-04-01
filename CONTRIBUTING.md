# Contributing

Thanks for helping improve this project.

## Local setup

1. Fork and clone the repository.
2. Create your branch from `main`.
3. Install dependencies:
```bash
pip install -r requirements.txt
```
4. Run tests:
```bash
python -m pytest -q -p no:cacheprovider
```

## Pull requests

- Keep PRs small and focused.
- Explain what changed and why.
- Include test updates when behavior changes.
- Do not commit secrets or `.env`.

## Code style

- Python 3.11+
- Keep modules simple and readable.
- Prefer explicit error logging for webhook/integration issues.

