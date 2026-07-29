from django.core.management.base import BaseCommand, CommandError

from apps.organizations.exceptions import BootstrapConflictError
from apps.organizations.services import bootstrap_organization


class Command(BaseCommand):
    help = "Cria a organização inicial, OWNER e unidade sem receber senha pela linha de comando."

    def add_arguments(self, parser):
        parser.add_argument("--organization-name", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-name", required=True)
        parser.add_argument("--unit-name", required=True)

    def handle(self, *args, **options):
        try:
            result = bootstrap_organization(
                organization_name=options["organization_name"],
                slug=options["slug"],
                owner_email=options["owner_email"],
                owner_name=options["owner_name"],
                unit_name=options["unit_name"],
            )
        except BootstrapConflictError as exc:
            raise CommandError(str(exc)) from exc

        state = "criada" if result.created else "já existente e validada"
        self.stdout.write(self.style.SUCCESS(f"Fundação da organização {state}."))
        if not result.user.has_usable_password():
            self.stdout.write("Defina a senha com: python manage.py changepassword <email>")
