from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from datetime import datetime
from functools import wraps
import copy

app = Flask(__name__)
app.secret_key = "dev-secret-key-hht-mockup"

BREACH_PCT = 0.05

# ============================================================
# Demo in-memory database. No SQL / no external connections.
# ============================================================
DB = {
    "users": {
    "contratista_demo": {
        "username": "contratista_demo",
        "password": "123456",
        "role": "contratista",
        "company_id": "C001",
        "company_name": "ABC Servicios Industriales",
        "active": True,
    },
    "contratista_demo2": {
        "username": "contratista_demo2",
        "password": "1234567",
        "role": "contratista",
        "company_id": "C002",
        "company_name": "Mantenimiento Andino SAC",
        "active": True,
    },
    "admin_demo": {
        "username": "admin_demo",
        "password": "admin123",
        "role": "admin",
        "company_id": None,
        "company_name": "UNACEM",
        "active": True,
    },
    },
    "companies": [
        {"id": "C001", "name": "ABC Servicios Industriales", "active": True},
        {"id": "C002", "name": "Mantenimiento Andino SAC", "active": True},
        {"id": "C003", "name": "Proyectos del Pacífico", "active": True},
        {"id": "C004", "name": "Logística Cementera SAC", "active": False},
    ],
    "areas": ["Mantenimiento", "Operaciones", "Despacho", "Cantera", "Laboratorio", "Logística"],
    "periods": ["Agosto 2026", "Julio 2026"],
    "hht_reference": {"C001": 1000, "C002": 760, "C003": 0, "C004": 0},
    "distributions": {
        "C001": {
            "period": "Agosto 2026",
            "rows": [
                {"area": "Mantenimiento", "workers": 12, "days": 20, "hht": 520},
                {"area": "Operaciones", "workers": 8, "days": 17, "hht": 460},
            ],
            "status": "REGISTRADA",
            "submitted_at": "2026-09-02 09:30",
            "approved_by": None,
            "approved_at": None,
        },
        "C002": {
            "period": "Agosto 2026",
            "rows": [],
            "status": "NO REGISTRADA",
            "submitted_at": None,
            "approved_by": None,
            "approved_at": None,
        },
        "C003": {
            "period": "Agosto 2026",
            "rows": [{"area": "Laboratorio", "workers": 5, "days": 18, "hht": 720}],
            "status": "PENDIENTE DE APROBACIÓN",
            "submitted_at": "2026-09-03 15:45",
            "approved_by": None,
            "approved_at": None,
        },
        "C004": {
            "period": "Agosto 2026",
            "rows": [],
            "status": "EMPRESA INACTIVA",
            "submitted_at": None,
            "approved_by": None,
            "approved_at": None,
        },
    },
    "audit_log": [
        {
            "company_id": "C001",
            "action": "REGISTRO",
            "user": "contratista_demo",
            "date": "2026-09-02 09:30",
            "detail": "Registro inicial de distribución",
            "before": None,
            "after": 980,
        }
    ],
    "edit_requests": [],
}


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_user():
    username = session.get("username")
    user = DB["users"].get(username)
    if user and user.get("active", True):
        return user
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user or user["role"] != role:
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def total_hht(rows):
    return round(sum(float(row.get("hht", 0) or 0) for row in rows), 2)


def validate_rows(rows):
    if not isinstance(rows, list) or not rows:
        return False, "Agrega al menos un área."

    areas = []
    for row in rows:
        area = (row.get("area") or "").strip()
        if not area:
            return False, "Todas las filas deben tener un área."
        if area not in DB["areas"]:
            return False, "Se encontró un área no válida."
        areas.append(area)
        for field in ("workers", "days", "hht"):
            try:
                value = float(row.get(field, 0) or 0)
            except (TypeError, ValueError):
                return False, f"El campo {field} contiene un valor inválido."
            if value < 0:
                return False, f"El campo {field} no puede ser negativo."

    if len(areas) != len(set(areas)):
        return False, "No puedes repetir un área dentro de la distribución."
    return True, ""


def validation(reference, distributed):
    if reference == 0:
        return {"mode": "approval", "valid": True, "minimum": 0, "difference": distributed - reference}
    minimum = round(reference * (1 - BREACH_PCT), 2)
    return {
        "mode": "normal",
        "valid": distributed >= minimum,
        "minimum": minimum,
        "difference": round(distributed - reference, 2),
    }


def company_by_id(company_id):
    return next((c for c in DB["companies"] if c["id"] == company_id), None)


def serialize_company(company_id):
    company = company_by_id(company_id)
    record = DB["distributions"][company_id]
    reference = DB["hht_reference"][company_id]
    distributed = total_hht(record["rows"])
    return {
        "id": company_id,
        "name": company["name"],
        "active": company["active"],
        "reference": reference,
        "distributed": distributed,
        "pending": round(distributed - reference, 2),
        "status": record["status"],
        "period": record["period"],
        "rows": copy.deepcopy(record["rows"]),
        "submitted_at": record["submitted_at"],
        "approved_by": record.get("approved_by"),
        "approved_at": record.get("approved_at"),
    }


def serialize_audit(item):
    enriched = copy.deepcopy(item)
    company = company_by_id(item["company_id"])
    enriched["company_name"] = company["name"] if company else item["company_id"]
    return enriched


@app.route("/")
def index():
    return redirect(url_for("dashboard")) if current_user() else redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = DB["users"].get(username)
        if user and user.get("active", True) and user["password"] == password:
            session["username"] = username
            return redirect(url_for("dashboard"))
        flash("Usuario o contraseña incorrectos, o cuenta deshabilitada.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    if user["role"] == "admin":
        return render_template("admin.html", user=user, breach=BREACH_PCT, periods=DB["periods"])
    data = serialize_company(user["company_id"])
    return render_template("contractor.html", user=user, data=data, areas=DB["areas"], periods=DB["periods"], breach=BREACH_PCT)


@app.get("/api/contractor/state")
@role_required("contratista")
def contractor_state():
    return jsonify(serialize_company(current_user()["company_id"]))


@app.post("/api/contractor/register")
@role_required("contratista")
def contractor_register():
    user = current_user()
    company_id = user["company_id"]
    record = DB["distributions"][company_id]
    if record["status"] in {"REGISTRADA", "PENDIENTE DE APROBACIÓN"}:
        return jsonify(ok=False, message="El periodo ya fue registrado y está bloqueado."), 409

    payload = request.get_json(force=True) or {}
    period = payload.get("period") or record["period"]
    rows = payload.get("rows", [])
    valid_rows, message = validate_rows(rows)
    if not valid_rows:
        return jsonify(ok=False, message=message), 400

    reference = DB["hht_reference"][company_id]
    distributed = total_hht(rows)
    check = validation(reference, distributed)
    if check["mode"] == "normal" and not check["valid"]:
        return jsonify(ok=False, message=f"No se puede registrar. Debes distribuir al menos {check['minimum']:.2f} HHT para estar dentro de la brecha."), 400

    status = "PENDIENTE DE APROBACIÓN" if reference == 0 else "REGISTRADA"
    timestamp = now_text()
    DB["distributions"][company_id] = {
        "period": period,
        "rows": copy.deepcopy(rows),
        "status": status,
        "submitted_at": timestamp,
        "approved_by": None,
        "approved_at": None,
    }
    DB["audit_log"].append({
        "company_id": company_id,
        "action": "REGISTRO",
        "user": user["username"],
        "date": timestamp,
        "detail": "Registro sujeto a aprobación" if reference == 0 else "Registro inicial de distribución",
        "before": 0,
        "after": distributed,
    })
    return jsonify(ok=True, data=serialize_company(company_id))


@app.post("/api/contractor/edit-request")
@role_required("contratista")
def request_edit():
    user = current_user()
    company_id = user["company_id"]
    record = DB["distributions"][company_id]
    if record["status"] != "REGISTRADA":
        return jsonify(ok=False, message="Solo puedes solicitar modificación de una distribución registrada."), 400

    payload = request.get_json(force=True) or {}
    period = (payload.get("period") or record["period"]).strip()
    reason = (payload.get("reason") or "").strip()
    rows = payload.get("rows", [])
    if not reason:
        return jsonify(ok=False, message="El motivo de la modificación es obligatorio."), 400
    valid_rows, message = validate_rows(rows)
    if not valid_rows:
        return jsonify(ok=False, message=message), 400

    open_request = next((r for r in DB["edit_requests"] if r["company_id"] == company_id and r["status"] == "PENDIENTE"), None)
    if open_request:
        return jsonify(ok=False, message="Ya existe una solicitud de modificación pendiente."), 409

    timestamp = now_text()
    request_id = max([r["id"] for r in DB["edit_requests"]], default=0) + 1
    DB["edit_requests"].append({
        "id": request_id,
        "company_id": company_id,
        "period": period,
        "reason": reason,
        "rows": copy.deepcopy(rows),
        "status": "PENDIENTE",
        "created_at": timestamp,
        "created_by": user["username"],
    })
    DB["audit_log"].append({
        "company_id": company_id,
        "action": "SOLICITUD DE MODIFICACIÓN",
        "user": user["username"],
        "date": timestamp,
        "detail": reason,
        "before": total_hht(record["rows"]),
        "after": total_hht(rows),
    })
    return jsonify(ok=True, message="Corrección enviada a verificación del administrador.")


@app.get("/api/contractor/requests")
@role_required("contratista")
def contractor_requests():
    company_id = current_user()["company_id"]
    return jsonify([copy.deepcopy(r) for r in DB["edit_requests"] if r["company_id"] == company_id])


@app.get("/api/admin/overview")
@role_required("admin")
def admin_overview():
    return jsonify({"companies": [serialize_company(c["id"]) for c in DB["companies"]]})


@app.get("/api/admin/edit-requests")
@role_required("admin")
def edit_requests():
    enriched = []
    for r in DB["edit_requests"]:
        item = copy.deepcopy(r)
        company = company_by_id(r["company_id"])
        item["company_name"] = company["name"] if company else r["company_id"]
        enriched.append(item)
    return jsonify(enriched)


@app.get("/api/admin/audit")
@role_required("admin")
def audit():
    return jsonify([serialize_audit(x) for x in reversed(DB["audit_log"])])


@app.get("/api/admin/users")
@role_required("admin")
def users():
    items = []
    for user in DB["users"].values():
        item = {
            "username": user["username"],
            "role": user["role"],
            "company_id": user["company_id"],
            "company_name": user["company_name"],
            "active": user.get("active", True),
        }
        items.append(item)
    return jsonify(items)


@app.post("/api/admin/users")
@role_required("admin")
def create_user():
    payload = request.get_json(force=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    company_id = payload.get("company_id")
    if not username or not password or not company_id:
        return jsonify(ok=False, message="Usuario, contraseña y empresa son obligatorios."), 400
    if username in DB["users"]:
        return jsonify(ok=False, message="El nombre de usuario ya existe."), 409
    company = company_by_id(company_id)
    if not company:
        return jsonify(ok=False, message="Empresa no válida."), 400
    existing = next((u for u in DB["users"].values() if u.get("company_id") == company_id and u.get("role") == "contratista"), None)
    if existing:
        return jsonify(ok=False, message="La empresa ya tiene un usuario contratista."), 409

    DB["users"][username] = {
        "username": username,
        "password": password,
        "role": "contratista",
        "company_id": company_id,
        "company_name": company["name"],
        "active": True,
    }
    DB["companies"][[c["id"] for c in DB["companies"]].index(company_id)]["active"] = True
    DB["audit_log"].append({
        "company_id": company_id,
        "action": "CREACIÓN DE USUARIO",
        "user": current_user()["username"],
        "date": now_text(),
        "detail": f"Usuario creado: {username}",
        "before": None,
        "after": username,
    })
    return jsonify(ok=True, message="Usuario contratista creado.", data={"username": username, "company_name": company["name"]})


@app.post("/api/admin/company/<company_id>/toggle")
@role_required("admin")
def toggle_company(company_id):
    company = company_by_id(company_id)
    if not company:
        return jsonify(ok=False, message="Empresa no encontrada."), 404
    company["active"] = not company.get("active", True)
    DB["audit_log"].append({
        "company_id": company_id,
        "action": "HABILITACIÓN EMPRESA" if company["active"] else "DESHABILITACIÓN EMPRESA",
        "user": current_user()["username"],
        "date": now_text(),
        "detail": "Empresa marcada como activa para el periodo" if company["active"] else "Empresa marcada como inactiva para el periodo; no laboró",
        "before": not company["active"],
        "after": company["active"],
    })
    return jsonify(ok=True, active=company["active"])


@app.post("/api/admin/users/<username>/toggle")
@role_required("admin")
def toggle_user(username):
    user = DB["users"].get(username)
    if not user or user["role"] != "contratista":
        return jsonify(ok=False, message="Usuario no encontrado."), 404
    user["active"] = not user.get("active", True)
    DB["audit_log"].append({
        "company_id": user["company_id"],
        "action": "DESHABILITACIÓN" if not user["active"] else "HABILITACIÓN",
        "user": current_user()["username"],
        "date": now_text(),
        "detail": f"Usuario {username}",
        "before": not user["active"],
        "after": user["active"],
    })
    return jsonify(ok=True, active=user["active"])


@app.post("/api/admin/review")
@role_required("admin")
def admin_review():
    payload = request.get_json(force=True) or {}
    company_id = payload.get("company_id")
    action = payload.get("action")
    record = DB["distributions"].get(company_id)
    if not record or record["status"] != "PENDIENTE DE APROBACIÓN":
        return jsonify(ok=False, message="El registro ya no está pendiente."), 400

    timestamp = now_text()
    if action == "approve":
        record["status"] = "REGISTRADA"
        record["approved_by"] = current_user()["username"]
        record["approved_at"] = timestamp
        detail = "Registro aprobado"
    elif action == "reject":
        record["status"] = "DESAPROBADA"
        detail = "Registro desaprobado; no cuenta como HHT oficial"
    else:
        return jsonify(ok=False, message="Acción no válida."), 400

    DB["audit_log"].append({
        "company_id": company_id,
        "action": "APROBACIÓN" if action == "approve" else "DESAPROBACIÓN",
        "user": current_user()["username"],
        "date": timestamp,
        "detail": detail,
        "before": total_hht(record["rows"]),
        "after": total_hht(record["rows"]),
    })
    return jsonify(ok=True, data=serialize_company(company_id))


@app.post("/api/admin/edit-request/<int:request_id>")
@role_required("admin")
def review_edit_request(request_id):
    item = next((r for r in DB["edit_requests"] if r["id"] == request_id), None)
    if not item or item["status"] != "PENDIENTE":
        return jsonify(ok=False, message="Solicitud no disponible."), 400

    action = (request.get_json(force=True) or {}).get("action")
    timestamp = now_text()
    company_id = item["company_id"]
    original = DB["distributions"][company_id]

    if action == "approve":
        item["status"] = "APROBADA"
        before = total_hht(original["rows"])
        after = total_hht(item["rows"])
        DB["distributions"][company_id] = {
            "period": item["period"],
            "rows": copy.deepcopy(item["rows"]),
            "status": "REGISTRADA",
            "submitted_at": timestamp,
            "approved_by": current_user()["username"],
            "approved_at": timestamp,
        }
        detail = "Modificación aprobada y aplicada"
    elif action == "reject":
        item["status"] = "DESAPROBADA"
        before = total_hht(original["rows"])
        after = before
        detail = "Modificación desaprobada; se conserva versión anterior"
    else:
        return jsonify(ok=False, message="Acción no válida."), 400

    DB["audit_log"].append({
        "company_id": company_id,
        "action": "APROBACIÓN MODIFICACIÓN" if action == "approve" else "DESAPROBACIÓN MODIFICACIÓN",
        "user": current_user()["username"],
        "date": timestamp,
        "detail": f"{detail}. Motivo: {item['reason']}",
        "before": before,
        "after": after,
    })
    return jsonify(ok=True, data=serialize_company(company_id))





@app.post("/api/admin/company/<company_id>/direct-edit")
@role_required("admin")
def admin_direct_edit(company_id):
    company = company_by_id(company_id)
    record = DB["distributions"].get(company_id)
    if not company or not record:
        return jsonify(ok=False, message="Empresa no encontrada."), 404
    payload = request.get_json(force=True) or {}
    rows = payload.get("rows", [])
    valid_rows, message = validate_rows(rows)
    if not valid_rows:
        return jsonify(ok=False, message=message), 400

    reason = (payload.get("reason") or "").strip()
    if not reason:
        return jsonify(ok=False, message="El motivo de la modificación administrativa es obligatorio."), 400

    before = copy.deepcopy(record["rows"])
    record["rows"] = copy.deepcopy(rows)
    timestamp = now_text()
    record["submitted_at"] = timestamp
    DB["audit_log"].append({
        "company_id": company_id,
        "action": "MODIFICACIÓN DIRECTA ADMIN",
        "user": current_user()["username"],
        "date": timestamp,
        "detail": reason,
        "before": total_hht(before),
        "after": total_hht(rows),
    })
    return jsonify(ok=True, data=serialize_company(company_id))


@app.get("/api/admin/company/<company_id>")
@role_required("admin")
def admin_company(company_id):
    if company_id not in DB["distributions"]:
        return jsonify(ok=False, message="Empresa no encontrada."), 404
    return jsonify(serialize_company(company_id))


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
