# job-application-creator

Minimal four-agent architecture implementation for tailored job-application workflows.

## Implemented architecture

- **Agent 1 – Discovery & Ingestion**: filters duplicate/old jobs (`<=48h`).
- **Agent 2 – Qualification Evaluator**: computes profile-match and hiring-chance scores, then routes by threshold.
- **Agent 3 – Document Tailoring Specialist**: tailors resume/cover-letter content and escapes LaTeX-sensitive characters.
- **Agent 4 – Compilation & Registry Manager**: retry-aware compile stage with artifact output paths and atomic CSV registry append.

## State model

The workflow uses a typed shared state (`AppState`) containing:
`candidate_profile_md`, `latex_template_str`, `scraped_jobs`, `current_job`, `match_analysis`, `tailored_resume_tex`, `cover_letter_md`, `compiled_artifacts`, and `process_status`.

## Key implementation details

- Custom Jinja/LaTeX delimiter configuration model (`JinjaDelimiterConfig`) using:
  - `((* *))`, `((( )))`, `((= =))`
- Scoring functions:
  - `compute_profile_matching_percentage(...)`
  - `compute_hiring_chance(...)`
- TeX-safe sanitation:
  - `escape_latex_characters(...)`
- Deterministic orchestration:
  - `WorkflowOrchestrator.run(...)`

## Tests

Run focused tests:

```bash
python -m unittest -v tests/test_pipeline.py
```