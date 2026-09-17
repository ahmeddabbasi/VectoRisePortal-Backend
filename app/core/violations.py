from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

VIOLATIONS: dict[str, dict] = {
    "check_in_window_closed": {
        "title": "Check-in window closed",
        "message": "You tried to check in after the allowed grace period. Your check-in was not recorded.",
        "steps": [
            "Open My Exceptions and find the late check-in record.",
            "Submit an explanation for why you were late.",
            "Wait for admin review — they may correct your attendance if approved.",
            "Contact your manager if you need to start work before the exception is resolved.",
        ],
        "link": "/employee/exceptions",
        "severity": "error",
    },
    "already_checked_in": {
        "title": "Already checked in",
        "message": "You have already checked in for today.",
        "steps": [
            "Use Check Out when you finish work for the day.",
            "If you need help correcting attendance, contact admin.",
        ],
        "link": "/employee/attendance",
        "severity": "error",
    },
    "must_check_in_first": {
        "title": "Check in required",
        "message": "You must check in before you can check out.",
        "steps": [
            "Tap Check In when you start work.",
            "If check-in is blocked, review My Exceptions for guidance.",
        ],
        "link": "/employee/dashboard",
        "severity": "error",
    },
    "already_checked_out": {
        "title": "Already checked out",
        "message": "You have already checked out for today.",
        "steps": [
            "Your attendance for today is complete.",
            "Contact admin if your hours need to be corrected.",
        ],
        "link": "/employee/attendance",
        "severity": "error",
    },
    "late_check_in": {
        "title": "Late check-in recorded",
        "message": "You checked in after your scheduled start time but within the grace period.",
        "steps": [
            "Your attendance is marked as late for today.",
            "If there was a valid reason, go to My Exceptions and add an explanation.",
        ],
        "link": "/employee/exceptions",
        "severity": "warning",
    },
    "early_check_out": {
        "title": "Early check-out recorded",
        "message": "You checked out before your scheduled end time.",
        "steps": [
            "Your attendance shows an early departure.",
            "If this was planned or approved, add a note under My Exceptions.",
        ],
        "link": "/employee/exceptions",
        "severity": "warning",
    },
    "late_check_out": {
        "title": "Late check-out recorded",
        "message": "You checked out after the allowed grace period. An exception has been created.",
        "steps": [
            "Review the late check-out record under My Exceptions.",
            "Submit an explanation if overtime or a delay was necessary.",
            "Wait for admin review if required.",
        ],
        "link": "/employee/exceptions",
        "severity": "warning",
    },
    "schedule_locked": {
        "title": "Schedule locked",
        "message": "This week's schedule is locked and cannot be edited directly.",
        "steps": [
            "Use the schedule change request form below.",
            "Describe what you need to change and why.",
            "Wait for admin approval before assuming the change is active.",
        ],
        "link": "/employee/schedule",
        "severity": "error",
    },
    "task_pending_approval": {
        "title": "Task awaiting approval",
        "message": "This task is still waiting for admin approval.",
        "steps": [
            "You cannot start or update it until it is approved.",
            "Check the Awaiting approval section on My Tasks.",
            "Contact your manager if approval is taking too long.",
        ],
        "link": "/employee/tasks",
        "severity": "error",
    },
    "task_rejected": {
        "title": "Task rejected",
        "message": "This task was not approved by admin.",
        "steps": [
            "Review the rejection reason on My Tasks.",
            "Submit a new task with clearer details if you still need the work logged.",
            "Contact your manager if you disagree with the decision.",
        ],
        "link": "/employee/tasks",
        "severity": "error",
    },
    "task_not_found": {
        "title": "Task not found",
        "message": "This task could not be found or is not assigned to you.",
        "steps": [
            "Refresh My Tasks and try again.",
            "Contact admin if a task is missing.",
        ],
        "link": "/employee/tasks",
        "severity": "error",
    },
    "invalid_time_log": {
        "title": "Timer error",
        "message": "The active timer could not be stopped.",
        "steps": [
            "Refresh My Tasks and check whether a timer is still running.",
            "Start a new timer only if no other timer is active.",
        ],
        "link": "/employee/tasks",
        "severity": "error",
    },
    "not_your_time_log": {
        "title": "Timer not allowed",
        "message": "You can only stop timers on your own tasks.",
        "steps": [
            "Return to My Tasks and use the timer on your assigned work.",
        ],
        "link": "/employee/tasks",
        "severity": "error",
    },
    "exception_not_found": {
        "title": "Exception not found",
        "message": "This exception could not be found on your record.",
        "steps": [
            "Refresh My Exceptions and try again.",
        ],
        "link": "/employee/exceptions",
        "severity": "error",
    },
}


def violation(code: str, **overrides) -> dict:
    base = VIOLATIONS.get(code, {
        "title": "Action not allowed",
        "message": "This action could not be completed.",
        "steps": ["Try again or contact admin if the issue continues."],
        "severity": "error",
    })
    payload = {**base, "code": code}
    payload.update(overrides)
    return payload


def raise_violation(
    db: Session | None,
    code: str,
    status_code: int = 400,
    commit: bool = False,
    **overrides,
) -> None:
    if commit and db is not None:
        db.commit()
    raise HTTPException(status_code=status_code, detail=violation(code, **overrides))
