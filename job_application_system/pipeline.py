from __future__ import annotations

import csv
import math
import re
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class ProcessStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    COMPILATION_ERROR = "COMPILATION_ERROR"
    SUCCESS = "SUCCESS"


@dataclass(frozen=True)
class JinjaDelimiterConfig:
    block_start_string: str = "((*"
    block_end_string: str = "*))"
    variable_start_string: str = "((("
    variable_end_string: str = ")))"
    comment_start_string: str = "((="
    comment_end_string: str = "=))"


@dataclass
class AppState:
    candidate_profile_md: str
    latex_template_str: str
    candidate_years_experience: float
    threshold: float = 75.0
    scraped_jobs: list[dict[str, Any]] = field(default_factory=list)
    current_job: dict[str, Any] = field(default_factory=dict)
    match_analysis: dict[str, Any] = field(default_factory=dict)
    tailored_resume_tex: str = ""
    cover_letter_md: str = ""
    compiled_artifacts: dict[str, str] = field(default_factory=dict)
    process_status: ProcessStatus | None = None


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9\+\#\.]+", text.lower())


def _cosine_similarity(a: str, b: str) -> float:
    tokens_a = Counter(_tokenize(a))
    tokens_b = Counter(_tokenize(b))
    if not tokens_a or not tokens_b:
        return 0.0
    shared = set(tokens_a) & set(tokens_b)
    numerator = sum(tokens_a[t] * tokens_b[t] for t in shared)
    denom = math.sqrt(sum(v * v for v in tokens_a.values())) * math.sqrt(
        sum(v * v for v in tokens_b.values())
    )
    if denom == 0:
        return 0.0
    return numerator / denom


def _keyword_overlap(a: str, b: str) -> float:
    cand = set(_tokenize(a))
    jd = set(_tokenize(b))
    if not jd:
        return 0.0
    return len(cand & jd) / len(jd)


def compute_profile_matching_percentage(
    candidate_profile_md: str,
    job_description: str,
    candidate_years_experience: float,
    required_years_experience: float,
    w1: float = 0.4,
    w2: float = 0.4,
    w3: float = 0.2,
) -> float:
    vector_score = _cosine_similarity(candidate_profile_md, job_description)
    keyword_score = _keyword_overlap(candidate_profile_md, job_description)
    req = max(required_years_experience, 1e-6)
    experience_score = min(1.0, max(0.0, candidate_years_experience / req))
    score = (w1 * vector_score + w2 * keyword_score + w3 * experience_score) * 100
    return round(max(0.0, min(100.0, score)), 2)


def compute_hiring_chance(
    profile_matching_percentage: float,
    mandatory_requirement_penalties: list[float],
    posting_age_hours: float,
    decay_lambda: float = 0.01,
) -> float:
    factor = 1.0
    for penalty in mandatory_requirement_penalties:
        p = max(0.0, min(1.0, penalty))
        factor *= 1 - p
    age = min(48.0, max(0.0, posting_age_hours))
    score = profile_matching_percentage * factor * math.exp(-decay_lambda * age)
    return round(max(0.0, min(100.0, score)), 2)


def escape_latex_characters(text: str) -> str:
    conv = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
    regex = re.compile(
        "|".join(re.escape(str(key)) for key in sorted(conv.keys(), key=lambda x: -len(x)))
    )
    return regex.sub(lambda m: conv[m.group(0)], text)


class DiscoveryIngestionAgent:
    def ingest(self, jobs: list[dict[str, Any]], max_hours_old: int = 48) -> list[dict[str, Any]]:
        seen_ids: set[str] = set()
        filtered = []
        for job in jobs:
            job_id = str(job.get("id", ""))
            if not job_id or job_id in seen_ids:
                continue
            if float(job.get("hours_old", 10_000)) > max_hours_old:
                continue
            seen_ids.add(job_id)
            filtered.append(job)
        return filtered


class QualificationEvaluatorAgent:
    def evaluate(self, state: AppState) -> ProcessStatus:
        required_years = float(state.current_job.get("required_years_experience", 0.0))
        profile_match = compute_profile_matching_percentage(
            candidate_profile_md=state.candidate_profile_md,
            job_description=str(state.current_job.get("description", "")),
            candidate_years_experience=state.candidate_years_experience,
            required_years_experience=required_years,
        )
        penalties = state.current_job.get("mandatory_requirement_penalties", [])
        hiring_chance = compute_hiring_chance(
            profile_matching_percentage=profile_match,
            mandatory_requirement_penalties=list(penalties),
            posting_age_hours=float(state.current_job.get("hours_old", 0.0)),
        )
        state.match_analysis = {
            "profile_matching_percentage": profile_match,
            "hiring_chances": hiring_chance,
            "skill_gaps": state.current_job.get("skill_gaps", []),
        }
        state.process_status = (
            ProcessStatus.QUALIFIED if profile_match >= state.threshold else ProcessStatus.DISQUALIFIED
        )
        return state.process_status


class DocumentTailoringSpecialistAgent:
    def tailor(self, state: AppState) -> None:
        job_title = escape_latex_characters(str(state.current_job.get("title", "Unknown Role")))
        company = escape_latex_characters(str(state.current_job.get("company", "Unknown Company")))
        jd = escape_latex_characters(str(state.current_job.get("description", "")))
        state.tailored_resume_tex = (
            state.latex_template_str.replace("{{JOB_TITLE}}", job_title)
            .replace("{{COMPANY}}", company)
            .replace("{{JOB_DESCRIPTION}}", jd)
        )
        state.cover_letter_md = (
            f"Dear Hiring Team at {company},\n\n"
            f"I am excited to apply for the {job_title} role. "
            "My background aligns with your requirements and I can defend all claims.\n"
        )


class CompilationRegistryManagerAgent:
    _lock = threading.Lock()

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.resume_dir = self.output_dir / "resumes"
        self.cover_dir = self.output_dir / "cover_letters"
        self.merged_dir = self.output_dir / "merged_applications"
        for folder in (self.resume_dir, self.cover_dir, self.merged_dir):
            folder.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.output_dir / "application_registry.csv"

    def _write_registry_row(self, row: dict[str, Any]) -> None:
        fieldnames = [
            "id",
            "jd_path",
            "resume_path",
            "cover_letter_path",
            "profile_matching_percentage",
            "hiring_chances",
        ]
        with self._lock:
            file_exists = self.registry_file.exists()
            with self.registry_file.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)

    def compile_and_register(
        self,
        state: AppState,
        compiler: Callable[[str], tuple[bool, str]],
        max_attempts: int = 3,
    ) -> ProcessStatus:
        job_id = str(state.current_job.get("id", uuid.uuid4().hex))
        resume_pdf = self.resume_dir / f"resume_{job_id}.pdf"
        cover_pdf = self.cover_dir / f"cover_{job_id}.pdf"
        merged_pdf = self.merged_dir / f"application_{job_id}.pdf"

        tex_input = state.tailored_resume_tex
        success = False
        for _ in range(max_attempts):
            success, _ = compiler(tex_input)
            if success:
                break
            tex_input = state.latex_template_str

        if not success:
            state.process_status = ProcessStatus.COMPILATION_ERROR
            return state.process_status

        resume_pdf.write_bytes(b"%PDF-1.4\n% resume")
        cover_pdf.write_bytes(b"%PDF-1.4\n% cover letter")
        merged_pdf.write_bytes(b"%PDF-1.4\n% merged")
        state.compiled_artifacts = {
            "resume_pdf": str(resume_pdf),
            "cover_letter_pdf": str(cover_pdf),
            "combined_pdf": str(merged_pdf),
        }
        self._write_registry_row(
            {
                "id": f"job_{uuid.uuid4().hex[:8]}",
                "jd_path": str(self.output_dir / f"jd_{job_id}.json"),
                "resume_path": str(resume_pdf),
                "cover_letter_path": str(cover_pdf),
                "profile_matching_percentage": state.match_analysis.get(
                    "profile_matching_percentage", 0.0
                ),
                "hiring_chances": state.match_analysis.get("hiring_chances", 0.0),
            }
        )
        state.process_status = ProcessStatus.SUCCESS
        return state.process_status


class WorkflowOrchestrator:
    def __init__(
        self,
        discovery_agent: DiscoveryIngestionAgent,
        evaluator_agent: QualificationEvaluatorAgent,
        tailoring_agent: DocumentTailoringSpecialistAgent,
        compilation_agent: CompilationRegistryManagerAgent,
    ) -> None:
        self.discovery_agent = discovery_agent
        self.evaluator_agent = evaluator_agent
        self.tailoring_agent = tailoring_agent
        self.compilation_agent = compilation_agent

    def run(
        self,
        state: AppState,
        jobs: list[dict[str, Any]],
        compiler: Callable[[str], tuple[bool, str]],
    ) -> list[AppState]:
        processed: list[AppState] = []
        state.scraped_jobs = self.discovery_agent.ingest(jobs)
        for job in state.scraped_jobs:
            state.current_job = job
            status = self.evaluator_agent.evaluate(state)
            if status == ProcessStatus.DISQUALIFIED:
                processed.append(state)
                continue
            self.tailoring_agent.tailor(state)
            self.compilation_agent.compile_and_register(state, compiler=compiler)
            processed.append(state)
        return processed
