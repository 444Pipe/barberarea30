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
