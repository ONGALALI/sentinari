from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestFilesRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestUrlRequest(BaseModel):
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str
    limit: int = 8
    module: str | None = None
    topic: str | None = None
    scientific_field: str | None = None
    vocational_discipline: str | None = None
    source_collection: str | None = None


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    mode: Literal["knowledge", "coding", "questionnaire"] = "knowledge"
    top_k: int = 6
    behavior_variant: float = Field(default=0.1, ge=0.0, le=25.0)
    qualia_control: dict[str, Any] | None = None
    use_web_fetch: bool = False
    module: str | None = None
    topic: str | None = None
    scientific_field: str | None = None
    vocational_discipline: str | None = None
    source_collection: str | None = None


class TaxonomyConfigureRequest(BaseModel):
    scientific_fields: list[str] = Field(default_factory=list)
    vocational_disciplines: list[str] = Field(default_factory=list)
    curricula: list[str] = Field(default_factory=list)


class OpenAlexToggleRequest(BaseModel):
    enabled: bool


class UnsupervisedRebuildRequest(BaseModel):
    requested_clusters: int | None = Field(default=None, ge=1, le=500)
    scientific_field: str | None = None
    vocational_discipline: str | None = None
    source_collection: str | None = None
    min_chunks: int | None = Field(default=None, ge=4, le=100000)
    max_terms_per_cluster: int | None = Field(default=None, ge=3, le=30)
    force_lexical: bool = False


class ShellRunRequest(BaseModel):
    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    session_id: str | None = Field(default=None, max_length=120)
    workflow_step: str | None = Field(default=None, max_length=80)
    approval_token: str | None = Field(default=None, max_length=500)
    dry_run: bool = False


class PersonalityUpdateRequest(BaseModel):
    name: str = Field(default="SMi", max_length=200)
    tone: str = Field(default="", max_length=4000)
    default_language: str = Field(default="English", max_length=60)
    supported_languages: list[str] = Field(default_factory=list)
    purpose: str = Field(default="", max_length=24000)
    domain_focus: str = Field(default="", max_length=12000)
    out_of_scope_policy: str = Field(default="", max_length=12000)
    goals: list[str] = Field(default_factory=list)
    general_addendum: str = ""
    coding_mode_system_addendum: str = ""


class SafetyUpdateRequest(BaseModel):
    top_k_min: int = Field(default=0, ge=0, le=100)
    top_k_max: int = Field(default=20, ge=0, le=100)
    behavior_variant_min: float = Field(default=0.1, ge=0.0, le=25.0)
    behavior_variant_max: float = Field(default=25.0, ge=0.0, le=25.0)
    temperature_min: float = Field(default=0.0, ge=0.0, le=2.0)
    temperature_max: float = Field(default=0.7, ge=0.0, le=2.0)
    calm_mode_enabled: bool = True
    anxiety_keywords: list[str] = Field(default_factory=list)
    enforce_safe_completions: bool = True
    refuse_harmful_or_illegal: bool = True
    privacy_first: bool = True


class AdminLoginRequest(BaseModel):
    username: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=500)


class QualiaVectorControlRequest(BaseModel):
    enabled: bool = True
    alpha: float | None = Field(default=None, ge=0.0, le=1.0)
    beta: float | None = Field(default=None, ge=0.0, le=1.0)
    gamma: float | None = Field(default=None, ge=0.0, le=1.0)
    gamma_cap: float | None = Field(default=None, ge=0.0, le=0.25)
    steps: int | None = Field(default=None, ge=1, le=240)
    q0_x: float | None = Field(default=None, ge=-1.0, le=1.0)
    q0_y: float | None = Field(default=None, ge=-1.0, le=1.0)
    q0_z: float | None = Field(default=None, ge=-1.0, le=1.0)
    a0_x: float | None = Field(default=None, ge=-1.0, le=1.0)
    a0_y: float | None = Field(default=None, ge=-1.0, le=1.0)
    a0_z: float | None = Field(default=None, ge=-1.0, le=1.0)
    s_x: float | None = Field(default=None, ge=-1.0, le=1.0)
    s_y: float | None = Field(default=None, ge=-1.0, le=1.0)
    s_z: float | None = Field(default=None, ge=-1.0, le=1.0)
    stability_bias: float | None = Field(default=None, ge=0.0, le=1.0)
    bell_mu: float | None = Field(default=None, ge=0.0, le=1.0)
    bell_sigma: float | None = Field(default=None, ge=0.02, le=0.5)
    bell_amplitude: float | None = Field(default=None, ge=0.0, le=1.0)
    bell_points: int | None = Field(default=None, ge=11, le=401)


class PlaygroundChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    top_k: int = Field(default=6, ge=0, le=20)
    behavior_variant: float = Field(default=0.1, ge=0.0, le=25.0)
    reasoning_profile: Literal["auto", "normal", "assessment", "architecture"] = "normal"
    qualia_control: QualiaVectorControlRequest | None = None
    persona_name: str | None = None
    persona_tone: str | None = None
    module: str | None = None
    topic: str | None = None
    scientific_field: str | None = None
    vocational_discipline: str | None = None
    source_collection: str | None = None


class IntakeApproveRequest(BaseModel):
    """§60: approve a quarantined document by assigning its scientific field."""
    document_id: int = Field(ge=1)
    scientific_field: str = Field(min_length=2, max_length=120)
    domain: str | None = Field(default=None, max_length=120)


class DirectChatRequest(BaseModel):
    """§51: payload for the revived Sentinari Direct Chat console (/ui/direct)."""
    message: str = Field(min_length=1, max_length=24000)
    history: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = Field(default=None, max_length=120)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=64, le=8192)


class ModelLabRunRequest(BaseModel):
    """§51: payload for the revived Model Deviation Lab comparison run."""
    run_label: str = Field(default="", max_length=120)
    prompt: str = Field(min_length=1, max_length=24000)
    model: str | None = Field(default=None, max_length=120)
    include_gemma: bool = True
    manual_answers: list[dict[str, Any]] = Field(default_factory=list)


class PlaygroundQualiaSimulationRequest(BaseModel):
    behavior_variant: float = Field(default=0.1, ge=0.0, le=25.0)
    qualia_control: QualiaVectorControlRequest | None = None


class PlaygroundQualiaBenchmarkRequest(BaseModel):
    prompts: list[str] = Field(default_factory=list)
    top_k: int = Field(default=6, ge=0, le=20)
    apply_baseline: bool = True


class TaskCreateRequest(BaseModel):
    task_to_perform: str = Field(min_length=3, max_length=4000)
    target_datetime: str = Field(default="", max_length=80)
    quality_standard_expected: str = Field(default="", max_length=4000)
    knowledge_library_applicable: str = Field(default="", max_length=2000)
    smi_feedback: str = Field(default="", max_length=20000)
    evaluation: str = Field(default="", max_length=12000)
    status: Literal["pending", "in_progress", "completed", "blocked", "cancelled"] = "pending"


class TaskUpdateRequest(BaseModel):
    task_to_perform: str = Field(min_length=3, max_length=4000)
    target_datetime: str = Field(default="", max_length=80)
    quality_standard_expected: str = Field(default="", max_length=4000)
    knowledge_library_applicable: str = Field(default="", max_length=2000)
    smi_feedback: str = Field(default="", max_length=20000)
    evaluation: str = Field(default="", max_length=12000)
    status: Literal["pending", "in_progress", "completed", "blocked", "cancelled"] = "pending"


class QualiaRecommendationRequest(BaseModel):
    question: str = Field(default="", max_length=12000)
    answer: str = Field(default="", max_length=24000)
    citations: list[str] = Field(default_factory=list)
    session_id: str = Field(default="", max_length=120)
    behavior_variant: float = Field(default=0.1, ge=0.0, le=25.0)
    current_gamma: float = Field(default=0.2, ge=0.0, le=1.0)
    current_stability_bias: float = Field(default=0.65, ge=0.0, le=1.0)
    gamma_cap: float = Field(default=0.25, ge=0.0, le=0.25)
    qualia: dict[str, Any] = Field(default_factory=dict)


class PlaygroundVideoPlanRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=12000)
    language: str = Field(default="English", max_length=60)
    fps: int = Field(default=24, ge=8, le=32)
    max_scenes: int = Field(default=8, ge=1, le=20)


class PlaygroundVideoSceneRequest(BaseModel):
    duration: float = Field(default=4.0, ge=0.5, le=20.0)
    action: str = Field(default="march_forward", max_length=64)
    camera: str = Field(default="static", max_length=64)
    narration: str | None = Field(default=None, max_length=600)


class PlaygroundVideoRenderRequest(BaseModel):
    language: str = Field(default="English", max_length=60)
    fps: int = Field(default=24, ge=8, le=32)
    scenes: list[PlaygroundVideoSceneRequest] = Field(default_factory=list)
    filename_hint: str = Field(default="ttv", max_length=40)


class PlaygroundVideoStitchRequest(BaseModel):
    input_dir: str = Field(default="", max_length=600)
    seconds_per_image: float = Field(default=3.0, ge=0.2, le=20.0)
    fps: int = Field(default=24, ge=8, le=60)
    width: int = Field(default=1280, ge=320, le=3840)
    height: int = Field(default=720, ge=240, le=2160)
    filename_hint: str = Field(default="stitched", max_length=40)


class PlaygroundVideoWanRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=6000)
    task: Literal["t2v-1.3B", "t2v-14B"] = "t2v-1.3B"
    size: str = Field(default="832*480", max_length=20)
    ckpt_dir: str = Field(default="", max_length=800)
    wan_repo_dir: str = Field(default="", max_length=800)
    wan_python: str = Field(default="", max_length=800)
    offload_model: bool = True
    t5_cpu: bool = True
    sample_steps: int = Field(default=30, ge=8, le=80)
    sample_shift: float = Field(default=8.0, ge=0.0, le=30.0)
    sample_guide_scale: float = Field(default=6.0, ge=1.0, le=20.0)
    base_seed: int = Field(default=-1, ge=-1, le=2147483647)
    timeout_seconds: int = Field(default=3600, ge=120, le=10800)
    filename_hint: str = Field(default="wan2_1", max_length=40)


class TutorEvaluateRequest(BaseModel):
    module_id: str
    question_id: str
    answer: str


class AssessmentRunRequest(BaseModel):
    action: str = Field(default="status")
    sample_size: int = Field(default=10, ge=1, le=100)
    stage: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=500)


class EscalationQueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=12000)
    mode: Literal["knowledge", "coding", "autonomous"] = "coding"
    session_id: str = Field(default="", max_length=120)
    requested_by: str = Field(default="", max_length=120)
    source: str = Field(default="api", max_length=80)
    context: str = Field(default="", max_length=12000)
    citations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    title: str = Field(default="", max_length=200)


class GenericResponse(BaseModel):
    ok: bool = True
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


