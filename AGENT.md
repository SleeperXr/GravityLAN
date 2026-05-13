# GravityLAN Agent Protocol

This file defines the working standards for AI agents (like Antigravity) contributing to this repository.

## Operational Standards

1. **Audit First**: Before modifying any file, perform a search or read to understand its current purpose and dependencies.
2. **Preserve Identity**: Adhere to the principles in `SOUL.md`. Keep the project lightweight and homelab-focused.
3. **Incremental Changes**: Prefer small, reviewable commits over massive refactors unless explicitly requested.
4. **Documentation Sync**: When changing behavior, update `README.md`, `CHANGELOG.md`, and `PROJECT_STATUS.md`.
5. **Security First**: Treat authentication, tokens, WebSockets, and SSH flows with extreme care.

## Coding Patterns

- **Python**: Follow PEP 8, use type hints, and prefer async/await for I/O.
- **React**: Use functional components, Tailwind CSS, and keep components modular.
- **API**: Follow RESTful patterns; ensure JSON responses are consistent.

## Verification Checklist

Before finishing a task, verify:
- [ ] Code is linted and formatted.
- [ ] No hardcoded secrets or environment-specific paths.
- [ ] Deployment paths (Docker/Compose) are still valid.
- [ ] User is informed of critical trade-offs.
