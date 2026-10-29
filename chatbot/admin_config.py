from django.contrib.admin.apps import AdminConfig


class ProtectedAdminConfig(AdminConfig):
    default_site = 'chatbot.admin_site.ProtectedAdminSite'
