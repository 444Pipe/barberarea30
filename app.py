from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    abort,
)
import os
import sqlite3
from datetime import datetime
import smtplib
from email.message import EmailMessage


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'bookings.db')

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-dev-secret')

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# Mapa de servicios para backend (slug -> nombre, precio entero en COP)
SERVICE_MAP = {
    'corte-basico':       {'name': 'Corte Básico',              'price': 30000},
    'corte-freestyle':    {'name': 'Corte + Freestyle',         'price': 35000},
    'corte-barba':        {'name': 'Corte con Barba',           'price': 40000},
    'corte-dama':         {'name': 'Corte para Dama',           'price': 35000},
    'freestyle-creativo': {'name': 'Corte + Freestyle Creativo','price': 40000},
    'asesoria-visajista': {'name': 'Asesoría Visajista',        'price': 60000},
    'rayitos-mechas':     {'name': 'Rayitos o Mechas',          'price': 225000},
    'trenzados':          {'name': 'Trenzados',                 'price': 70000},
}


@app.template_filter('time_12h')
def time_12h(value: str) -> str:
    """Convierte una hora HH:MM o HH:MM:SS a formato 12 horas (4:00 p.m.)."""

    if not value:
        return ''

    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            dt = datetime.strptime(value, fmt)
            # 04:00 PM -> 4:00 p.m.
            out = dt.strftime('%I:%M %p').lstrip('0')
            return (
                out.replace('AM', 'a.m.').replace('PM', 'p.m.')
            )
        except ValueError:
            continue

    return value


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS bookings (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               phone TEXT NOT NULL,
               email TEXT,
               service_slug TEXT NOT NULL,
               service_name TEXT NOT NULL,
               price INTEGER NOT NULL,
               date TEXT NOT NULL,
               time TEXT NOT NULL,
               notes TEXT,
               status TEXT NOT NULL DEFAULT 'pendiente',
               created_at TEXT NOT NULL,
               completed_at TEXT
           )'''
    )
    conn.commit()
    conn.close()


def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return view_func(*args, **kwargs)

    wrapper.__name__ = view_func.__name__
    return wrapper


def send_email(to_email: str, subject: str, body: str) -> None:
    """Envía un correo usando variables de entorno SMTP.

    Si no está configurado SMTP, solo registra en consola y no lanza error.
    """

    if not to_email:
        return

    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASSWORD')
    from_email = os.environ.get('SMTP_FROM', smtp_user)

    if not (smtp_host and smtp_user and smtp_pass and from_email):
        # Sin configuración SMTP, no enviamos pero tampoco rompemos la app
        print('[EMAIL] SMTP no configurado. Simulando envío a', to_email)
        print('Asunto:', subject)
        print('Cuerpo:', body)
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except Exception as e:
        print('[EMAIL] Error al enviar correo:', e)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/services')
def services():
    return render_template('services.html')


@app.route('/gallery')
def gallery():
    return render_template('gallery.html')


@app.route('/booking')
def booking():
    return render_template('booking.html')


# Compatibilidad con rutas .html directas
@app.route('/index.html')
def index_html():
    return render_template('index.html')


@app.route('/services.html')
def services_html():
    return render_template('services.html')


@app.route('/gallery.html')
def gallery_html():
    return render_template('gallery.html')


@app.route('/booking.html')
def booking_html():
    return render_template('booking.html')


# ───────────── API de reservas ─────────────

@app.route('/api/bookings', methods=['POST'])
def api_create_booking():
    data = request.get_json() or {}

    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip() or None
    service_slug = (data.get('service_slug') or '').strip()
    service_name = (data.get('service') or '').strip()
    date_str = (data.get('date') or '').strip()
    time_str = (data.get('time') or '').strip()
    notes = (data.get('notes') or '').strip() or None

    if not all([name, phone, service_slug, service_name, date_str, time_str]):
        return jsonify({'ok': False, 'error': 'Faltan campos obligatorios'}), 400

    svc_info = SERVICE_MAP.get(service_slug)
    if not svc_info:
        return jsonify({'ok': False, 'error': 'Servicio no válido'}), 400

    # Precio entero en COP; si el front manda price_num, usamos ese
    try:
        price = int(data.get('price_num') or svc_info['price'])
    except (TypeError, ValueError):
        price = svc_info['price']

    created_at = datetime.utcnow().isoformat(timespec='seconds')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO bookings (name, phone, email, service_slug, service_name, price, date, time, notes, status, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            name,
            phone,
            email,
            service_slug,
            service_name,
            price,
            date_str,
            time_str,
            notes,
            'pendiente',
            created_at,
        ),
    )
    booking_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Correo de confirmación al crear la reserva
    if email:
        subject = 'Reserva recibida – Barber Freestyle'
        body = (
            f'Hola {name},\n\n'
            f'Hemos recibido tu solicitud de cita en Barber Freestyle.\n\n'
            f'Servicio: {service_name}\n'
            f'Fecha: {date_str}\n'
            f'Hora: {time_str}\n'
            f'Precio estimado: ${price:,} COP\n\n'
            'Nos pondremos en contacto por WhatsApp para confirmar cualquier detalle.\n\n'
            'Barber Freestyle'
        )
        send_email(email, subject, body)

    return jsonify({'ok': True, 'id': booking_id})


# ───────────── Panel administrativo ─────────────


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = 'Credenciales inválidas'

    return render_template('admin_login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
@login_required
def admin_dashboard():
    conn = get_db_connection()
    bookings = conn.execute(
        'SELECT * FROM bookings ORDER BY date DESC, time DESC'
    ).fetchall()

    # Métricas de ingresos
    completed = [b for b in bookings if b['status'] == 'completado']
    total_ingresos = sum(b['price'] for b in completed) if completed else 0
    total_cortes = len(completed)
    promedio_por_corte = int(total_ingresos / total_cortes) if total_cortes else 0

    # Eventos para calendario (todas las reservas)
    calendar_events = []
    for b in bookings:
        calendar_events.append(
            {
                'id': b['id'],
                'title': f"{b['name']} - {b['service_name']}",
                'date': b['date'],
                'time': b['time'],
                'name': b['name'],
                'phone': b['phone'],
                'email': b['email'],
                'service_name': b['service_name'],
                'service_slug': b['service_slug'],
                'status': b['status'],
                'price': b['price'],
                'notes': b['notes'],
                'created_at': b['created_at'],
                'completed_at': b['completed_at'],
            }
        )

    # Ingresos por mes (solo reservas completadas)
    monthly_map = {}
    for b in completed:
        date_str = b['date']
        parsed_date = None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue

        if not parsed_date:
            continue

        key = parsed_date.strftime('%Y-%m')
        label = parsed_date.strftime('%b %Y')
        if key not in monthly_map:
            monthly_map[key] = {'label': label, 'total': 0}
        monthly_map[key]['total'] += b['price']

    monthly_keys = sorted(monthly_map.keys())
    monthly_labels = [monthly_map[k]['label'] for k in monthly_keys]
    monthly_totals = [monthly_map[k]['total'] for k in monthly_keys]

    conn.close()

    return render_template(
        'admin_dashboard.html',
        bookings=bookings,
        total_ingresos=total_ingresos,
        total_cortes=total_cortes,
        promedio_por_corte=promedio_por_corte,
        calendar_events=calendar_events,
        monthly_labels=monthly_labels,
        monthly_totals=monthly_totals,
    )


@app.post('/admin/bookings/<int:booking_id>/complete')
@login_required
def admin_complete_booking(booking_id: int):
    conn = get_db_connection()
    booking = conn.execute(
        'SELECT * FROM bookings WHERE id = ?', (booking_id,)
    ).fetchone()
    if not booking:
        conn.close()
        abort(404)

    if booking['status'] != 'completado':
        completed_at = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            'UPDATE bookings SET status = ?, completed_at = ? WHERE id = ?',
            ('completado', completed_at, booking_id),
        )
        conn.commit()

        # Correo de corte terminado
        if booking['email']:
            subject = 'Tu corte ha sido finalizado – Barber Freestyle'
            body = (
                f'Hola {booking["name"]},\n\n'
                f'Tu servicio "{booking["service_name"]}" ha sido marcado como completado.\n\n'
                'Gracias por confiar en Barber Freestyle.\n\n'
                'Te esperamos nuevamente.\n\n'
                'Barber Freestyle'
            )
            send_email(booking['email'], subject, body)

    conn.close()
    return redirect(url_for('admin_dashboard'))


@app.post('/admin/bookings/<int:booking_id>/cancel')
@login_required
def admin_cancel_booking(booking_id: int):
    conn = get_db_connection()
    booking = conn.execute(
        'SELECT * FROM bookings WHERE id = ?', (booking_id,)
    ).fetchone()
    if not booking:
        conn.close()
        abort(404)

    if booking['status'] != 'cancelado':
        conn.execute(
            'UPDATE bookings SET status = ? WHERE id = ?',
            ('cancelado', booking_id),
        )
        conn.commit()

    conn.close()
    return redirect(url_for('admin_dashboard'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    init_db()
    app.run(host='0.0.0.0', port=port, debug=debug)

