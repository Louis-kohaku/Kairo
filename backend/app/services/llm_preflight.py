"""Shared LM Studio preflight check run before any job that talks to the
local LLM (AI production planning, AI edit). Actually queries /v1/models
and classifies the result *before* spending time on a chat completion that
would otherwise fail with a vague error - and logs each step so the job
log tells the full story instead of a single "ERROR: ..." line.
"""
from __future__ import annotations

from app.services import job_log, llm_client


def run_check(log_lines: list[str]) -> llm_client.LLMStatus:
    """Appends timestamped [LM_STUDIO] log lines to `log_lines` describing
    the check as it happens, and returns the resulting LLMStatus. Callers
    should treat `status.ready` as the gate for whether to proceed."""
    log_lines.append(job_log.timestamp_line("[LM_STUDIO] Checking server..."))
    log_lines.append(job_log.timestamp_line(f"[LM_STUDIO] API: {llm_client.LLM_BASE_URL}"))

    status = llm_client.get_status()

    log_lines.append(
        job_log.timestamp_line(f"[LM_STUDIO] Connection: {'OK' if status.server_reachable else 'NG'}")
    )
    if not status.server_reachable:
        log_lines.append(job_log.timestamp_line(f"[LM_STUDIO] ERROR: {status.error_code}"))
        return status

    log_lines.append(job_log.timestamp_line("[LM_STUDIO] Fetching available models..."))
    if not status.api_ok:
        log_lines.append(job_log.timestamp_line("[LM_STUDIO] Available models: fetch failed"))
        log_lines.append(job_log.timestamp_line(f"[LM_STUDIO] ERROR: {status.error_code}"))
        return status

    log_lines.append(job_log.timestamp_line(f"[LM_STUDIO] Available models: {len(status.models_loaded)}"))
    log_lines.append(job_log.timestamp_line(f"[LM_STUDIO] Requested model: {status.configured_model}"))
    log_lines.append(
        job_log.timestamp_line(
            f"[LM_STUDIO] Requested model found: {'YES' if status.configured_model_loaded else 'NO'}"
        )
    )

    if not status.ready:
        log_lines.append(job_log.timestamp_line(f"[LM_STUDIO] ERROR: {status.error_code}"))
        log_lines.append(job_log.timestamp_line("[LM_STUDIO] Available models:"))
        for model_id in status.models_loaded:
            log_lines.append(job_log.timestamp_line(f"  - {model_id}"))

    return status
