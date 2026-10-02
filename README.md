# Kolkata Live Job Search

A live job search platform for Kolkata. Candidates search jobs or upload their CV and see **only currently open jobs** in Kolkata, ranked by how well they match, and apply directly on the company's site.

Final Year B.Tech Project · CSE (AI & ML) · Techno Main Salt Lake

## Features
- Live job data from public job APIs, updated automatically every few hours
- Manual search with filters: company, salary, skills, experience, work mode, area
- CV upload with AI matching and a personalised "Best for You" ranking
- Skill-gap analysis and an AI career assistant
- Employer portal with spam verification before jobs go live
- Admin panel for moderation, pipeline health and analytics

## Team
| Role | Area | Folder | Member |
|------|------|--------|--------|
| M1 | AI/ML Engineering | `AI &ml/` | _name_ |
| M2 | Data Engineering | `data_pipeline/` | _name_ |
| M3 | Backend, Database & Security | `backend/` | _name_ |
| M4 | Frontend & UI/UX | `frontend/` | _name_ |
| M5 | Employer Portal, Verification & Admin | `admin/` | _name_ |

## Project structure
kolkata-job-search/
├── data_pipeline/ collectors, cleaning, open/close check (M2)
├── backend/ FastAPI, database, auth, security (M3)
├── ml/ matching, ranking model, RAG assistant (M1)
├── frontend/ candidate web app, shared UI kit (M4)
├── admin/ employer portal, verification, admin (M5)
├── docs/ architecture diagram, guides, report
└── .github/ review rules and PR template


## Tech stack
Python · FastAPI · PostgreSQL (Supabase) · React + Tailwind CSS · sentence-transformers · XGBoost · GitHub Actions

## How to contribute
Read [CONTRIBUTING.md](CONTRIBUTING.md) before your first change.
Short version: **never push to `main`**. Work on your own branch, open a pull request, and wait for approval.