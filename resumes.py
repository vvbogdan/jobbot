# -*- coding: utf-8 -*-
"""
Base resumes — the raw material resumes are tailored from via the Claude API.
Keys must match the "resume_key" of a profile in config.py (or one you add with /addprofile).

Format is free-form plain text: the more detailed and truthful, the better the model can
tailor it. Never invent facts here (dates, companies, numbers) — only what's actually true.

This is a public, tracked-in-git file, so it ships with ONE made-up example ("Frontend", a
fictional person) — just enough for the "Tailor resume"/"cover letter" buttons to work out of
the box and to show the expected format. Don't put your real resume here if this repo (or a
fork of it) is public.

Instead, create resumes_local.py next to this file (same BASE_RESUMES dict shape) with your
real resume — it's in .gitignore, never committed, and jobbot.py automatically prefers it over
this file when it exists. That's how the actual deployment (yours, on Render) keeps using your
real resume while the public repo only ever shows this placeholder.
"""

BASE_RESUMES = {
    "Frontend": """
Jane Doe — Frontend Developer · React / TypeScript / UI Engineering
jane.doe@example.com | +1 (555) 010-2030 | linkedin.com/in/janedoe-example | Remote

SUMMARY
Frontend developer with 3 years of experience building responsive, accessible web
applications with React and TypeScript. Comfortable owning a feature from design handoff to
production, with a focus on clean component architecture and performance.

SKILLS
- JavaScript / TypeScript — production, 3 yrs
- React, React Router, React Query — primary stack
- State management: Redux Toolkit, Zustand, Context API
- Styling: CSS Modules, Tailwind CSS, Styled Components
- Testing: Jest, React Testing Library, Cypress (E2E)
- Tooling: Vite, Webpack, ESLint/Prettier, Git
- Basics: Node.js/Express (small internal tools), REST APIs, GraphQL (consumer side)

EXPERIENCE
Frontend Developer | Example Retail Co. | 2024 – Present
- Built and maintained customer-facing React features for an e-commerce platform (product
  listing, checkout flow, order tracking).
- Migrated a legacy jQuery widget to React + TypeScript, cutting related bug reports by ~40%.
- Collaborated with design on a component library used across three internal products.
Technologies: React, TypeScript, Redux Toolkit, Jest, Tailwind CSS

Junior Frontend Developer | Example Agency | 2022 – 2024
- Delivered marketing sites and landing pages for agency clients using React and Next.js.
- Implemented responsive layouts from Figma designs with pixel-level accuracy.
- Set up CI checks (lint, type-check, test) for two client repositories.
Technologies: React, Next.js, JavaScript, CSS, Figma

EDUCATION
B.Sc. in Computer Science — Example State University, 2022

NOTE TO WHOEVER IS USING THIS BOT: this is placeholder content so the bot works immediately.
Replace this whole entry with your own real resume (same free-text format) before relying on
the tailored PDFs for actual applications.
""",
}
