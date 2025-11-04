
# src/routers/rrhh.py
from fastapi import APIRouter, Query, HTTPException, Body
from fastapi.responses import StreamingResponse
from typing import Literal, List, Optional, Any, Dict
from sqlalchemy import text
from decimal import Decimal
from datetime import date, datetime
from fpdf import FPDF
from pydantic import BaseModel, Field
import os, hashlib, random, math
import io


# Usa el MISMO engine que tus otros routers
from src.core.db import engine

router = APIRouter(prefix="/rrhh", tags=["rrhh"])
NOMINA_FAKE = True

# ------------------ Modelos Pydantic ------------------
class EmployeeBase(BaseModel):
    doc_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    hire_date: date | None = None
    position_id: int | None = None
    base_salary: float | None = None
    status: Literal["ACTIVE", "INACTIVE"] | None = "ACTIVE"
    contract_type: str | None = None
    contract_start: date | None = None
    contract_end: date | None = None

class EmployeeCreate(EmployeeBase):
    # Requeridos mínimos para crear (ajusta a tu gusto)
    doc_id: str
    first_name: str
    last_name: str
    hire_date: date
    base_salary: float

class EmployeeUpdate(EmployeeBase):
    # PATCH parcial: todos opcionales
    pass

def _model_data(m: BaseModel) -> dict:
    # Compatibilidad Pydantic v1/v2
    return m.model_dump(exclude_unset=True) if hasattr(m, "model_dump") else m.dict(exclude_unset=True)

# ------------------ Crear empleado ------------------
@router.post("/empleados", status_code=201)
def create_employee(data: EmployeeCreate):
    payload = _model_data(data)
    if not payload.get("status"):
        payload["status"] = "ACTIVE"

    try:
        with engine.begin() as conn:
            new_id = conn.execute(text("""
                INSERT INTO cafetal.Employee
                    (doc_id, first_name, last_name, email, phone, hire_date,
                     position_id, base_salary, status, contract_type, contract_start, contract_end)
                OUTPUT INSERTED.employee_id
                VALUES
                    (:doc_id, :first_name, :last_name, :email, :phone, :hire_date,
                     :position_id, :base_salary, :status, :contract_type, :contract_start, :contract_end)
            """), payload).scalar_one()
    except Exception as e:
        import traceback; print("ERR POST /empleados:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    # Reusa tu endpoint de lectura para devolver el registro normalizado
    return get_employee(int(new_id))

# ------------------ Actualizar (PATCH parcial) ------------------
@router.patch("/empleados/{emp_id}")
def update_employee(emp_id: int, data: EmployeeUpdate):
    payload = _model_data(data)
    if not payload:
        raise HTTPException(400, "No enviaste campos para actualizar")

    # Mapea nombres del modelo -> columnas reales
    field_map = {
        "doc_id": "doc_id",
        "first_name": "first_name",
        "last_name": "last_name",
        "email": "email",
        "phone": "phone",
        "hire_date": "hire_date",
        "position_id": "position_id",
        "base_salary": "base_salary",
        "status": "status",
        "contract_type": "contract_type",
        "contract_start": "contract_start",
        "contract_end": "contract_end",
    }

    sets, params = [], {"id": emp_id}
    for k, v in payload.items():
        col = field_map.get(k)
        if not col:
            continue
        sets.append(f"{col} = :{k}")
        params[k] = v

    if not sets:
        raise HTTPException(400, "Los campos enviados no son válidos")

    sql = f"UPDATE cafetal.Employee SET {', '.join(sets)} WHERE employee_id = :id"

    try:
        with engine.begin() as conn:
            exists = conn.execute(text("SELECT 1 FROM cafetal.Employee WHERE employee_id=:id"), {"id": emp_id}).first()
            if not exists:
                raise HTTPException(404, "Empleado no encontrado")
            res = conn.execute(text(sql), params)
            if res.rowcount == 0:
                raise HTTPException(500, "No se pudo actualizar el empleado")
    except HTTPException:
        raise
    except Exception as e:
        import traceback; print("ERR PATCH /empleados/{id}:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    return get_employee(emp_id)

# ------------------ Eliminar (suave o duro) ------------------
@router.delete("/empleados/{emp_id}")
def delete_employee(emp_id: int, hard: bool = Query(False, description="Si true, borra físicamente")):
    try:
        with engine.begin() as conn:
            # verifica existencia
            row = conn.execute(text("SELECT status FROM cafetal.Employee WHERE employee_id=:id"), {"id": emp_id}).first()
            if not row:
                raise HTTPException(404, "Empleado no encontrado")

            if hard:
                # ⚠️ Podría fallar si hay FKs (p.ej., boletas)
                res = conn.execute(text("DELETE FROM cafetal.Employee WHERE employee_id=:id"), {"id": emp_id})
                if res.rowcount == 0:
                    raise HTTPException(500, "No se pudo eliminar")
                return {"ok": True, "deleted": True}
            else:
                res = conn.execute(text("UPDATE cafetal.Employee SET status='INACTIVE' WHERE employee_id=:id"), {"id": emp_id})
                if res.rowcount == 0:
                    raise HTTPException(500, "No se pudo inactivar")
    except HTTPException:
        raise
    except Exception as e:
        import traceback; print("ERR DELETE /empleados/{id}:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    # Devuelve el empleado ya inactivado (coincide con tu shape)
    return get_employee(emp_id)

def _cast(v):
    if v is None: return None
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, (date, datetime)): return v.isoformat()
    return v

def _row_map(row):
    # Compatible con SQLAlchemy 1.4/2.0
    if hasattr(row, "_mapping"):
        return row._mapping
    return row  # por si ya es dict

# Helpers SQL genéricos (conversión segura a JSON)
def _to_dict(m: dict) -> dict:
    return {k: _cast(v) for k, v in m.items()}

def db_query_all(sql: str, params: tuple = ()) -> list[dict]:
    try:
        with engine.begin() as conn:
            # Para placeholders "?"
            res = conn.exec_driver_sql(sql, params)
            rows = []
            for r in res:
                m = _row_map(r)
                rows.append(_to_dict(dict(m)))
            return rows
    except Exception as e:
        import traceback; print("ERR db_query_all:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

def db_query_one(sql: str, params: tuple = ()) -> dict | None:
    try:
        with engine.begin() as conn:
            row = conn.exec_driver_sql(sql, params).first()
            if not row:
                return None
            m = _row_map(row)
            return _to_dict(dict(m))
    except Exception as e:
        import traceback; print("ERR db_query_one:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# --- aquí, sin sangrado extra ---
def _rng_for(emp_id: int, period_id: int) -> random.Random:
    # misma semilla para mismo empleado + periodo → montos reproducibles
    seed = int(hashlib.sha1(f"{emp_id}:{period_id}".encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)

GENERATED_PDFS: set[tuple[int, int]] = set()  # (emp_id, period_id)

def _fake_has_pdf(emp_id: int, period_id: int) -> bool:
    return False

def _render_payslip_pdf(company: dict, period: dict, slip: dict) -> bytes:
    def S(v): return f"S/ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)

    # HEADER
    C_PRIMARY = (90, 35, 25)
    C_ACCENT  = (222, 215, 207)
    pdf.set_fill_color(*C_PRIMARY)
    pdf.rect(0, 0, 210, 28, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 16)
    pdf.set_xy(12, 8);  pdf.cell(0, 8, "CAFETAL SAC", ln=1)
    pdf.set_font("Arial", "", 10)
    pdf.set_x(12); pdf.cell(0, 6, f'RUC: {company.get("ruc","-")} · {company.get("address","-")}', ln=1)

    pdf.set_fill_color(*C_ACCENT)
    pdf.rect(0, 28, 210, 12, "F")
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(12, 31)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 6, f'Boleta de Pago - Periodo {period.get("code","")}', ln=1)

    pdf.ln(4)

    # Datos empleado
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, "Datos del Trabajador", ln=1)
    pdf.set_font("Arial", "", 10)
    pdf.cell(100, 6, f'Empleado: {slip["empleado"]}', ln=0)
    pdf.cell(0, 6,   f'Documento: {slip.get("doc_id") or "-"}', ln=1)
    pdf.cell(100, 6, f'ID: {slip["emp_id"]}', ln=0)
    pdf.cell(0, 6,   f'Correo: {slip.get("email") or "-"}', ln=1)
    pdf.cell(100, 6, f'Desde: {period.get("start","-")[:10]}', ln=0)
    pdf.cell(0, 6,   f'Hasta: {period.get("end","-")[:10]}', ln=1)

    # ⬇️ Fecha de emisión opcional (va aquí)
    if period.get("issue_date"):
        pdf.cell(0, 6, f'Emisión: {str(period["issue_date"])[:10]}', ln=1)

    pdf.ln(4)

    # Tabla
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, "Detalle", ln=1)
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(245, 245, 245)
    pdf.cell(95, 8, "Concepto", 1, 0, "L", True)
    pdf.cell(40, 8, "Haberes", 1, 0, "R", True)
    pdf.cell(40, 8, "Deducciones", 1, 1, "R", True)

    pdf.set_font("Arial", "", 10)
    def row(concepto, haber=0.0, ded=0.0):
        pdf.cell(95, 7, concepto, 1, 0, "L")
        pdf.cell(40, 7, S(haber) if haber else "-", 1, 0, "R")
        pdf.cell(40, 7, S(ded)   if ded   else "-", 1, 1, "R")

    base = float(slip["base_salary"] or 0)
    ot   = float(slip["overtime"] or 0)
    bon  = float(slip["bonus"] or 0)
    ded  = float(slip["deductions"] or 0)
    net  = float(slip["net"] or 0)

    row("Sueldo base", base, 0)
    row("Horas extra", ot, 0)
    row("Bonificaciones", bon, 0)
    row("Deducciones", 0, ded)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(95, 7, "Totales", 1, 0, "R")
    pdf.cell(40, 7, S(base + ot + bon), 1, 0, "R")
    pdf.cell(40, 7, S(ded), 1, 1, "R")

    pdf.ln(3)
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 10, f"NETO A RECIBIR: {S(net)}", ln=1, align="R")
    pdf.set_text_color(40, 40, 40)

    pdf.ln(8)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 5, "Este documento es informativo. Firmas y sellos físicos pueden ser requeridos según políticas internas.")

    # Firmas
    pdf.ln(14)
    y = pdf.get_y()
    pdf.line(25, y, 95, y)
    pdf.line(115, y, 185, y)
    pdf.set_y(y)
    pdf.set_font("Arial", "", 9)
    pdf.cell(70, 6, "Firma del Trabajador", 0, 0, "C")
    pdf.cell(40, 6, "", 0, 0)
    pdf.cell(70, 6, "Representante de CAFETAL", 0, 1, "C")

    # Retorno seguro (string -> bytes si hace falta)
    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", "replace")
    return out

def _fake_payslip_for_emp(m, period_id: int):
    """
    m: mapping con keys employee_id, first_name, last_name, doc_id, email, base_salary
    """
    base = float(m["base_salary"] or 0)
    R = _rng_for(m["employee_id"], period_id)
    overtime   = round(base * R.uniform(0.02, 0.10), 2)
    bonus      = round(base * R.uniform(0.00, 0.05), 2)
    deductions = round(base * R.uniform(0.00, 0.08), 2)
    net = base + overtime + bonus - deductions

    return {
        "id": f"{period_id}-{m['employee_id']}",
        "period_id": period_id,
        "emp_id": m["employee_id"],
        "doc_id": m["doc_id"],
        "empleado": f"{m['first_name']} {m['last_name']}",
        "base_salary": base,
        "overtime": overtime,
        "bonus": bonus,
        "deductions": deductions,
        "net": net,
        "email": m["email"],
    }

@router.get("/empleados")
def list_employees(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    estado: Literal["activo", "inactivo"] | None = None,
):
    off = (page - 1) * page_size
    where, params = [], {}

    if q:
        where.append("(e.first_name LIKE :q OR e.last_name LIKE :q OR e.doc_id LIKE :q)")
        params["q"] = f"%{q}%"

    if estado:
        where.append("e.status = :status")
        params["status"] = "ACTIVE" if estado == "activo" else "INACTIVE"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    try:
        with engine.begin() as conn:
            total = conn.execute(
                text(f"SELECT COUNT(*) FROM cafetal.Employee e {where_sql}"),
                params,
            ).scalar_one()

            res = conn.execute(
                text(f"""
                    SELECT
                        e.employee_id, e.doc_id, e.first_name, e.last_name,
                        e.email, e.phone, e.hire_date, e.position_id,
                        e.base_salary, e.status, e.contract_type,
                        e.contract_start, e.contract_end
                    FROM cafetal.Employee e
                    {where_sql}
                    ORDER BY e.employee_id
                    OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
                """),
                {**params, "off": off, "lim": page_size},
            )
            rows = [_row_map(r) for r in res]
    except Exception as e:
        # Muestra el error exacto en consola y devuelve detalle en dev
        import traceback; print("ERR /empleados:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    items = [{
        "id": r["employee_id"],
        "doc_id": r["doc_id"],
        "nombres": r["first_name"],
        "apellidos": r["last_name"],
        "email": r["email"],
        "telefono": r["phone"],
        "position_id": r["position_id"],
        "base_salary": _cast(r["base_salary"]),
        "contract_type": r["contract_type"],
        "contract_start": _cast(r["contract_start"]),
        "contract_end": _cast(r["contract_end"]),
        "estado": "activo" if r["status"] == "ACTIVE" else "inactivo",
        "fecha_ingreso": _cast(r["hire_date"]),
    } for r in rows]

    return {"items": items, "total": total, "page": page, "page_size": page_size}

@router.get("/empleados/{emp_id}")
def get_employee(emp_id: int):
    try:
        with engine.begin() as conn:
            r = conn.execute(
                text("""
                    SELECT
                        e.employee_id, e.doc_id, e.first_name, e.last_name,
                        e.email, e.phone, e.hire_date, e.position_id,
                        e.base_salary, e.status, e.contract_type,
                        e.contract_start, e.contract_end
                    FROM cafetal.Employee e
                    WHERE e.employee_id = :id
                """),
                {"id": emp_id},
            ).first()
    except Exception as e:
        import traceback; print("ERR /empleados/{id}:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    if not r:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    m = _row_map(r)
    return {
        "id": m["employee_id"],
        "doc_id": m["doc_id"],
        "nombres": m["first_name"],
        "apellidos": m["last_name"],
        "email": m["email"],
        "telefono": m["phone"],
        "position_id": m["position_id"],
        "base_salary": _cast(m["base_salary"]),
        "contract_type": m["contract_type"],
        "contract_start": _cast(m["contract_start"]),
        "contract_end": _cast(m["contract_end"]),
        "estado": "activo" if m["status"] == "ACTIVE" else "inactivo",
        "fecha_ingreso": _cast(m["hire_date"]),
    }

# ---------- Nómina: Periodos ----------
@router.get("/nomina/periodos")
def list_payroll_periods(limit: int = 24):
    if limit <= 0:
        limit = 24

    try:
        with engine.begin() as conn:
            # TOP no admite parámetro, pero limit ya es int validado
            rows = conn.execute(text(f"""
                SELECT TOP {int(limit)}
                    payroll_period_id AS id,
                    -- código legible yyyy-MM basado en period_start
                    CONCAT(YEAR(period_start), '-', RIGHT(CONCAT('0', MONTH(period_start)), 2)) AS code,
                    period_start      AS start,
                    period_end        AS [end],
                    CASE WHEN status = 'CLOSED' THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS is_closed
                FROM cafetal.PayrollPeriod
                ORDER BY period_start DESC
            """)).mappings().all()

        return {
            "items": [{k: _cast(v) for k, v in r.items()} for r in rows],
            "total": len(rows),
        }
    except Exception as e:
        import traceback; print("ERR /nomina/periodos:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# Pequeño helper: cómo se llama la FK de periodo en Payslip (period_id o payroll_period_id)
def _payslip_period_col(conn) -> str:
    names = {
        r[0] for r in conn.execute(text("""
            SELECT LOWER(c.name)
            FROM sys.columns c
            WHERE c.object_id = OBJECT_ID('cafetal.Payslip')
        """)).fetchall()
    }
    if "period_id" in names:
        return "period_id"
    if "payroll_period_id" in names:
        return "payroll_period_id"
    # Por defecto asumimos period_id; si no existe, el SQL fallará y veremos el nombre real
    return "period_id"


# ---------- Nómina: Resumen ----------
@router.get("/nomina/resumen")
def payroll_summary(period_id: int | None = None):
    # 1) período por defecto: último
    with engine.begin() as conn:
        if period_id is None:
            pid = conn.execute(text("""
                SELECT TOP 1 payroll_period_id
                FROM cafetal.PayrollPeriod
                ORDER BY period_start DESC
            """)).scalar()
            if not pid:
                return {"period_id": None, "empleados": 0, "bruto": 0.0, "deducciones": 0.0, "neto": 0.0}
            period_id = int(pid)

    if NOMINA_FAKE:
        with engine.begin() as conn:
            rows = conn.execute(text("""
                SELECT employee_id, first_name, last_name, doc_id, email, base_salary
                FROM cafetal.Employee
                WHERE status = 'ACTIVE'
            """)).fetchall()

        empleados = 0
        bruto = 0.0
        ded = 0.0
        neto = 0.0
        for r in rows:
            m = _row_map(r)
            slip = _fake_payslip_for_emp(m, period_id)
            empleados += 1
            bruto += (slip["base_salary"] + slip["overtime"] + slip["bonus"])
            ded += slip["deductions"]
            neto += slip["net"]

        return {
            "period_id": period_id,
            "empleados": empleados,
            "bruto": round(bruto, 2),
            "deducciones": round(ded, 2),
            "neto": round(neto, 2),
        }

# ---------- Nómina: Boletas (paginado) ----------
@router.get("/nomina/boletas")
def list_payslips(
    period_id: int | None = None,
    q: str = "",
    page: int = 1,
    page_size: int = 10,
):
    with engine.begin() as conn:
        if period_id is None:
            pid = conn.execute(text("""
                SELECT TOP 1 payroll_period_id
                FROM cafetal.PayrollPeriod
                ORDER BY period_start DESC
            """)).scalar()
            if not pid:
                return {"items": [], "total": 0, "page": page, "page_size": page_size}
            period_id = int(pid)

    off = (page - 1) * page_size
    params = {"q": q}
    where = ""
    if q:
        where = """
            AND ( first_name LIKE '%' + :q + '%'
               OR last_name  LIKE '%' + :q + '%'
               OR email      LIKE '%' + :q + '%'
               OR doc_id     LIKE '%' + :q + '%')
        """

    with engine.begin() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(1) FROM cafetal.Employee
            WHERE status = 'ACTIVE' {where}
        """), params).scalar_one()

        rows = conn.execute(text(f"""
            SELECT employee_id, first_name, last_name, doc_id, email, base_salary
            FROM cafetal.Employee
            WHERE status = 'ACTIVE' {where}
            ORDER BY first_name, last_name
            OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
        """), {**params, "off": off, "lim": page_size}).fetchall()

    items = []
    for r in rows:
        m = _row_map(r)
        fake = _fake_payslip_for_emp(m, period_id)
        # 👇 True si viene “de fábrica” o si ya lo generaste vía POST /generar_pdf
        fake["has_pdf"] = _fake_has_pdf(m["employee_id"], period_id) or ((m["employee_id"], period_id) in GENERATED_PDFS)
        items.append(fake)

    return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}


@router.get("/nomina/boleta_pdf")
def boleta_pdf(
    emp_id: int,
    period_id: int | None = None,
    base: float | None = None,
    overtime: float | None = None,
    bonus: float | None = None,
    deductions: float | None = None,
    net: float | None = None,
    issue_date: str | None = None,   # <-- NUEVO: fecha de emisión opcional (YYYY-MM-DD)
):
    with engine.begin() as conn:
        if period_id is None:
            row = conn.execute(text("""
                SELECT TOP 1 payroll_period_id, period_start, period_end
                FROM cafetal.PayrollPeriod
                ORDER BY period_start DESC
            """)).first()
            if not row:
                raise HTTPException(404, "No hay periodos")
            period_id = int(row[0]); period_start = row[1]; period_end = row[2]
        else:
            row = conn.execute(text("""
                SELECT payroll_period_id, period_start, period_end
                FROM cafetal.PayrollPeriod WHERE payroll_period_id = :pid
            """), {"pid": period_id}).first()
            if not row:
                raise HTTPException(404, "Periodo no encontrado")
            period_start, period_end = row[1], row[2]

        emp = conn.execute(text("""
            SELECT employee_id, first_name, last_name, doc_id, email, base_salary
            FROM cafetal.Employee WHERE employee_id = :eid
        """), {"eid": emp_id}).first()
        if not emp:
            raise HTTPException(404, "Empleado no encontrado")

        m = _row_map(emp)
        slip = _fake_payslip_for_emp(m, period_id)

    # overrides opcionales
    if base is not None:        slip["base_salary"] = float(base)
    if overtime is not None:    slip["overtime"]     = float(overtime)
    if bonus is not None:       slip["bonus"]        = float(bonus)
    if deductions is not None:  slip["deductions"]   = float(deductions)
    if net is None:
        slip["net"] = float(slip["base_salary"] + slip["overtime"] + slip["bonus"] - slip["deductions"])
    else:
        slip["net"] = float(net)

    company = {"name": "CAFETAL SAC", "ruc": "RUC 20XXXXXXXXX", "address": "Av. Café 123, Lima"}
    period  = {
        "code": f"{period_start:%Y-%m}",
        "start": period_start.isoformat(),
        "end": period_end.isoformat(),
        "issue_date": issue_date,  # <-- fecha de emisión opcional para mostrar
    }
    pdf_bytes = _render_payslip_pdf(company, period, slip)
    filename = f"Boleta_{slip['emp_id']}_{period['code']}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/nomina/generar_pdf")
def generar_pdf(emp_id: int, period_id: int):
    GENERATED_PDFS.add((emp_id, period_id))
    return {"ok": True}
