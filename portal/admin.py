from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Scheme, Application, ApplicationDocument, ApplicationStatusHistory, EligibilityAssessment, CompensationConfiguration, CompensationEstimate, OfficerRemark, Notification, AuditLog, AssistantFAQ

@admin.register(User)
class JanUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Jan Sutra profile', {'fields': ('role','mobile','address','district','taluka','village')}),)
    list_display = ('username','email','role','district','is_active')
    list_filter = ('role','district','is_active')

@admin.register(AssistantFAQ)
class AssistantFAQAdmin(admin.ModelAdmin):
    list_display = ('question','topic','active')
    list_filter = ('topic','active')
    search_fields = ('question','answer','keywords')

admin.site.register([Scheme, Application, ApplicationDocument, ApplicationStatusHistory, EligibilityAssessment, CompensationConfiguration, CompensationEstimate, OfficerRemark, Notification, AuditLog])
