from django.contrib import admin
from .models import Partner, PartnerInvestment, MonthlyROISnapshot, PartnerMonthlyShare


class PartnerInvestmentInline(admin.TabularInline):
    model = PartnerInvestment
    extra = 1
    fields = ('amount', 'description', 'date')
    readonly_fields = ('created_at',)


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'share_percentage', 'is_active', 'created_at')
    inlines = [PartnerInvestmentInline]


class PartnerShareInline(admin.TabularInline):
    model = PartnerMonthlyShare
    extra = 0
    readonly_fields = (
        'partner', 'share_percentage', 'gross_share',
        'investment_balance_before', 'amortization_applied',
        'investment_balance_after', 'cash_out',
    )
    can_delete = False


@admin.register(MonthlyROISnapshot)
class MonthlyROISnapshotAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'year', 'month', 'net_income', 'is_locked', 'created_at')
    list_filter = ('year', 'is_locked')
    readonly_fields = ('created_at', 'created_by', 'net_income')
    inlines = [PartnerShareInline]

    def has_change_permission(self, request, obj=None):
        if obj and obj.is_locked:
            return False
        return super().has_change_permission(request, obj)
