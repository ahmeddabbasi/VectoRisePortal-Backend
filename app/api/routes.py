from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.employee_routes import router as employee_router
from app.api.hrm_routes import router as hrm_router
from app.api.sales_routes import router as sales_router

router = sales_router

__all__ = ["router", "auth_router", "admin_router", "employee_router", "hrm_router", "sales_router"]
