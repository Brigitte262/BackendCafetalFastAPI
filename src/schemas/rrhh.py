# src/schemas/rrhh.py
from typing import Optional, Literal, List
from pydantic import BaseModel

# ===================== Empleados =====================

class EmployeeOut(BaseModel):
    id: int
    doc_id: Optional[str] = None
    nombres: str
    apellidos: str
    email: Optional[str] = None
    telefono: Optional[str] = None
    position_id: Optional[int] = None
    base_salary: Optional[float] = None
    contract_type: Optional[str] = None
    # El router devuelve fechas como ISO string (p.ej. "2025-01-11")
    contract_start: Optional[str] = None
    contract_end: Optional[str] = None
    estado: Literal["activo", "inactivo"]
    fecha_ingreso: Optional[str] = None

class EmployeesPage(BaseModel):
    items: List[EmployeeOut]
    total: int
    page: int
    page_size: int

# Alias para compatibilidad con nombres anteriores
EmpleadoOut = EmployeeOut
EmpleadosPage = EmployeesPage

# ===================== Nómina (opcionales) =====================

class PayrollPeriodOut(BaseModel):
    id: int
    code: str
    start: str
    end: str
    is_closed: bool

class PayrollSummaryOut(BaseModel):
    period_id: Optional[int]
    empleados: int
    bruto: float
    deducciones: float
    neto: float
