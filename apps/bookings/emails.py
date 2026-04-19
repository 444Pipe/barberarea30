from django.core.mail import send_mail
from django.conf import settings

def send_booking_confirmation_email(booking):
    """
    Sends a confirmation email for an upcoming booking.
    """
    if not booking.client_email:
        return
        
    subject = f"Confirmación de Reserva - Barbería Área 30"
    message = (
        f"Hola {booking.client_name},\n\n"
        f"Tu reserva ha sido confirmada con éxito.\n"
        f"Detalles de la Cita:\n"
        f"- Fecha: {booking.date}\n"
        f"- Hora: {booking.time}\n"
        f"- Servicio: {booking.service.name if booking.service else 'N/A'}\n"
        f"- Barbero: {booking.barber.display_name if booking.barber else 'Cualquiera'}\n\n"
        f"Gracias por preferirnos.\n"
        f"¡Te esperamos!"
    )
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [booking.client_email],
        fail_silently=True,
    )

def send_post_sale_survey_email(booking):
    """
    Sends a post-sale survey email to the client after the appointment is complete.
    """
    if not booking.client_email:
        return
        
    subject = f"Encuesta de Satisfacción - Barbería Área 30"
    
    # URL to the review page. Adjust according to your router settings.
    # Assuming there's a view named 'review' or giving a placeholder URL.
    domain = getattr(settings, 'SITE_URL', 'http://localhost:8000') # Update to your production url
    survey_url = f"{domain}/bookings/review/{booking.id}/" # You might need a URL or token for the review
    
    message = (
        f"Hola {booking.client_name},\n\n"
        f"Esperamos que hayas disfrutado de tu servicio en Barbería Área 30.\n"
        f"Nos encantaría escuchar tus comentarios sobre tu experiencia.\n\n"
        f"Por favor tómate un minuto para dejarnos tu calificación:\n"
        f"{survey_url}\n\n"
        f"¡Gracias!"
    )
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [booking.client_email],
        fail_silently=True,
    )
