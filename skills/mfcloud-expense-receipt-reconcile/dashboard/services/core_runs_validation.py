from __future__ import annotations

from fastapi import HTTPException

from .core_runs_state import _workflow_state_for_ym


def _assert_run_mode_allowed(year: int, month: int, mode: str, *, _workflow_state_for_ym_fn=_workflow_state_for_ym) -> None:
    if mode in {"preflight", "preflight_mf"}:
        return
    state = _workflow_state_for_ym_fn(year, month)
    allowed = state.get("allowed_run_modes") if isinstance(state.get("allowed_run_modes"), list) else []
    if mode in allowed:
        return
    next_step = str(state.get("next_step") or "")
    allowed_label = ", ".join(str(x) for x in allowed) if allowed else "none"
    raise HTTPException(
        status_code=409,
        detail=(
            "Workflow order violation: "
            f"next_step={next_step}; allowed_modes={allowed_label}; requested_mode={mode}"
        ),
    )


def _assert_source_action_allowed(year: int, month: int, source: str, action: str, *, _workflow_state_for_ym_fn=_workflow_state_for_ym) -> None:
    if source not in {"amazon", "rakuten"}:
        raise HTTPException(status_code=400, detail="Invalid source.")
    if action not in {"confirm", "print"}:
        raise HTTPException(status_code=400, detail="Invalid action.")

    state = _workflow_state_for_ym_fn(year, month)
    if not state["preflight"]["done"]:
        raise HTTPException(
            status_code=409,
            detail="Workflow order violation: preflight is required before confirmation/print.",
        )

    branch = state["amazon"] if source == "amazon" else state["rakuten"]
    label = "amazon" if source == "amazon" else "rakuten"
    if not branch["downloaded"]:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow order violation: {label}_download must be completed before {label} confirmation/print.",
        )
    if action == "print" and not branch["confirmed"]:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow order violation: {label} confirmation is required before {label} print.",
        )


def _assert_archive_allowed(year: int, month: int, *, _workflow_state_for_ym_fn=_workflow_state_for_ym) -> None:
    state = _workflow_state_for_ym_fn(year, month)
    archive_state = state.get("archive") if isinstance(state.get("archive"), dict) else {}
    if bool(archive_state.get("can_archive")):
        return
    raise HTTPException(
        status_code=409,
        detail="Workflow order violation: archive requires at least one source to complete confirmation and print first.",
    )
