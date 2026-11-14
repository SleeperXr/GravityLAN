# GravityLAN Tests

This directory serves as a guide for running tests in GravityLAN.

To keep the repository clean and structured, the testing suites are located within their respective components:

*   **Backend Tests**: Located in [backend/tests/](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/backend/tests). These are automated tests for the FastAPI endpoints, authentication, database migrations, scanner, and agent adoption.
*   **CI/CD Workflow**: Configured in [.github/workflows/ci.yml](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/.github/workflows/ci.yml) to automatically run linting and pytest suites on every push and pull request.

---

## Running Backend Tests Locally

To run the backend test suite, follow these steps:

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Activate your virtual environment (if not already done).
3. Install the development dependencies:
   ```bash
   pip install -r requirements.txt pytest pytest-asyncio
   ```
4. Execute the test suite using `pytest`:
   ```bash
   python -m pytest
   ```

## Running Frontend Verification

To verify that GravityUI builds and compiles without TypeScript errors:

1. Navigate to the GravityUI directory:
   ```bash
   cd frontend-vue
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Run the TypeScript type check compiler:
   ```bash
   npm run typecheck
   ```

## Running the Browser Smoke Tests

Two Playwright tests in `frontend-vue/e2e/` walk a fresh install through the setup wizard and sign in and out. They start the demo backend (`scripts/dev_demo.py --fresh`: no scans, no SSH, 127.0.0.1 only) and the Vite dev server themselves, and stop if port 8000 or 5174 is already in use, so they never touch a real instance. CI runs them in the `e2e` job.

```bash
cd frontend-vue
npx playwright install chromium   # once
GRAVITYLAN_E2E_PYTHON=../.venv/bin/python npm run test:e2e
```

`GRAVITYLAN_E2E_PYTHON` names a Python with the backend dependencies (default: `python`).
