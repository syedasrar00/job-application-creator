import tempfile
import unittest
from pathlib import Path

from job_application_system.pipeline import (
    AppState,
    CompilationRegistryManagerAgent,
    DiscoveryIngestionAgent,
    DocumentTailoringSpecialistAgent,
    ProcessStatus,
    QualificationEvaluatorAgent,
    WorkflowOrchestrator,
    escape_latex_characters,
)


class PipelineTests(unittest.TestCase):
    def test_escape_latex_characters(self) -> None:
        text = r"A&B 100% #1_{ok}\path"
        escaped = escape_latex_characters(text)
        self.assertIn(r"\&", escaped)
        self.assertIn(r"\%", escaped)
        self.assertIn(r"\#", escaped)
        self.assertIn(r"\_", escaped)
        self.assertIn(r"\{", escaped)
        self.assertIn(r"\}", escaped)
        self.assertIn(r"\textbackslash{}", escaped)

    def test_discovery_filters_duplicates_and_old_jobs(self) -> None:
        jobs = [
            {"id": "1", "hours_old": 12},
            {"id": "1", "hours_old": 12},
            {"id": "2", "hours_old": 72},
            {"id": "3", "hours_old": 4},
        ]
        result = DiscoveryIngestionAgent().ingest(jobs)
        self.assertEqual([j["id"] for j in result], ["1", "3"])

    def test_orchestrator_routes_disqualified_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            state = AppState(
                candidate_profile_md="python backend",
                latex_template_str="Resume for {{JOB_TITLE}} at {{COMPANY}}",
                candidate_years_experience=1,
                threshold=90,
            )
            orchestrator = WorkflowOrchestrator(
                discovery_agent=DiscoveryIngestionAgent(),
                evaluator_agent=QualificationEvaluatorAgent(),
                tailoring_agent=DocumentTailoringSpecialistAgent(),
                compilation_agent=CompilationRegistryManagerAgent(output_dir),
            )
            jobs = [
                {
                    "id": "job1",
                    "title": "ML Engineer",
                    "company": "ACME",
                    "description": "kubernetes rust",
                    "required_years_experience": 10,
                    "hours_old": 2,
                }
            ]

            calls = {"count": 0}

            def compiler(_: str) -> tuple[bool, str]:
                calls["count"] += 1
                return True, ""

            result = orchestrator.run(state=state, jobs=jobs, compiler=compiler)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].process_status, ProcessStatus.DISQUALIFIED)
            self.assertEqual(calls["count"], 0)

    def test_compilation_retries_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CompilationRegistryManagerAgent(Path(tmp))
            state = AppState(
                candidate_profile_md="python backend",
                latex_template_str="baseline template",
                candidate_years_experience=5,
            )
            state.current_job = {"id": "job2"}
            state.tailored_resume_tex = "tailored template"
            state.match_analysis = {
                "profile_matching_percentage": 85.0,
                "hiring_chances": 70.0,
            }
            attempts = {"count": 0}

            def compiler(_: str) -> tuple[bool, str]:
                attempts["count"] += 1
                return attempts["count"] >= 2, "error"

            status = manager.compile_and_register(state, compiler=compiler)
            self.assertEqual(status, ProcessStatus.SUCCESS)
            self.assertEqual(attempts["count"], 2)
            self.assertTrue(Path(state.compiled_artifacts["combined_pdf"]).exists())
            self.assertTrue((Path(tmp) / "application_registry.csv").exists())


if __name__ == "__main__":
    unittest.main()
