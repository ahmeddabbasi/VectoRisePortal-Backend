from sqlalchemy.orm import Session

from app.models.system_setting import SystemSetting

DEFAULT_SETTINGS = {
    "check_in_grace_minutes": ("15", "Minutes after scheduled start for on-time check-in"),
    "check_out_grace_minutes": ("15", "Minutes after scheduled end for on-time checkout"),
    "schedule_deadline_day": ("4", "Day of week for schedule deadline (0=Mon, 4=Fri)"),
    "schedule_deadline_hour": ("17", "Hour on deadline day when schedules lock"),
    "daily_required_hours": ("8", "Required working hours per day"),
    "daily_max_hours": ("10", "Maximum working hours per day"),
    "weekly_required_hours": ("40", "Required working hours per week"),
    "weekly_max_hours": ("48", "Maximum working hours per week"),
    "default_start_time": ("09:00", "Default shift start time"),
    "default_end_time": ("17:00", "Default shift end time"),
    "default_break_minutes": ("60", "Default break duration in minutes"),
    "working_days": ("0,1,2,3,4", "Working days (0=Mon)"),
    "missed_schedule_penalty": ("5", "Performance penalty for missed schedule submission"),
    "weight_attendance": ("25", "Attendance weight %"),
    "weight_task_completion": ("30", "Task completion weight %"),
    "weight_deadline": ("20", "Deadline adherence weight %"),
    "weight_schedule": ("15", "Schedule adherence weight %"),
    "weight_evaluation": ("10", "HR evaluation weight %"),
    "incomplete_attendance_policy": ("incomplete", "Policy for missing check-in/out: incomplete or absent"),
}


class SettingsService:
    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[str, str] | None = None

    def _load_cache(self):
        if self._cache is None:
            rows = self.db.query(SystemSetting).all()
            self._cache = {key: val for key, (val, _) in DEFAULT_SETTINGS.items()}
            for row in rows:
                self._cache[row.key] = row.value

    def seed_defaults(self):
        for key, (value, description) in DEFAULT_SETTINGS.items():
            if not self.db.query(SystemSetting).filter(SystemSetting.key == key).first():
                self.db.add(SystemSetting(key=key, value=value, description=description))
        self._cache = None

    def get(self, key: str, default: str = "") -> str:
        self._load_cache()
        return self._cache.get(key, DEFAULT_SETTINGS.get(key, (default, ""))[0])

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except ValueError:
            return default

    def get_all(self) -> dict[str, str]:
        self._load_cache()
        return dict(self._cache)

    def set(self, key: str, value: str):
        row = self.db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = value
        else:
            self.db.add(SystemSetting(key=key, value=value))
        self._cache = None
