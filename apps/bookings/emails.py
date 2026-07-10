import re

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.core.signing import Signer


def _send_html_email(subject, template_name, context, to_email):
    if not to_email:
        return

    html_content = render_to_string(template_name, context)
    text_content = strip_tags(html_content)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email]
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send(fail_silently=True)


def _whatsapp_url(phone):
    """Construye un enlace wa.me/<digits> a partir del teléfono del cliente.

    - Strip de todo lo que no sea dígito.
    - Si el número quedó con 10 dígitos (formato local CO), antepone 57.
    - Devuelve None si no hay teléfono utilizable.
    """
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    if not digits:
        return None
    if len(digits) == 10 and not digits.startswith('57'):
        digits = '57' + digits
    return f'https://wa.me/{digits}'

def send_booking_confirmation_email(booking):
    """Sends a confirmation email for an upcoming booking."""
    subject = f"Confirmación de Reserva - Barbería Área 30"
    domain = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    signer = Signer()
    signed_id = signer.sign(booking.id)
    booking_url = f"{domain}/reserva/{signed_id}/"
    context = {
        'booking': booking,
        'site_url': domain,
        'booking_url': booking_url
    }
    _send_html_email(subject, 'emails/booking_confirmation.html', context, booking.client_email)

def send_booking_reminder_email(booking):
    """Sends a reminder email 2 hours before the appointment."""
    subject = f"¡Tu cita es pronto! - Barbería Área 30"
    context = {
        'booking': booking,
        'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000')
    }
    _send_html_email(subject, 'emails/booking_reminder.html', context, booking.client_email)

def send_post_sale_survey_email(booking):
    """Sends a post-sale survey email to the client after the appointment is complete."""
    subject = f"Encuesta de Satisfacción - Barbería Área 30"
    domain = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    signed_id = Signer().sign(booking.id)
    context = {
        'booking': booking,
        'survey_url': f"{domain}/rate/{signed_id}/"
    }
    _send_html_email(subject, 'emails/post_sale_survey.html', context, booking.client_email)

def send_barber_cancellation_notification(booking):
    """Notifica al barbero que una reserva fue cancelada por el cliente."""
    if not booking.barber or not booking.barber.user or not booking.barber.user.email:
        return

    subject = f"Cita cancelada: {booking.client_name} — {booking.date}"
    domain = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    context = {
        'booking': booking,
        'site_url': domain,
        'whatsapp_url': _whatsapp_url(booking.client_phone),
    }
    _send_html_email(
        subject,
        'emails/barber_cancellation_notification.html',
        context,
        booking.barber.user.email,
    )

def send_admin_new_booking_notification(booking):
    """Notifica a los administradores que se ha creado una nueva reserva."""
    from django.core.mail import send_mail
    from django.conf import settings as dj_settings
    
    # Enviar solo al correo del local para evitar que Hostinger lo reenvíe a todos
    admin_email = 'localarea30barberclub@gmail.com'
        
    subject = f"Nueva Reserva: {booking.client_name} - {booking.date}"
    message = (
        f"Se ha creado una nueva reserva en el sistema.\n\n"
        f"Cliente: {booking.client_name}\n"
        f"Teléfono: {booking.client_phone or 'No especificado'}\n"
        f"Fecha: {booking.date}\n"
        f"Hora: {booking.time}\n"
        f"Servicio: {booking.service.name if booking.service else 'No especificado'}\n"
        f"Barbero: {booking.barber.display_name if booking.barber else 'Cualquier barbero'}\n\n"
        f"Ingresa al panel de administración para más detalles."
    )
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=dj_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[admin_email],
            fail_silently=True,
        )
    except Exception as e:
        print("Error enviando notificación a admin:", e)

def send_barber_new_booking_notification(booking):
    """Notifica al barbero (si tiene correo) que se le ha asignado una nueva reserva.

    Usa el mismo HTML de marca (black/gold) que el correo al cliente,
    pero con el tono operacional propio del barbero: detalles de la cita,
    contacto directo al cliente por WhatsApp y enlace a su agenda.
    """
    if not booking.barber or not booking.barber.user or not booking.barber.user.email:
        return

    domain = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    subject = f"Nueva cita: {booking.client_name} — {booking.date}"
    context = {
        'booking': booking,
        'site_url': domain,
        'agenda_url': f'{domain}/admin-panel/barbers/my-agenda/',
        'whatsapp_url': _whatsapp_url(booking.client_phone),
    }
    try:
        _send_html_email(
            subject,
            'emails/barber_new_booking_notification.html',
            context,
            booking.barber.user.email,
        )
    except Exception as e:
        print("Error enviando notificación al barbero:", e)
