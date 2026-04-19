from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.bookings.models import Booking
from apps.bookings.emails import send_post_sale_survey_email


class Command(BaseCommand):
    help = 'Sends post-sale surveys to clients 2 hours after completion if they have empty review'

    def handle(self, *args, **kwargs):
        # We target completed bookings without review, not yet surveyed, 
        # where completed_at is older than 2 hours.
        threshold_time = timezone.now() - timedelta(hours=2)
        
        # Consider ONLY bookings that actually specify an email and have a filled completed_at
        bookings_to_survey = Booking.objects.filter(
            status='completed',
            review__isnull=True,
            survey_sent=False,
            client_email__isnull=False,  # Exclude strictly unprovided emails
            completed_at__lte=threshold_time
        ).exclude(
            client_email='' # Ensure no empty string emails
        )
        
        count = 0
        
        for booking in bookings_to_survey:
            try:
                send_post_sale_survey_email(booking)
                # Mark as sent
                booking.survey_sent = True
                booking.save(update_fields=['survey_sent'])
                count += 1
                self.stdout.write(self.style.SUCCESS(f'Sent survey to {booking.client_email} for booking {booking.id}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to send to {booking.client_email}: {str(e)}'))
                
        self.stdout.write(self.style.SUCCESS(f'Finished sending {count} surveys.'))
