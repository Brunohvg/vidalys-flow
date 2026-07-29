from django.contrib import admin

from apps.organizations.models import Membership, Organization, OrganizationUnit

admin.site.register(Organization)
admin.site.register(OrganizationUnit)
admin.site.register(Membership)
