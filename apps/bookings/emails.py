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
    context = {
        'booking': booking,
        'survey_url': f"{domain}/rate/{booking.id}/"
    }
    _send_html_email(subject, 'emails/post_sale_survey.html', context, booking.client_email)

def send_barber_cancellation_notification(booking):
    """Notifica al barbero que una reserva fue cancelada por el cliente."""
    if not booking.barber or not booking.barber.user or not booking.barber.user.email:
        return
        
    subject = f"Reserva Cancelada: {booking.client_name}"
    domain = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    context = {
        'booking': booking,
        'site_url': domain
    }
    _send_html_email(subject, 'emails/barber_cancellation_notification.html', context, booking.barber.user.email)

def send_admin_new_booking_notification(booking):
    """Notifica a los administradores que se ha creado una nueva reserva."""
    from django.core.mail import send_mail
    from django.conf import settings as dj_settings
    
    admin_email = getattr(dj_settings, 'EMAIL_ADMIN', '')
    if not admin_email:
        return
        
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
