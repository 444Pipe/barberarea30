"""User authentication views and admin panel page views."""
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse

from .decorators import staff_required, admin_required, role_required


def admin_login_view(request):
    """Custom login page with Área 30 branding."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        # No manipular la contraseña: un .strip() rechazaría claves que empiezan
        # o terminan con espacios (válidas). Se toma tal cual la ingresa el usuario.
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect based on role
            profile = getattr(user, 'profile', None)
            if profile and profile.is_barber and not profile.is_admin:
                return redirect('admin_barber_agenda')
            return redirect('admin_dashboard')
        else:
            error = 'Credenciales inválidas'

    return render(request, 'admin/login.html', {'error': error})


def admin_logout_view(request):
    logout(request)
    return redirect('admin_login')


@staff_required
def admin_dashboard_view(request):
    """Dashboard principal — inyecta KPIs reales del día o la fecha seleccionada."""
    from apps.bookings.models import Booking
    from apps.cashflow.models import Sale
    from django.db.models import Sum, Count
    from django.utils import timezone
    import datetime

    profile = getattr(request.user, 'profile', None)
    
    date_str = request.GET.get('date')
    if date_str:
        try:
            today = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            today = timezone.localtime(timezone.now()).date()
    else:
        today = timezone.localtime(timezone.now()).date()

    # Calculate dates for navigation
    prev_date = today - datetime.timedelta(days=1)
    next_date = today + datetime.timedelta(days=1)
    is_today = (today == timezone.localtime(timezone.now()).date())

    base = Booking.objects.all()
    is_barber_only = profile and profile.is_barber and not profile.is_admin
    barber_profile = getattr(request.user, 'barber_profile', None) if is_barber_only else None
    if is_barber_only:
        base = base.filter(barber=barber_profile) if barber_profile else base.none()

    today_bookings = base.filter(date=today)
    today_completed = today_bookings.filter(status='completed').count()
    today_pending = today_bookings.filter(status__in=['pending', 'confirmed']).count()

    # Revenue today from Sales model (more accurate).
    # Solo contamos las ventas APROBADAS para que coincida con lo que muestra
    # Caja / Cierre Diario — antes el dashboard sumaba pendientes de aprobar,
    # generando discrepancias "a veces hay más, a veces menos plata".
    # Para un barbero, además restringimos a sus propias ventas.
    today_sales = Sale.objects.filter(
        created_at__date=today,
        approval_status=Sale.STATUS_APPROVED,
    )
    if is_barber_only:
        today_sales = today_sales.filter(barber=barber_profile) if barber_profile else today_sales.none()
    today_revenue = float(today_sales.aggregate(t=Sum('final_price'))['t'] or 0)
    today_tips = float(today_sales.aggregate(t=Sum('tip_amount'))['t'] or 0)

    # Top barber today
    top_today = (
        today_bookings.filter(status='completed')
        .values('barber__display_name')
        .annotate(cuts=Count('id'))
        .order_by('-cuts')
        .first()
    )

    pending_approvals_count = 0
    # Solo quienes pueden confirmar ventas (operational_admin/superadmin) ven el
    # panel de aprobaciones; el rol 'admin' recibía 403 del backend y el panel
    # quedaba roto.
    if profile and profile.role in ('operational_admin', 'superadmin'):
        pending_approvals_count = Sale.objects.filter(approval_status=Sale.STATUS_PENDING, included_in_daily_close__isnull=True).count()

    context = {
        'user_role': profile.role if profile else 'unknown',
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'dashboard',
        'today': today,
        'today_str': today.strftime('%Y-%m-%d'),
        'prev_date': prev_date.strftime('%Y-%m-%d'),
        'next_date': next_date.strftime('%Y-%m-%d'),
        'is_today': is_today,
        'today_completed': today_completed,
        'today_pending': today_pending,
        'today_revenue': today_revenue,
        'today_tips': today_tips,
        'top_barber_today': top_today['barber__display_name'] if top_today else '—',
        'pending_approvals_count': pending_approvals_count,
    }
    return render(request, 'admin/dashboard.html', context)


@staff_required
def admin_calendar_view(request):
    context = {
        'user_role': getattr(request.user, 'profile', None) and request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'calendar',
    }
    return render(request, 'admin/calendar.html', context)


from apps.cashflow.models import PaymentMethod

@staff_required
def admin_bookings_view(request):
    payment_methods = PaymentMethod.objects.filter(is_active=True)
    profile = getattr(request.user, 'profile', None)
    context = {
        'user_role': profile.role if profile else '',
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'bookings',
        'payment_methods': payment_methods,
    }
    return render(request, 'admin/bookings.html', context)


@staff_required
def admin_mis_reservas_view(request):
    """Reservas Personales: reutiliza la página de reservas pero pre-filtrada al
    perfil de barbero del usuario (Frank). Solo muestra sus propias citas."""
    payment_methods = PaymentMethod.objects.filter(is_active=True)
    profile = getattr(request.user, 'profile', None)
    try:
        my_barber_id = request.user.barber_profile.id
    except Exception:
        my_barber_id = 0  # sin perfil de barbero → no muestra ninguna reserva
    context = {
        'user_role': profile.role if profile else '',
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'mis_reservas',
        'payment_methods': payment_methods,
        'only_my_bookings': True,
        'my_barber_id': my_barber_id,
    }
    return render(request, 'admin/bookings.html', context)


@admin_required
def admin_barbers_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'barbers',
    }
    return render(request, 'admin/barbers.html', context)


@staff_required
def admin_barber_agenda_view(request):
    """Vista personal del barbero — su propia agenda."""
    context = {
        'user_role': getattr(request.user, 'profile', None) and request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'my_agenda',
    }
    return render(request, 'admin/barber_agenda.html', context)


@admin_required
def admin_clients_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'clients',
    }
    return render(request, 'admin/clients.html', context)


@admin_required
def admin_charts_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'charts',
    }
    return render(request, 'admin/charts.html', context)


@role_required('superadmin', 'admin')
def admin_settings_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'settings',
    }
    return render(request, 'admin/settings.html', context)


@staff_required
def admin_gallery_view(request):
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'gallery',
    }
    return render(request, 'admin/gallery.html', context)


@staff_required
def admin_reels_view(request):
    from apps.barbers.models import Barber
    barbers = Barber.objects.filter(is_available=True)
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'reels',
        'barbers': barbers,
    }
    return render(request, 'admin/reels.html', context)


from .decorators import operational_admin_required
from apps.cashflow.models import Sale, Expense, Commission, DailyClose
from django.db.models import Sum
from django.utils import timezone

@operational_admin_required
def admin_cashflow_view(request):
    from apps.cashflow.models import Sale, Expense, Commission, DailyClose, InventorySale, PaymentMethod
    from apps.inventory.models import InventoryItem
    from django.db.models import Sum
    from django.utils import timezone
    today = timezone.localtime(timezone.now()).date()
    
    # Pendientes por cerrar
    pending_sales = Sale.objects.filter(included_in_daily_close__isnull=True)
    pending_expenses = Expense.objects.filter(included_in_daily_close__isnull=True)
    pending_inventory_sales = InventorySale.objects.filter(included_in_daily_close__isnull=True)
    
    # Solo consideramos las ventas aprobadas para las finanzas y comisiones
    approved_sales = pending_sales.filter(approval_status=Sale.STATUS_APPROVED)
    
    # Pendientes de aprobación (para notificaciones de Frank)
    pending_approvals_count = pending_sales.filter(approval_status=Sale.STATUS_PENDING).count()

    # Totales parciales
    total_sales = approved_sales.aggregate(t=Sum('final_price'))['t'] or 0
    total_inventory_sales = pending_inventory_sales.aggregate(t=Sum('total_price'))['t'] or 0
    total_tips = approved_sales.aggregate(t=Sum('tip_amount'))['t'] or 0
    total_expenses = pending_expenses.aggregate(t=Sum('amount'))['t'] or 0
    
    # Comisiones parciales
    commissions = Commission.objects.filter(sale__in=approved_sales)
    total_commissions = commissions.aggregate(t=Sum('commission_amount'))['t'] or 0

    # Ingreso neto con la fórmula ÚNICA (cashflow.services) para que coincida
    # con el detalle en vivo y el cierre diario. La comisión de Frank se
    # descuenta por separado (su propina es pass-through, no afecta el neto).
    from apps.cashflow import services as cashflow_services
    frank_commission = commissions.filter(
        barber__display_name__icontains='frank'
    ).aggregate(t=Sum('commission_amount'))['t'] or 0
    non_frank_commissions = total_commissions - frank_commission

    net_income = cashflow_services.compute_live_net_income(
        service_revenue=total_sales,
        inventory_revenue=total_inventory_sales,
        non_frank_commissions=non_frank_commissions,
        real_expenses=total_expenses,
        frank_commission=frank_commission,
    )

    # El historial de cierres ahora se carga vía JS filtrable
    # (GET /api/admin/cashflow/daily-closes/), ya no por contexto.

    # Data for inventory sales modal
    inventory_items = InventoryItem.objects.filter(is_active=True).order_by('category', 'name')
    payment_methods = PaymentMethod.objects.filter(is_active=True).order_by('name')

    # Control de caja (efectivo/transferencia) con historial desglosado y saldo
    # derivado de Frank. Es la parte más nueva, compleja y pesada (recorre las
    # ventas/egresos/pagos/movimientos del período). Si algo falla —un dato raro,
    # un timeout de la BD, o el hueco de esquema en la ventana de un deploy— NO se
    # debe tumbar toda la página de finanzas: se registra el traceback real (visible
    # en los logs de Railway) y la caja se muestra en un estado de "no disponible".
    cash_box = None
    frank_ledger = None
    cash_box_error = False
    try:
        cash_box = cashflow_services.compute_cash_box_detail()
        frank_ledger = cashflow_services.compute_frank_ledger()
    except Exception:
        cash_box_error = True
        import logging as _logging, traceback as _traceback
        _logging.getLogger(__name__).error(
            "Fallo calculando el control de caja en /admin-panel/cashflow/:\n%s",
            _traceback.format_exc(),
        )
        # Estructura vacía con la MISMA forma para que el template no se rompa:
        # muestra todo en $0 y arriba se avisa que no se pudo cargar (ver logs).
        _empty_box = {
            'income': [], 'outflow': [], 'income_total': 0,
            'out_total': 0, 'opening': 0, 'balance': 0,
        }
        cash_box = {
            'period_start': None, 'period_start_label': None, 'last_cut': None,
            'cash': dict(_empty_box), 'transfer': dict(_empty_box),
        }
        frank_ledger = {'exists': False, 'balance': 0, 'suggested_payment': 0}

    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'cashflow',
        'today': today,
        'pending_sales_count': approved_sales.count() + pending_inventory_sales.count(),
        'pending_approvals_count': pending_approvals_count,
        # Jornada que sellaría el cierre. Entre medianoche y las 5 a.m. sigue
        # siendo la del día anterior, y se avisa en el encabezado.
        'business_date': cashflow_services.business_date(),
        'total_sales': total_sales,
        'total_inventory_sales': total_inventory_sales,
        'total_tips': total_tips,
        'total_expenses': total_expenses,
        'total_commissions': total_commissions,
        'net_income': net_income,
        'inventory_items': inventory_items,
        'payment_methods': payment_methods,
        'cash_box': cash_box,
        'frank_ledger': frank_ledger,
        'cash_box_error': cash_box_error,
    }
    return render(request, 'admin/cashflow.html', context)


@operational_admin_required
def admin_expenses_view(request):
    """Todas las salidas de dinero, no solo los egresos.

    Antes esta pantalla listaba únicamente el modelo `Expense`, así que los
    vales, las liquidaciones a barberos y los retiros no aparecían por ningún
    lado. El dueño veía un "Debe haber" en la caja que no lograba reconstruir
    aquí, y la diferencia parecía plata perdida.

    Ahora cuelga de `compute_outflows`, la misma función que alimenta la
    tarjeta de caja: con `period=caja` los dos totales son el mismo número por
    construcción (lo verifica ConciliacionTests).

    Parámetros GET:
      period      caja (desde el último corte) | rango | recientes
      date_from   / date_to   solo con period=rango, sobre la fecha del egreso
      source      cash | transfer
      category    cualquiera de OUTFLOW_CATEGORIES
    """
    from datetime import datetime
    from apps.cashflow import services as cashflow_services
    from apps.cashflow.models import Expense

    def _parse(value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    date_from = _parse(request.GET.get('date_from'))
    date_to = _parse(request.GET.get('date_to'))
    source = request.GET.get('source') or ''
    category = request.GET.get('category') or ''
    if source not in ('cash', 'transfer'):
        source = ''
    if category not in dict(cashflow_services.OUTFLOW_CATEGORIES):
        category = ''

    # El período por defecto es el de la caja: es el que hace que este total y
    # el "Debe haber" hablen del mismo dinero. Un rango de fechas explícito
    # gana, porque quien lo escribe está buscando otra cosa.
    period = request.GET.get('period') or ''
    if period not in ('caja', 'rango', 'recientes'):
        period = 'rango' if (date_from or date_to) else 'caja'
    if period != 'rango':
        date_from = date_to = None

    period_start = None
    last_cut = None
    try:
        period_start, _oc, _ot = cashflow_services.cash_period_bounds()
        last_cut = cashflow_services.current_cash_cut()
        rows = cashflow_services.compute_outflows(
            source=source or None,
            category=category or None,
            date_from=date_from,
            date_to=date_to,
            use_cash_period=(period == 'caja'),
        )
        # "Últimas 50" recorta ANTES de sumar: el total que se muestra encima
        # de la tabla tiene que ser el de las filas que se ven, no el del
        # histórico entero.
        if period == 'recientes':
            rows = rows[:50]
        summary = cashflow_services.summarize_outflows(rows)
        box = cashflow_services.compute_cash_box()
        outflows_error = False
    except Exception:
        # Misma política que la tarjeta de caja: un dato raro no debe tumbar la
        # página entera. Se avisa arriba y el traceback queda en los logs.
        import logging as _logging, traceback as _traceback
        _logging.getLogger(__name__).error(
            "Fallo listando las salidas en /admin-panel/expenses/:\n%s",
            _traceback.format_exc(),
        )
        rows, summary, box = [], {'total': 0, 'by_source': {}, 'by_category': []}, {}
        outflows_error = True

    # Cuadre contra la caja: solo tiene sentido cuando se está mirando
    # exactamente el período de la caja y sin filtros que recorten la lista.
    cuadre = None
    if period == 'caja' and not category and not outflows_error:
        esperado_cash = box.get('cash_out', 0)
        esperado_transfer = box.get('transfer_out', 0)
        if source == 'cash':
            esperado, obtenido = esperado_cash, summary['by_source'].get('cash', 0)
        elif source == 'transfer':
            esperado, obtenido = esperado_transfer, summary['by_source'].get('transfer', 0)
        else:
            esperado = esperado_cash + esperado_transfer
            obtenido = summary['total']
        cuadre = {
            'esperado': esperado,
            'obtenido': obtenido,
            'ok': esperado == obtenido,
            'diferencia': obtenido - esperado,
        }

    rows_visibles = rows

    period_label = {
        'caja': (
            f'Desde el corte del {timezone.localtime(period_start).strftime("%d/%m/%Y %I:%M %p")}'
            if period_start else 'Todo el histórico (nunca se ha hecho un corte)'
        ),
        'recientes': 'Últimas 50 salidas registradas',
        'rango': 'Rango de fechas elegido',
    }[period]

    role = request.user.profile.role
    tipos_permitidos = [
        (key, label) for key, label in Expense.EXPENSE_TYPES
        if key in cashflow_services.allowed_expense_types(role)
    ]

    context = {
        'user_role': role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'expenses',
        'rows': rows_visibles,
        'rows_total': len(rows),
        'summary': summary,
        'cuadre': cuadre,
        'outflows_error': outflows_error,
        'period': period,
        'period_label': period_label,
        'last_cut': last_cut,
        'source': source,
        'category': category,
        'categories': cashflow_services.OUTFLOW_CATEGORIES,
        'expense_types': tipos_permitidos,
        'date_from_str': date_from.strftime('%Y-%m-%d') if date_from else '',
        'date_to_str': date_to.strftime('%Y-%m-%d') if date_to else '',
    }
    return render(request, 'admin/expenses.html', context)


@operational_admin_required
def admin_inventory_view(request):
    from apps.inventory.models import InventoryItem
    items = InventoryItem.objects.all().order_by('category', 'name')
    
    # Calculate stats
    low_stock_count = sum(1 for item in items if item.is_low_stock)
    
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'inventory',
        'items': items,
        'low_stock_count': low_stock_count,
    }
    return render(request, 'admin/inventory.html', context)


from .decorators import superadmin_required

@superadmin_required
def admin_reports_view(request):
    from django.utils import timezone
    now = timezone.localtime(timezone.now())
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'reports',
        'current_year': now.year,
        'current_month': now.month,
    }
    return render(request, 'admin/reports.html', context)


@role_required('superadmin', 'admin')
def admin_audit_log_view(request):
    """Vista del Log de Auditoría. Solo accesible para superadmin y admin (batman).
    Frank (operational_admin) y barberos no tienen acceso."""
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'audit_log',
    }
    return render(request, 'admin/audit_log.html', context)


@superadmin_required
def admin_reviews_view(request):
    """Vista del panel de encuestas y calificaciones de clientes."""
    from apps.bookings.models import Review
    from apps.barbers.models import Barber
    from django.db.models import Avg, Count
    
    barbers = Barber.objects.filter(is_available=True).annotate(
        review_count=Count('bookings__review'),
        avg_rating=Avg('bookings__review__barber_rating')
    ).order_by('-avg_rating')
    
    reviews = Review.objects.select_related('booking__barber', 'booking__service').order_by('-created_at')[:50]
    
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'reviews',
        'barbers': barbers,
        'reviews': reviews,
    }
    return render(request, 'admin/reviews.html', context)


@operational_admin_required
def admin_manual_service_view(request):
    from apps.bookings.models import Booking
    from apps.services.models import Service
    from apps.barbers.models import Barber
    import json
    import uuid
    from django.utils.text import slugify
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            client_name = data.get('client_name', 'Cliente General')
            date = data.get('date')
            time = data.get('time')
            duration_minutes = int(data.get('duration_minutes', 60))
            manual_labor_cost = data.get('manual_labor_cost', 0)
            manual_materials_cost = data.get('manual_materials_cost', 0)
            
            description = data.get('description', '')
            materials_list = data.get('materials_list', [])
            barber_id = data.get('barber_id')
            custom_service_name = data.get('service_name', 'Servicio Manual').strip()
            if not custom_service_name:
                custom_service_name = 'Servicio Manual'
            
            # Resolver el barbero a partir del id que mandó el frontend.
            # Si el id no resuelve, NO caer silenciosamente a Frank — devolver
            # un error explícito para que el operador corrija. Si no se mandó
            # id, usar Frank por defecto (era la intención original).
            barber = None
            if barber_id:
                barber = Barber.objects.filter(id=barber_id).first()
                if not barber:
                    return JsonResponse({
                        'error': (
                            f'No existe ningún barbero con id={barber_id}. '
                            f'Refresca la página y vuelve a seleccionarlo en la lista.'
                        )
                    }, status=400)
            else:
                # Default histórico: Servicio Manual es de Frank.
                barber = Barber.objects.filter(user__first_name__icontains='frank').first()
                if not barber:
                    barber = Barber.objects.filter(display_name__icontains='frank').first()
                if not barber:
                    barber = getattr(request.user, 'barber_profile', None)

            # Buscamos o creamos el servicio personalizado
            service = Service.objects.filter(name__iexact=custom_service_name).first()
            if not service:
                base_slug = slugify(custom_service_name) or 'servicio-manual'
                unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
                is_frank = 'frank' in (barber.display_name.lower() if barber else '')
                service = Service.objects.create(
                    name=custom_service_name,
                    slug=unique_slug,
                    category='vip' if is_frank else 'individual',
                    price=0,
                    duration_minutes=duration_minutes,
                    is_active=False  # Oculto del agendamiento público
                )

            # The base price can just be labor + materials, but we also save the manual ones
            total_price = float(manual_labor_cost) + float(manual_materials_cost)

            notes = f'{custom_service_name} creado manualmente por admin.'
            if description:
                notes += f'\n\nDescripción del trabajo:\n{description}'
            
            if materials_list:
                notes += '\n\nMateriales Utilizados:'
                for mat in materials_list:
                    mat_price = float(mat.get('price', 0))
                    notes += f"\n- {mat.get('name', 'Material')}: ${mat_price:,.0f}".replace(',', '.')

            # Frank ocupa 2h por servicio, sin importar lo que mande el form;
            # el resto de barberos usa el valor enviado (o el del servicio).
            effective_duration = (
                barber.effective_duration_minutes(service)
                if barber is not None else duration_minutes
            )

            # Validar bloqueos antes de crear. Como en el walk-in, el bloqueo de
            # inactividad del BARBERO se puede forzar (con confirmación previa); el
            # local cerrado y el cruce con otra cita siguen siendo bloqueos firmes.
            from apps.bookings.validators import check_booking_conflict
            force = bool(data.get('force'))
            override_block_note = None
            err = check_booking_conflict(
                barber=barber, date=date, time=time,
                duration_minutes=effective_duration,
            )
            if err:
                hard_err = check_booking_conflict(
                    barber=barber, date=date, time=time,
                    duration_minutes=effective_duration,
                    check_unavailability=False,
                )
                if hard_err:
                    # Bloqueo firme (local cerrado o cruce con otra cita): no se fuerza.
                    return JsonResponse({'error': hard_err}, status=409)
                # El único bloqueo es la inactividad del barbero → se puede forzar.
                if not force:
                    return JsonResponse({
                        'requires_override': True,
                        'warning': err + ' ¿Deseas agendarlo de todos modos?',
                    }, status=409)
                override_block_note = err

            if override_block_note:
                notes = notes.rstrip() + '\n\n⚠ Agendado manualmente sobre un bloqueo de inactividad del barbero.'

            booking = Booking.objects.create(
                client_name=client_name,
                barber=barber,
                service=service,
                date=date,
                time=time,
                duration_minutes=effective_duration,
                price=total_price,
                manual_labor_cost=manual_labor_cost,
                manual_materials_cost=manual_materials_cost,
                status='confirmed',
                is_walk_in=True,
                notes=notes.strip()
            )

            return JsonResponse({'success': True, 'booking_id': booking.id})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=400)

    barbers = Barber.objects.filter(is_available=True)
    context = {
        'user_role': request.user.profile.role,
        'user_name': request.user.get_full_name() or request.user.username,
        'active_section': 'manual_service',
        'barbers': barbers,
    }
    return render(request, 'admin/manual_service.html', context)
