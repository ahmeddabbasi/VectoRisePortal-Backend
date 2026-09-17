import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.attendance_record import AttendanceRecord
from app.models.employee import Employee
from app.models.enums import AttendanceStatus, TaskStatus
from app.models.hr_evaluation import HREvaluation
from app.models.performance_score import PerformanceScore
from app.models.task import Task
from app.models.work_schedule import WorkSchedule
from app.services.settings_service import SettingsService


class PerformanceService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = SettingsService(db)

    def _attendance_score(self, employee_id: int, start: date, end: date) -> tuple[float, dict]:
        records = (
            self.db.query(AttendanceRecord)
            .filter(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.work_date >= start,
                AttendanceRecord.work_date <= end,
            )
            .all()
        )
        if not records:
            return 0.0, {"total_days": 0, "on_time": 0, "late": 0, "incomplete": 0}
        on_time = sum(1 for r in records if r.status == AttendanceStatus.ON_TIME)
        late = sum(1 for r in records if r.status == AttendanceStatus.LATE)
        incomplete = sum(1 for r in records if r.status == AttendanceStatus.INCOMPLETE)
        total = len(records)
        score = ((on_time + late * 0.7) / total) * 100 if total else 0
        return round(score, 2), {"total_days": total, "on_time": on_time, "late": late, "incomplete": incomplete}

    def _task_score(self, employee_id: int, start: date, end: date) -> tuple[float, dict]:
        tasks = (
            self.db.query(Task)
            .filter(
                Task.assigned_employee_id == employee_id,
                Task.created_at >= start,
                Task.created_at <= end + timedelta(days=1),
            )
            .all()
        )
        if not tasks:
            return 0.0, {"assigned": 0, "completed": 0, "overdue": 0}
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        overdue = sum(1 for t in tasks if t.status == TaskStatus.OVERDUE)
        completion_rate = (completed / len(tasks)) * 100
        deadline_score = max(0, completion_rate - (overdue / len(tasks) * 20))
        return round(completion_rate, 2), {
            "assigned": len(tasks),
            "completed": completed,
            "overdue": overdue,
            "deadline_score": round(deadline_score, 2),
        }

    def _schedule_score(self, employee_id: int, start: date, end: date) -> tuple[float, dict]:
        schedules = (
            self.db.query(WorkSchedule)
            .filter(
                WorkSchedule.employee_id == employee_id,
                WorkSchedule.week_start >= start,
                WorkSchedule.week_start <= end,
            )
            .all()
        )
        submitted_weeks = len({s.week_start for s in schedules if s.status in {"submitted", "locked"}})
        expected_weeks = max(1, (end - start).days // 7 + 1)
        score = min(100, (submitted_weeks / expected_weeks) * 100)
        return round(score, 2), {"submitted_weeks": submitted_weeks, "expected_weeks": expected_weeks}

    def _evaluation_score(self, employee_id: int, start: date, end: date) -> tuple[float, dict]:
        evals = (
            self.db.query(HREvaluation)
            .filter(
                HREvaluation.employee_id == employee_id,
                HREvaluation.period_start >= start,
                HREvaluation.period_end <= end,
            )
            .all()
        )
        if not evals:
            return 0.0, {"count": 0}
        avg = sum(e.score for e in evals) / len(evals)
        return round(avg, 2), {"count": len(evals), "average": round(avg, 2)}

    def calculate_score(self, employee_id: int, period_start: date, period_end: date, period_type: str = "weekly") -> PerformanceScore:
        w_att = self.settings.get_int("weight_attendance", 25)
        w_task = self.settings.get_int("weight_task_completion", 30)
        w_dead = self.settings.get_int("weight_deadline", 20)
        w_sched = self.settings.get_int("weight_schedule", 15)
        w_eval = self.settings.get_int("weight_evaluation", 10)

        att_score, att_detail = self._attendance_score(employee_id, period_start, period_end)
        task_score, task_detail = self._task_score(employee_id, period_start, period_end)
        sched_score, sched_detail = self._schedule_score(employee_id, period_start, period_end)
        eval_score, eval_detail = self._evaluation_score(employee_id, period_start, period_end)
        deadline_score = task_detail.get("deadline_score", task_score)

        total = (
            att_score * w_att / 100
            + task_score * w_task / 100
            + deadline_score * w_dead / 100
            + sched_score * w_sched / 100
            + eval_score * w_eval / 100
        )

        breakdown = {
            "weights": {
                "attendance": w_att,
                "task_completion": w_task,
                "deadline": w_dead,
                "schedule": w_sched,
                "evaluation": w_eval,
            },
            "scores": {
                "attendance": {"score": att_score, "detail": att_detail},
                "task_completion": {"score": task_score, "detail": task_detail},
                "deadline": {"score": deadline_score, "detail": task_detail},
                "schedule": {"score": sched_score, "detail": sched_detail},
                "evaluation": {"score": eval_score, "detail": eval_detail},
            },
            "formula": (
                f"({att_score}×{w_att}%)+({task_score}×{w_task}%)+"
                f"({deadline_score}×{w_dead}%)+({sched_score}×{w_sched}%)+({eval_score}×{w_eval}%)"
            ),
            "total": round(total, 2),
        }

        record = PerformanceScore(
            employee_id=employee_id,
            period_start=period_start,
            period_end=period_end,
            period_type=period_type,
            attendance_score=att_score,
            task_completion_score=task_score,
            deadline_score=deadline_score,
            schedule_score=sched_score,
            evaluation_score=eval_score,
            total_score=round(total, 2),
            breakdown=json.dumps(breakdown),
        )
        self.db.add(record)
        return record

    def employee_metrics(self, employee_id: int, start: date, end: date) -> dict:
        att_score, att_detail = self._attendance_score(employee_id, start, end)
        task_score, task_detail = self._task_score(employee_id, start, end)
        sched_score, sched_detail = self._schedule_score(employee_id, start, end)
        return {
            "attendance": att_detail,
            "tasks": task_detail,
            "schedule": sched_detail,
            "attendance_score": att_score,
            "task_score": task_score,
            "schedule_score": sched_score,
        }
