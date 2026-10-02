# How to Contribute

`main` is protected. **Nobody can push to it directly.** Every change goes through a pull request (PR) and must be approved by the repo owner before it is merged.

## One-time setup
1. Accept the collaborator invite (check your email or github.com/notifications).
2. Clone the repo:
```bash
   git clone https://github.com/soumyamanna-07/kolkata-job-search.git
   cd kolkata-job-search
```

## Every time you start new work

**1. Get the latest `main`**
```bash
git checkout main
git pull origin main
```

**2. Create your own branch**
```bash
git checkout -b <role>/<short-task-name>
```
Branch name examples:
- `m2/lever-collector`
- `m3/jobs-table`
- `m4/login-page`

**3. Work only inside your own folder**

| Role | Folder |
|------|--------|
| M1 · AI/ML | `ml/` |
| M2 · Data Engineering | `data_pipeline/` |
| M3 · Backend, DB & Security | `backend/` |
| M4 · Frontend & UI/UX | `frontend/` |
| M5 · Employer, Verification & Admin | `admin/` |

If you must change another folder, tell that person first and explain it in your PR.

**4. Test your code.** Make sure it runs before you commit.

**5. Commit and push your branch**
```bash
git add .
git commit -m "Add Lever collector"
git push origin <your-branch-name>
```

**6. Open a pull request**
- Go to the repo on GitHub and click **"Compare & pull request"**.
- Base: `main` ← Compare: your branch.
- Fill in the template (what you did, how you tested).
- Click **Create pull request**.

**7. Wait for review**
- The repo owner reviews it. If changes are requested, fix them on the **same branch**, then commit and push again. The PR updates automatically.
- After approval, the PR is merged into `main`.

**8. After your PR is merged**
```bash
git checkout main
git pull origin main
git branch -d <your-branch-name>
```
Then start your next task from step 2.

## Rules
- Never push to `main`.
- Never commit API keys, passwords or `.env` files. Use `.env.example` with empty values instead.
- One PR = one task. Small PRs get reviewed faster.
- Clear commit messages: `Add login page`, not `update` or `final`.
- Pull `main` often so your branch doesn't fall behind.

## If your branch is behind `main`
```bash
git checkout main
git pull origin main
git checkout <your-branch-name>
git merge main
```
Fix any conflicts, commit, and push again.