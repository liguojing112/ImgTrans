from __future__ import annotations

import argparse
from collections.abc import Sequence
import getpass

from server.app import create_app
from server.config import ServerSettings, ServerSettingsError
from server.admin.security import AdminSecurityError, hash_admin_password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ImgTrans backend service")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="validate configuration, database and routes without serving",
    )
    parser.add_argument(
        "--hash-admin-password",
        action="store_true",
        help="prompt for an administrator password and print its scrypt hash",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.hash_admin_password:
        try:
            password = getpass.getpass("Administrator password: ")
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                print("passwords_do_not_match")
                return 2
            print(hash_admin_password(password))
            return 0
        except AdminSecurityError as error:
            print(f"password_error: {error}")
            return 2
    try:
        settings = ServerSettings.from_env()
    except ServerSettingsError as error:
        print(f"configuration_error: {error}")
        return 2
    if arguments.smoke_test:
        app = create_app(settings)
        try:
            if not app.state.database.probe():
                print("database_unavailable")
                return 1
            route_paths = set(app.openapi().get("paths", {}))
            required = {
                "/health/live",
                "/health/ready",
                "/v1/service-info",
                "/v1/client-config",
                "/v1/translations",
                "/v1/models/manifest",
                "/v1/activations/validate",
                "/admin/login",
            }
            if not required.issubset(route_paths):
                print("route_contract_incomplete")
                return 1
            print("imgtrans-server ready api=v1")
            return 0
        finally:
            app.state.database.close()

    import uvicorn

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    return 0
